"""M4 evaluation report for the primary model on the validation split (SPEC C6).

Core metrics (macro/weighted F1, per-class P/R/F1, top-3, bootstrap CIs), slices (year,
narrative length bucket, company size), priority PR-AUC and P/R at the val-A threshold,
and a paired bootstrap against the M3 baseline. Results are for **val** (and the val-B
half where a threshold chosen on val-A is used). The test split is never read.

CLI::

    python -m complaintiq.eval.evaluation run
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from complaintiq.config import load_config
from complaintiq.data.load import resolve

logger = logging.getLogger("complaintiq.eval.evaluation")

SLICES = ("year", "length_bucket", "company_size")


def paired_bootstrap_macro_f1(
    y_true: Sequence[str],
    pred_a: Sequence[str],
    pred_b: Sequence[str],
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Paired percentile bootstrap of macro-F1(a) - macro-F1(b) on the same resampled rows.

    The label set is fixed once (classes with support in ``y_true``). Returns ``diff``,
    ``lo``, ``hi`` and ``p_le_0`` (share of resamples where a is not better than b).
    """
    from complaintiq.eval.metrics import _macro_f1_from_codes

    yt, pa, pb = (np.asarray(v) for v in (y_true, pred_a, pred_b))
    classes, codes = np.unique(np.concatenate([yt, pa, pb]), return_inverse=True)
    n = len(yt)
    t, a, b = codes[:n], codes[n: 2 * n], codes[2 * n:]
    k = len(classes)
    fixed = np.unique(t)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        diffs[i] = (_macro_f1_from_codes(t[idx], a[idx], k, fixed)
                    - _macro_f1_from_codes(t[idx], b[idx], k, fixed))
    return {
        "diff": _macro_f1_from_codes(t, a, k, fixed) - _macro_f1_from_codes(t, b, k, fixed),
        "lo": float(np.quantile(diffs, alpha / 2)),
        "hi": float(np.quantile(diffs, 1 - alpha / 2)),
        "p_le_0": float((diffs <= 0).mean()),
        "n_boot": float(n_boot),
    }


def _md(df: pl.DataFrame, digits: int = 3) -> str:
    def cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return "" if np.isnan(v) else f"{v:.{digits}f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    return "\n".join([head, sep, *("| " + " | ".join(cell(v) for v in r) + " |"
                                   for r in df.iter_rows())])


def _core(y: np.ndarray, pred: np.ndarray, labels: list[str], prob: np.ndarray | None,
          n_boot: int, seed: int) -> dict[str, Any]:
    from complaintiq.eval import metrics

    m = metrics.compute_metrics(y, pred, labels, y_score=prob)
    ci = metrics.bootstrap_macro_f1_ci(y, pred, n_boot=n_boot, seed=seed)
    return {"macro_f1": m["macro_f1"], "ci_lo": ci["lo"], "ci_hi": ci["hi"],
            "weighted_f1": m["weighted_f1"], "accuracy": m["accuracy"], "top3": m["top3"],
            "per_class": m["per_class"], "n": len(y)}


