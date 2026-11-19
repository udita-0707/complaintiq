"""ONE-SHOT final evaluation on the TEST split (SPEC C4, C13: "test-set results reported once").

Do not run this during development. It runs only when every guard passes:

1. ``--confirm-final-test-eval`` is given;
2. ``configs/final_model.yaml`` exists and every field is filled, including ``frozen_date``;
3. ``reports/m4/test_results.md`` does NOT exist (the test split is read at most once);
4. the thresholds in ``final_model.yaml`` equal ``configs/thresholds.yaml``;
5. the saved model's ``meta.json`` matches ``model_version`` and ``data_version``;
6. the git working tree is clean (or ``--allow-dirty``, which is recorded in the report);
7. the environment variable ``CIQ_ALLOW_TEST=1`` is set by the person running it.

It prints what it will do before reading any file, then checks the guards, and only then
reads ``test.parquet``. The report records the git commit, data_version and model id.
No complaint text is printed or written.

Usage::

    CIQ_ALLOW_TEST=1 python scripts/final_test_eval.py --confirm-final-test-eval
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FINAL_CONFIG = REPO / "configs" / "final_model.yaml"
REPORT = REPO / "reports" / "m4" / "test_results.md"
RESULTS_JSON = REPO / "reports" / "m4" / "results" / "test_results.json"
REQUIRED = ("model_id", "model_dir", "model_version", "data_version", "run_ids", "thresholds",
            "frozen_date", "frozen_by")
THRESHOLD_KEYS = ("tau", "temperature_product", "temperature_issue", "priority_threshold")
TEST_ENV_VAR = "CIQ_ALLOW_TEST"

PLAN = """\
final_test_eval.py: ONE-SHOT evaluation on the TEST split.
Plan:
  1. read configs/final_model.yaml and configs/thresholds.yaml (configs only);
  2. check the guards (confirmation flag, freeze date, no existing report, thresholds,
     model meta, clean git tree, CIQ_ALLOW_TEST=1); stop at the first failure;
  3. only then read data/processed/time/test.parquet (narrative, labels, slice columns);
  4. score product, issue, priority with the frozen model and thresholds (no refitting);
  5. write reports/m4/test_results.md and reports/m4/results/test_results.json and log
     one run per task to reports/experiments/m4/final_test.csv.
After this the report exists and the script refuses to run again.
"""


def check_guards(
    final: dict[str, Any] | None,
    thresholds: dict[str, Any],
    report_path: Path,
    confirmed: bool,
    env: dict[str, str],
    git_dirty: bool,
    allow_dirty: bool,
    meta: dict[str, Any] | None,
) -> list[str]:
    """Every reason the final evaluation must not run (empty list = all guards pass)."""
    problems: list[str] = []
    if not confirmed:
        problems.append("missing --confirm-final-test-eval")
    if report_path.exists():
        problems.append(f"{report_path} already exists: the test split was already evaluated")
    if final is None:
        problems.append("configs/final_model.yaml is missing")
        return problems
    for key in REQUIRED:
        if final.get(key) in (None, "", {}):
            problems.append(f"final_model.yaml: '{key}' is not filled")
    fd = final.get("frozen_date")
    if fd not in (None, ""):
        try:
            dt.date.fromisoformat(str(fd))
        except ValueError:
            problems.append(f"final_model.yaml: frozen_date '{fd}' is not YYYY-MM-DD")
    ft = final.get("thresholds") or {}
    for k in THRESHOLD_KEYS:
        if k not in ft:
            problems.append(f"final_model.yaml: thresholds.{k} missing")
        elif k not in thresholds or float(ft[k]) != float(thresholds[k]):
            problems.append(f"thresholds.{k} differs from configs/thresholds.yaml")
    if meta is None:
        problems.append(f"model meta.json not found under {final.get('model_dir')}")
    else:
        for k in ("model_version", "data_version"):
            if meta.get(k) != final.get(k):
                problems.append(f"model meta {k}={meta.get(k)} != final_model.yaml {final.get(k)}")
        missing = {"product", "issue", "priority"} - set(meta.get("tasks", []))
        if missing:
            problems.append(f"model lacks tasks {sorted(missing)}")
    if git_dirty and not allow_dirty:
        problems.append("git working tree is dirty (commit first, or pass --allow-dirty)")
    if env.get(TEST_ENV_VAR) != "1":
        problems.append(
            f"set {TEST_ENV_VAR}=1 in the environment yourself to unlock the test split"
        )
    return problems


def _load_yaml(path: Path) -> dict[str, Any] | None:
    import yaml

    if not path.exists():
        return None
    return yaml.safe_load(path.read_text()) or {}


def evaluate(final: dict[str, Any], commit: str, allow_dirty: bool) -> dict[str, Any]:
    """Score the frozen model on test. Called only after every guard passed."""
    import numpy as np
    import polars as pl

    from complaintiq.config import load_config
    from complaintiq.data.load import resolve
    from complaintiq.data.training_data import LABEL_COLS, data_version, load_split
    from complaintiq.eval import metrics
    from complaintiq.eval.error_analysis import length_bucket
    from complaintiq.eval.tracking import log_run
    from complaintiq.models.baseline import (
        HIGH,
        TEXT_COL,
        BaselineModel,
        load_baseline_config,
        transform_chunked,
    )
    from complaintiq.models.calibrate import (
        apply_temperature,
        binary_at,
        coverage_precision,
        expected_calibration_error,
    )

    dv = data_version()
    if dv != final["data_version"]:
        raise SystemExit(f"data_version {dv} != frozen {final['data_version']}; refusing")
    th = final["thresholds"]
    ecfg = load_config("eval")
    data_cfg = load_config("data")
    model = BaselineModel.load(resolve(final["model_dir"]))
    test = load_split("test", columns=[TEXT_COL, *LABEL_COLS.values(), "date_received",
                                       "n_words", "company"])
    top_n = data_cfg["slices"]["top_companies"]
    top_companies = (
        load_split("train", columns=["company"]).group_by("company").len()
        .sort(["len", "company"], descending=[True, False]).head(top_n)["company"]
    )
    test = test.with_columns(
        year=pl.col("date_received").dt.year().cast(pl.Utf8),
        company_size=pl.when(pl.col("company").is_in(top_companies.implode()))
        .then(pl.lit(f"top {top_n} companies")).otherwise(pl.lit("other companies")),
        length_bucket=length_bucket(pl.col("n_words"), data_cfg["slices"]["length_bucket_edges"]),
    )
    X = transform_chunked(model.vectorizer, test[TEXT_COL],
                          load_baseline_config()["features"]["transform_chunk_rows"])
    res: dict[str, Any] = {"n_test": test.height, "commit": commit, "allow_dirty": allow_dirty,
                           "data_version": dv, "model_id": final["model_id"],
                           "model_version": final["model_version"],
                           "frozen_date": str(final["frozen_date"]), "thresholds": th,
                           "run_ids": {}}
    n_boot = ecfg["evaluation"]["n_boot"]
    for task in ("product", "issue"):
        labels, prob = model.scores(task, X)
        y = test[LABEL_COLS[task]].to_numpy()
        cal = apply_temperature(prob, float(th[f"temperature_{task}"]))
        pred = np.asarray(labels)[cal.argmax(axis=1)]
        m = metrics.compute_metrics(y, pred, labels, y_score=cal)
        ci = metrics.bootstrap_macro_f1_ci(y, pred, n_boot=n_boot, seed=int(ecfg["seed"]))
        correct = pred == y
        r = {"macro_f1": m["macro_f1"], "ci": ci, "weighted_f1": m["weighted_f1"],
             "accuracy": m["accuracy"], "top3": m["top3"],
             "ece": expected_calibration_error(cal.max(1), correct,
                                               ecfg["calibration"]["n_bins"]),
             "per_class": m["per_class"].to_dicts()}
        frame = test.select("year", "length_bucket", "company_size").with_columns(
            t=pl.Series(y), p=pl.Series(pred))
        r["slices"] = {s: metrics.slice_metrics(frame, "t", "p", s).to_dicts()
                       for s in ("year", "length_bucket", "company_size")}
        if task == "product":
            r["gate"] = coverage_precision(cal.max(1), correct, [float(th["tau"])]).to_dicts()[0]
        res[task] = r
        res["run_ids"][task] = log_run(
            "final_test", resolve(ecfg["experiments_dir"]), data_version=dv,
            model=final["model_id"], task=LABEL_COLS[task], seed=int(ecfg["seed"]),
            n_train=model.meta["n_train"], owner=ecfg["owner"],
            hyperparams={"thresholds": th, "frozen_date": str(final["frozen_date"])},
            val_macro_f1=r["macro_f1"], val_weighted_f1=r["weighted_f1"], val_top3=r["top3"],
            notes="FINAL TEST: val_* columns hold TEST metrics; one-shot, frozen model",
        )
    labels, prob = model.scores("priority", X)
    yb = (test[LABEL_COLS["priority"]].to_numpy() == HIGH).astype(int)
    score = prob[:, labels.index(HIGH)]
    res["priority"] = {"pr_auc": metrics.priority_metrics(yb, score, 0.5)["pr_auc"],
                       "base_rate": float(yb.mean()),
                       "at_threshold": binary_at(yb, score, float(th["priority_threshold"]))}
    res["run_ids"]["priority"] = log_run(
        "final_test", resolve(ecfg["experiments_dir"]), data_version=dv,
        model=final["model_id"], task="priority", seed=int(ecfg["seed"]),
        n_train=model.meta["n_train"], owner=ecfg["owner"], val_pr_auc=res["priority"]["pr_auc"],
        hyperparams={"thresholds": th}, notes="FINAL TEST: val_pr_auc holds the TEST PR-AUC",
    )
    return res


def write_report(res: dict[str, Any]) -> None:
    """Write the test report (aggregates only)."""
    out = [
        "# M4 final TEST results (one-shot)",
        "",
        "Generated once by `scripts/final_test_eval.py` after the model freeze. These are the"
        " only test-split numbers of the project; nothing was tuned on them.",
        "",
        f"- git commit `{res['commit']}`" + (" (dirty tree allowed)" if res["allow_dirty"] else ""),
        f"- data_version `{res['data_version']}`",
        f"- model id `{res['model_id']}`, model_version `{res['model_version']}`",
        f"- frozen on {res['frozen_date']}; thresholds {json.dumps(res['thresholds'])}",
        f"- test rows {res['n_test']:,}; run_ids "
        + ", ".join(f"{t} `{r}`" for t, r in res["run_ids"].items()),
        "",
        "| task | macro-F1 | 95% CI | weighted-F1 | accuracy | top-3 | ECE (calibrated) |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in ("product", "issue"):
        r = res[t]
        out.append(f"| {t} | {r['macro_f1']:.4f} | {r['ci']['lo']:.4f}-{r['ci']['hi']:.4f} |"
                   f" {r['weighted_f1']:.4f} | {r['accuracy']:.4f} | {r['top3']:.4f} |"
                   f" {r['ece']:.4f} |")
    g, p = res["product"]["gate"], res["priority"]
    out += [
        "",
        f"Gate at tau={g['threshold']:.4f}: coverage {g['coverage']:.4f}, precision"
        f" {g['precision']:.4f}.",
        "",
        f"Priority: PR-AUC {p['pr_auc']:.4f} (base rate {p['base_rate']:.4f}); at threshold"
        f" {p['at_threshold']['threshold']:.4f}: precision {p['at_threshold']['precision']:.4f},"
        f" recall {p['at_threshold']['recall']:.4f}.",
        "",
        "Per-class tables and slices: `reports/m4/results/test_results.json`.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Entry point: plan, guards, then (only if all pass) the test evaluation."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--confirm-final-test-eval", action="store_true", dest="confirm")
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args(argv)
    print(PLAN, flush=True)  # before reading anything

    sys.path.insert(0, str(REPO / "src"))
    from complaintiq.eval.tracking import git_commit

    final = _load_yaml(FINAL_CONFIG)
    thresholds = _load_yaml(REPO / "configs" / "thresholds.yaml") or {}
    meta = None
    if final and final.get("model_dir"):
        meta_path = REPO / str(final["model_dir"]) / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    if final:
        print(f"model id {final.get('model_id')}, data_version {final.get('data_version')},"
              f" frozen_date {final.get('frozen_date')}", flush=True)
    commit = git_commit()
    problems = check_guards(final, thresholds, REPORT, args.confirm, dict(os.environ),
                            commit.endswith("-dirty"), args.allow_dirty, meta)
    if problems:
        print("REFUSING to read the test split:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    print("All guards passed. Reading the test split now.", flush=True)
    res = evaluate(final, commit, args.allow_dirty)  # type: ignore[arg-type]
    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(res, indent=2, sort_keys=True, default=str))
    write_report(res)
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