def run(reference_model: str = "tfidf_sgd") -> dict[str, Any]:
    """Compute every number of the evaluation report, log it and write the report."""
    from complaintiq.data.training_data import LABEL_COLS, load_split
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
    from complaintiq.models.calibrate import binary_at, split_val_ab

    ecfg = load_config("eval")
    cfg = ecfg["evaluation"]
    seed = int(ecfg["seed"])
    n_boot = int(cfg["n_boot"])
    vs = ecfg["val_split"]
    data_cfg = load_config("data")
    thresholds = load_config("thresholds")
    bcfg = load_baseline_config()
    chunk = bcfg["features"]["transform_chunk_rows"]
    model = BaselineModel.load(resolve(ecfg["primary_model_dir"]))
    meta = model.meta

    val = load_split("val", columns=[TEXT_COL, *LABEL_COLS.values(), "date_received",
                                     "n_words", "company"])
    top_n = data_cfg["slices"]["top_companies"]
    top_companies = (
        load_split("train", columns=["company"]).group_by("company").len()
        .sort(["len", "company"], descending=[True, False]).head(top_n)["company"]
    )
    val = val.with_columns(
        year=pl.col("date_received").dt.year().cast(pl.Utf8),
        company_size=pl.when(pl.col("company").is_in(top_companies.implode()))
        .then(pl.lit(f"top {top_n} companies")).otherwise(pl.lit("other companies")),
        length_bucket=length_bucket(pl.col("n_words"), data_cfg["slices"]["length_bucket_edges"]),
    )
    mask_a = split_val_ab(val[vs["stratify_col"]].to_numpy(), vs["frac_a"], vs["seed"])
    mask_b = ~mask_a
    X = transform_chunked(model.vectorizer, val[TEXT_COL], chunk)
    ref_dir = resolve(bcfg["artifacts_dir"]) / reference_model
    ref = BaselineModel.load(ref_dir) if (ref_dir / "meta.json").is_file() else None
    X_ref = transform_chunked(ref.vectorizer, val[TEXT_COL], chunk) if ref else None

    res: dict[str, Any] = {
        "model_id": ecfg["primary_model_id"], "model_version": meta["model_version"],
        "data_version": meta["data_version"], "n_val": val.height,
        "n_val_b": int(mask_b.sum()), "reference": f"baseline/{reference_model}" if ref else None,
        "run_ids": {},
    }
    exp_dir = resolve(ecfg["experiments_dir"])
    for task in ("product", "issue"):
        labels, prob = model.scores(task, X)
        y = val[LABEL_COLS[task]].to_numpy()
        pred = np.asarray(labels)[prob.argmax(axis=1)]
        r: dict[str, Any] = {
            "full": _core(y, pred, labels, prob, n_boot, seed),
            "val_b": _core(y[mask_b], pred[mask_b], labels, prob[mask_b], n_boot, seed),
        }
        frame = val.select(*SLICES).with_columns(t=pl.Series(y), p=pl.Series(pred))
        r["slices"] = {s: metrics.slice_metrics(frame, "t", "p", s) for s in SLICES}
        if ref is not None:
            rl, rp = ref.scores(task, X_ref)
            rpred = np.asarray(rl)[rp.argmax(axis=1)]
            r["paired_vs_reference"] = paired_bootstrap_macro_f1(y, pred, rpred, n_boot, seed)
        res[task] = r
        f = r["full"]
        res["run_ids"][task] = log_run(
            "evaluation", exp_dir, data_version=meta["data_version"],
            model=ecfg["primary_model_id"], task=LABEL_COLS[task],
            hyperparams={"n_boot": n_boot, "val_split": vs}, seed=seed,
            n_train=meta["n_train"], owner=ecfg["owner"], val_macro_f1=f["macro_f1"],
            val_weighted_f1=f["weighted_f1"], val_top3=f["top3"],
            notes=(f"evaluation report: full val n={f['n']}; macro-F1 95% CI"
                   f" {f['ci_lo']:.4f}-{f['ci_hi']:.4f}; val-B macro-F1"
                   f" {r['val_b']['macro_f1']:.4f}; fixed label set"),
        )

    labels, prob = model.scores("priority", X)
    y_bin = (val[LABEL_COLS["priority"]].to_numpy() == HIGH).astype(int)
    score = prob[:, labels.index(HIGH)]
    thr = thresholds.get("priority_threshold")
    pr = {
        "pr_auc_full": metrics.priority_metrics(y_bin, score, 0.5)["pr_auc"],
        "pr_auc_b": metrics.priority_metrics(y_bin[mask_b], score[mask_b], 0.5)["pr_auc"],
        "base_rate_full": float(y_bin.mean()),
        "at_0_5_full": binary_at(y_bin, score, 0.5),
        "threshold": thr,
        "at_thr_b": binary_at(y_bin[mask_b], score[mask_b], float(thr)) if thr else None,
    }
    sev_frame = val.select(*SLICES).with_columns(y=pl.Series(y_bin), s=pl.Series(score))
    pr["slices_pr_auc"] = {
        s: pl.DataFrame([
            {s: k, "n": part.height, "high_rate": float(part["y"].mean()),
             "pr_auc": metrics.priority_metrics(part["y"].to_numpy(), part["s"].to_numpy(),
                                                0.5)["pr_auc"] if part["y"].sum() else None}
            for (k,), part in sev_frame.group_by([s])
        ]).sort(s)
        for s in SLICES
    }
    res["priority"] = pr
    res["run_ids"]["priority"] = log_run(
        "evaluation", exp_dir, data_version=meta["data_version"],
        model=ecfg["primary_model_id"], task="priority", hyperparams={"threshold": thr},
        seed=seed, n_train=meta["n_train"], owner=ecfg["owner"], val_pr_auc=pr["pr_auc_full"],
        notes=(f"evaluation report: PR-AUC full val {pr['pr_auc_full']:.4f}, val-B"
               f" {pr['pr_auc_b']:.4f}; threshold from configs/thresholds.yaml (val-A)"),
    )
    _save(res, resolve(ecfg["reports_dir"]) / "results" / "evaluation.json")
    write_report(res, cfg, resolve(cfg["report_path"]))
    return res


def _save(res: dict[str, Any], path: Path) -> None:
    def conv(v: Any) -> Any:
        if isinstance(v, pl.DataFrame):
            return v.to_dicts()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(conv(res), indent=2, sort_keys=True))


def write_report(res: dict[str, Any], cfg: dict[str, Any], path: Path) -> None:
    """Markdown evaluation report."""
    thin = cfg["thin_class_rows"]
    out = [
        "# M4 evaluation report (VALIDATION results)",
        "",
        "Generated by `python -m complaintiq.eval.evaluation run` (`make eval-report`)."
        " **Every number here is on the validation split; the test split was not read.**"
        " Test results are produced once, after the freeze, by `scripts/final_test_eval.py`"
        " (TODO: not run).",
        "",
        f"- Model `{res['model_id']}` (model_version `{res['model_version']}`, data_version"
        f" `{res['data_version']}`). Input: narrative only.",
        f"- **full val** = all {res['n_val']:,} val rows. val was used in M3 to choose this model,"
        " so full-val numbers are not an unbiased estimate.",
        f"- **val-B** = the {res['n_val_b']:,}-row held-out half (configs/eval.yaml: val_split);"
        " thresholds were chosen on val-A, so threshold-dependent numbers are reported on val-B"
        " only.",
        "- Macro-F1 = mean F1 over classes with support (fixed label set); 95% CIs are"
        f" percentile bootstrap ({int(cfg['n_boot'])} resamples, seed 42).",
        "- Calibration (ECE, reliability, coverage-precision): `reports/m4/calibration_report.md`.",
        "- Logged runs: `reports/experiments/m4/evaluation.csv`, run_ids "
        + ", ".join(f"{t} `{r}`" for t, r in res["run_ids"].items()) + ".",
        "",
        "## Headline",
        "",
        "| task | split | n | macro-F1 | 95% CI | weighted-F1 | accuracy | top-3 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for task in ("product", "issue"):
        for split in ("full", "val_b"):
            f = res[task][split]
            out.append(
                f"| {task} | {'full val' if split == 'full' else 'val-B'} | {f['n']:,} |"
                f" {f['macro_f1']:.4f} | {f['ci_lo']:.4f}-{f['ci_hi']:.4f} |"
                f" {f['weighted_f1']:.4f} | {f['accuracy']:.4f} | {f['top3']:.4f} |"
            )
    pr = res["priority"]
    out += [
        "",
        f"Priority (HIGH): PR-AUC full val **{pr['pr_auc_full']:.4f}**, val-B"
        f" **{pr['pr_auc_b']:.4f}** (full-val HIGH base rate {pr['base_rate_full']:.4f}).",
        "",
        "| threshold | how chosen | split | precision | recall | F1 | flagged share |",
        "|---|---|---|---|---|---|---|",
    ]
    a = pr["at_0_5_full"]
    out.append(f"| 0.5000 | fixed (M3 default) | full val | {a['precision']:.4f} |"
               f" {a['recall']:.4f} | {a['f1']:.4f} | {a['flagged_share']:.4f} |")
    if pr["at_thr_b"]:
        b = pr["at_thr_b"]
        out.append(f"| {b['threshold']:.4f} | val-A, recall target (thresholds.yaml) | val-B |"
                   f" {b['precision']:.4f} | {b['recall']:.4f} | {b['f1']:.4f} |"
                   f" {b['flagged_share']:.4f} |")
    else:
        out.append("| TODO | run `make calibrate` first | | | | | |")
    if res.get("reference"):
        out += [
            "",
            f"## Significance vs the M3 baseline (`{res['reference']}`)",
            "",
            "Paired bootstrap on full val (same resampled rows for both models). diff ="
            " primary minus baseline macro-F1.",
            "",
            "| task | diff | 95% CI | share of resamples with diff <= 0 |",
            "|---|---|---|---|",
        ]
        for task in ("product", "issue"):
            p = res[task]["paired_vs_reference"]
            out.append(f"| {task} | {p['diff']:+.4f} | {p['lo']:+.4f} to {p['hi']:+.4f} |"
                       f" {p['p_le_0']:.3f} |")
    for task in ("product", "issue"):
        pc = res[task]["full"]["per_class"].filter(pl.col("support") > 0).with_columns(
            flag=pl.when(pl.col("support") < thin).then(pl.lit(f"<{thin} val rows"))
            .otherwise(pl.lit(""))
        ).sort("support", descending=True)
        out += [f"## {task}: per class (full val)", "", _md(pc), "", f"### {task}: slices", ""]
        for s, df in res[task]["slices"].items():
            out += [f"**{s}**", "", _md(df), ""]
    out += ["## priority: PR-AUC by slice (full val)", ""]
    for s, df in pr["slices_pr_auc"].items():
        out += [f"**{s}**", "", _md(df), ""]
    out += [
        "Slice notes: val covers 2022-09-13 to 2023-05-05 only, so the year slice has two"
        " values. `submitted_via` is 100% Web on narrative rows (M2), so the channel slice of"
        " SPEC C6 is not informative and is omitted.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n")


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m complaintiq.eval.evaluation")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--reference", default="tfidf_sgd")
    args = ap.parse_args(argv)
    res = run(args.reference)
    print(json.dumps({"run_ids": res["run_ids"]}, indent=2))


if __name__ == "__main__":
    main()
