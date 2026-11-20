"""M4 improvement iterations on the primary model (SPEC C6: hypothesis, change, result, logged).

Every choice (lambda, prior source, adopt or not) is made on **val-A**; **val-B** is the
held-out report. The primary model and the M3 defaults are never modified: iteration
outputs are only logged and reported. The test split is never read.

1. ``prior``: label-shift prior correction. With ``class_weight=balanced`` the classifier
   behaves as if classes were equally frequent; val (2022-09 to 2023-05) is dominated by
   credit reporting (60.5% vs 40.5% in train, M2 report). Change: ``p'(y|x) ~ p(y|x) *
   prior(y) ** lambda``, prior from train or val-A, lambda on a grid.
2. ``class_weight``: soften balanced weights to ``balanced ** power`` (retrains product
   and issue on train with the primary model's saved vectorizer).
3. ``consistency``: restrict issue predictions to issues seen with the predicted product in
   train (at least ``issue_product_min_rows`` rows).

CLI::

    python -m complaintiq.models.iterations run --only prior,consistency
    python -m complaintiq.models.iterations run --only class_weight
    python -m complaintiq.models.iterations report
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from complaintiq.config import load_config
from complaintiq.data.load import resolve

logger = logging.getLogger("complaintiq.models.iterations")

ITERATIONS = ("prior", "class_weight", "consistency")


# --------------------------------------------------------------------------- pure helpers


def prior_adjust(prob: np.ndarray, prior: np.ndarray, lam: float) -> np.ndarray:
    """Row-normalized ``prob * prior ** lam`` (``lam = 0`` leaves the argmax unchanged)."""
    p = np.asarray(prob, dtype=np.float64) * np.clip(np.asarray(prior), 1e-12, None) ** lam
    return p / p.sum(axis=1, keepdims=True)


def powered_class_weights(y: np.ndarray, power: float) -> dict[str, float]:
    """``balanced`` class weights (n / (k * n_c)) raised to ``power`` (1 = balanced, 0 = none)."""
    classes, counts = np.unique(y, return_counts=True)
    w = len(y) / (len(classes) * counts)
    return {str(c): float(v ** power) for c, v in zip(classes, w, strict=True)}


def allowed_issue_mask(
    products: np.ndarray, issues: np.ndarray, product_labels: list[str],
    issue_labels: list[str], min_rows: int,
) -> np.ndarray:
    """Boolean (n_products x n_issues): issue seen with product in at least ``min_rows`` rows.

    A product with no allowed issue keeps all issues (no restriction).
    """
    df = pl.DataFrame({"p": products, "i": issues}).group_by(["p", "i"]).len()
    pi = {p: k for k, p in enumerate(product_labels)}
    ii = {i: k for k, i in enumerate(issue_labels)}
    mask = np.zeros((len(product_labels), len(issue_labels)), dtype=bool)
    for p, i, n in df.iter_rows():
        if n >= min_rows and p in pi and i in ii:
            mask[pi[p], ii[i]] = True
    mask[~mask.any(axis=1)] = True
    return mask


def restrict_issues(issue_prob: np.ndarray, product_pred_idx: np.ndarray,
                    mask: np.ndarray) -> np.ndarray:
    """Zero issue probabilities not allowed for the predicted product, then renormalize."""
    p = issue_prob * mask[product_pred_idx]
    s = p.sum(axis=1, keepdims=True)
    return np.divide(p, s, out=issue_prob.copy(), where=s > 0)


def _scores(y: np.ndarray, labels: list[str], prob: np.ndarray) -> dict[str, float]:
    from complaintiq.eval.metrics import compute_metrics

    pred = np.asarray(labels)[prob.argmax(axis=1)]
    m = compute_metrics(y, pred, labels, y_score=prob)
    return {"macro_f1": m["macro_f1"], "weighted_f1": m["weighted_f1"],
            "accuracy": m["accuracy"], "top3": m["top3"]}


# --------------------------------------------------------------------------- context


class _Ctx:
    """Shared state for one ``run``: model, val probabilities, val-A/B masks."""

    def __init__(self) -> None:
        from complaintiq.data.training_data import LABEL_COLS, load_split
        from complaintiq.models.baseline import (
            TEXT_COL,
            BaselineModel,
            load_baseline_config,
            transform_chunked,
        )
        from complaintiq.models.calibrate import split_val_ab

        self.ecfg = load_config("eval")
        self.cfg = self.ecfg["iterations"]
        self.vs = self.ecfg["val_split"]
        self.chunk = load_baseline_config()["features"]["transform_chunk_rows"]
        self.model = BaselineModel.load(resolve(self.ecfg["primary_model_dir"]))
        self.meta = self.model.meta
        self.label_cols = LABEL_COLS
        self.val = load_split("val", columns=[TEXT_COL, LABEL_COLS["product"],
                                              LABEL_COLS["issue"]])
        self.mask_a = split_val_ab(self.val[self.vs["stratify_col"]].to_numpy(),
                                   self.vs["frac_a"], self.vs["seed"])
        self.X_val = transform_chunked(self.model.vectorizer, self.val[TEXT_COL], self.chunk)
        self.y = {t: self.val[LABEL_COLS[t]].to_numpy() for t in ("product", "issue")}
        self.prob = {t: self.model.scores(t, self.X_val) for t in ("product", "issue")}
        self.train_labels = load_split("train", columns=[LABEL_COLS["product"],
                                                         LABEL_COLS["issue"]])

    def split_scores(self, task: str, labels: list[str], prob: np.ndarray) -> dict[str, Any]:
        y = self.y[task]
        return {"val_a": _scores(y[self.mask_a], labels, prob[self.mask_a]),
                "val_b": _scores(y[~self.mask_a], labels, prob[~self.mask_a])}

    def log(self, name: str, task: str, hp: dict[str, Any], val_b: dict[str, float],
            notes: str) -> str:
        from complaintiq.eval.tracking import log_run

        return log_run(
            "iterations", resolve(self.ecfg["experiments_dir"]),
            data_version=self.meta["data_version"], model=f"{self.ecfg['primary_model_id']}+{name}",
            task=self.label_cols[task], hyperparams=hp, seed=int(self.ecfg["seed"]),
            n_train=self.meta["n_train"], owner=self.ecfg["owner"],
            val_macro_f1=val_b["macro_f1"], val_weighted_f1=val_b["weighted_f1"],
            val_top3=val_b["top3"],
            notes=f"iteration {name}: {notes}; val_* columns are val-B (held-out); fixed label set",
        )


# --------------------------------------------------------------------------- iterations


def iter_prior(ctx: _Ctx) -> dict[str, Any]:
    """Iteration 1: prior correction; source and lambda chosen on val-A macro-F1."""
    out: dict[str, Any] = {"tasks": {}}
    for task in ("product", "issue"):
        labels, prob = ctx.prob[task]
        col = ctx.label_cols[task]
        tr = ctx.train_labels[col].value_counts(normalize=True)
        tr_prior = dict(zip(tr[col].to_list(), tr["proportion"].to_list(), strict=True))
        ya = ctx.y[task][ctx.mask_a]
        va = {lbl: float((ya == lbl).mean()) for lbl in labels}
        sources = {"train": np.array([tr_prior.get(lbl, 0.0) for lbl in labels]),
                   "val_a": np.array([va[lbl] for lbl in labels])}
        grid = []
        for src, prior in sources.items():
            for lam in ctx.cfg["prior_lambdas"]:
                s = ctx.split_scores(task, labels, prior_adjust(prob, prior, lam))
                grid.append({"source": src, "lambda": lam, **{f"a_{k}": v for k, v in
                             s["val_a"].items()}, **{f"b_{k}": v for k, v in s["val_b"].items()}})
        g = pl.DataFrame(grid)
        best = g.sort(["a_macro_f1", "lambda"], descending=[True, False]).row(0, named=True)
        base = g.filter(pl.col("lambda") == 0.0).row(0, named=True)
        adopt = bool(best["lambda"] > 0 and best["a_macro_f1"] > base["a_macro_f1"])
        b = {k[2:]: v for k, v in best.items() if k.startswith("b_")}
        rid = ctx.log("prior", task, {"source": best["source"], "lambda": best["lambda"],
                                      "grid": ctx.cfg["prior_lambdas"]}, b,
                      f"chosen on val-A source={best['source']} lambda={best['lambda']};"
                      f" baseline val-B macro-F1 {base['b_macro_f1']:.4f}; adopt={adopt}")
        out["tasks"][task] = {"grid": g.to_dicts(), "best": best, "base": base,
                              "adopt": adopt, "run_id": rid}
    return out


def iter_consistency(ctx: _Ctx) -> dict[str, Any]:
    """Iteration 3: restrict issue to issues seen with the predicted product in train."""
    p_labels, p_prob = ctx.prob["product"]
    i_labels, i_prob = ctx.prob["issue"]
    pc, ic = ctx.label_cols["product"], ctx.label_cols["issue"]
    mask = allowed_issue_mask(ctx.train_labels[pc].to_numpy(), ctx.train_labels[ic].to_numpy(),
                              p_labels, i_labels, ctx.cfg["issue_product_min_rows"])
    # Measured motivation: issue errors whose predicted issue is not allowed for the TRUE product.
    yp, yi = ctx.y["product"], ctx.y["issue"]
    i_pred = np.asarray(i_labels)[i_prob.argmax(axis=1)]
    p_idx = {p: k for k, p in enumerate(p_labels)}
    i_idx = {i: k for k, i in enumerate(i_labels)}
    err = i_pred != yi
    cross = np.array([not mask[p_idx[p], i_idx[i]] for p, i in zip(yp, i_pred, strict=True)])
    new = restrict_issues(i_prob, p_prob.argmax(axis=1), mask)
    before = ctx.split_scores("issue", i_labels, i_prob)
    after = ctx.split_scores("issue", i_labels, new)
    adopt = bool(after["val_a"]["macro_f1"] > before["val_a"]["macro_f1"])
    rid = ctx.log("consistency", "issue",
                  {"issue_product_min_rows": ctx.cfg["issue_product_min_rows"],
                   "allowed_pairs": int(mask.sum())}, after["val_b"],
                  f"issue errors with predicted issue not seen with the true product:"
                  f" {cross[err].mean():.4f} of {int(err.sum())}; baseline val-B macro-F1"
                  f" {before['val_b']['macro_f1']:.4f}; adopt={adopt}")
    return {"allowed_pairs": int(mask.sum()), "n_pairs": int(mask.size),
            "issue_errors": int(err.sum()), "cross_product_share": float(cross[err].mean()),
            "before": before, "after": after, "adopt": adopt, "run_id": rid}


def iter_class_weight(ctx: _Ctx) -> dict[str, Any]:
    """Iteration 2: retrain product and issue with ``balanced ** power`` class weights."""
    from complaintiq.data.training_data import load_split
    from complaintiq.models.baseline import (
        TEXT_COL,
        build_classifier,
        fit_with_convergence,
        transform_chunked,
    )

    params = dict(ctx.meta["hyperparams"])
    seed = int(load_config("baseline")["seed"])
    tasks = ("product", "issue")
    train = load_split("train", columns=[TEXT_COL, *(ctx.label_cols[t] for t in tasks)])
    t0 = time.perf_counter()
    X_train = transform_chunked(ctx.model.vectorizer, train[TEXT_COL], ctx.chunk)
    vec_s = time.perf_counter() - t0
    out: dict[str, Any] = {"transform_seconds": vec_s, "tasks": {}}
    for power in ctx.cfg["class_weight_powers"]:
        for task in tasks:
            y = train[ctx.label_cols[task]].to_numpy()
            p = {**params, "class_weight": powered_class_weights(y, power)}
            clf = build_classifier(p, seed)
            t1 = time.perf_counter()
            conv = fit_with_convergence(clf, X_train, y)
            fit_s = time.perf_counter() - t1
            labels = [str(c) for c in clf.classes_]
            after = ctx.split_scores(task, labels, clf.predict_proba(ctx.X_val))
            before = ctx.split_scores(task, *ctx.prob[task])
            adopt = bool(after["val_a"]["macro_f1"] > before["val_a"]["macro_f1"])
            rid = ctx.log(f"class_weight_pow{power}", task,
                          {"class_weight_power": power, **conv, "fit_seconds": round(fit_s, 1)},
                          after["val_b"],
                          f"retrained on train with balanced**{power} weights,"
                          f" {conv}; baseline val-B macro-F1 {before['val_b']['macro_f1']:.4f};"
                          f" adopt={adopt}")
            out["tasks"][f"{task}/pow{power}"] = {
                "power": power, "before": before, "after": after, "adopt": adopt,
                "conv": conv, "fit_seconds": fit_s, "run_id": rid}
            logger.info("class_weight %s pow %s done in %.0fs", task, power, fit_s)
    return out


# --------------------------------------------------------------------------- report


def _results_dir() -> Path:
    return resolve(load_config("eval")["reports_dir"]) / "results"


def run(only: Sequence[str]) -> dict[str, Any]:
    """Run the named iterations; each result is saved to reports/m4/results/."""
    ctx = _Ctx()
    fns = {"prior": iter_prior, "class_weight": iter_class_weight,
           "consistency": iter_consistency}
    out = {}
    for name in only:
        res = fns[name](ctx)
        res["model_id"] = ctx.ecfg["primary_model_id"]
        res["n_val_a"], res["n_val_b"] = int(ctx.mask_a.sum()), int((~ctx.mask_a).sum())
        path = _results_dir() / f"iteration_{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res, indent=2, sort_keys=True, default=float))
        out[name] = res
    write_report()
    return out


def _f(v: float) -> str:
    return f"{v:.4f}"


def write_report() -> None:
    """Compose reports/m4/improvement_iterations.md from the saved iteration results."""
    cfg = load_config("eval")["iterations"]
    rd = _results_dir()
    res = {n: json.loads((rd / f"iteration_{n}.json").read_text())
           for n in ITERATIONS if (rd / f"iteration_{n}.json").exists()}
    any_res = next(iter(res.values()), {})
    out = [
        "# M4 improvement iterations (validation split)",
        "",
        "Generated by `python -m complaintiq.models.iterations` (`make iterations`). Each"
        " iteration = hypothesis, change, result, logged in"
        " `reports/experiments/m4/iterations.csv` (val_* columns there are val-B).",
        "",
        f"- Base: the primary model `{any_res.get('model_id', 'TODO')}`, argmax, no calibration.",
        f"- Every choice is made on **val-A** ({any_res.get('n_val_a', 'TODO')} rows);"
        f" **val-B** ({any_res.get('n_val_b', 'TODO')} rows) is held out. The test split was"
        " not read. Adopt = better val-A macro-F1 than the base.",
        "- Nothing here changes the primary model or the serving path; adopting an iteration"
        " is a team decision before the freeze (configs/final_model.yaml).",
        "- Each iteration is measured alone against the same base. **TODO:** their combination"
        " (e.g. class weights ** 0.5 + prior correction + issue restriction) was not run; the"
        " gains may overlap. Adopting any of them also requires re-running `make calibrate`"
        " (temperature and tau were fit on the base model's probabilities).",
        "",
    ]
    if "prior" in res:
        r = res["prior"]
        out += [
            "## Iteration 1: prior correction for the label shift",
            "",
            "**Hypothesis.** Balanced class weights make the model act as if classes were equally"
            " frequent, but val is dominated by credit reporting (product share 0.405 in train vs"
            " 0.605 in val; issue `Improper use of your report` 0.063 vs 0.177, M2 report"
            " section 3). Multiplying the probabilities by the class prior should recover"
            " accuracy and weighted-F1; the effect on macro-F1 is uncertain.",
            "",
            "**Change.** `p'(y|x) ~ p(y|x) * prior(y) ** lambda`; prior from train labels or"
            f" val-A labels; lambda in {cfg['prior_lambdas']}; best by val-A macro-F1.",
            "",
            "**Result.**",
            "",
            "| task | chosen (val-A) | val-B macro-F1 base -> chosen | val-B weighted-F1 base ->"
            " chosen | val-B accuracy base -> chosen | adopt | run_id |",
            "|---|---|---|---|---|---|---|",
        ]
        for task, t in r["tasks"].items():
            b, c = t["base"], t["best"]
            out.append(
                f"| {task} | {c['source']}, lambda={c['lambda']} | {_f(b['b_macro_f1'])} ->"
                f" {_f(c['b_macro_f1'])} | {_f(b['b_weighted_f1'])} -> {_f(c['b_weighted_f1'])}"
                f" | {_f(b['b_accuracy'])} -> {_f(c['b_accuracy'])} | {t['adopt']} |"
                f" `{t['run_id']}` |"
            )
        out += [
            "",
            "Deployment note: the `val_a` prior source uses labels from the val period. In"
            " production that means recent labelled complaints; the `train` source needs no"
            " recent labels. Compare both rows at the chosen lambda in the grid below before"
            " adopting. Neither is applied to the primary model or the API.",
            "",
            "Full grid (val-A chooses; val-B shown for transparency):",
            "",
        ]
        for task, t in r["tasks"].items():
            g = pl.DataFrame(t["grid"]).select("source", "lambda", "a_macro_f1", "b_macro_f1",
                                               "a_weighted_f1", "b_weighted_f1", "b_accuracy")
            out += [f"**{task}**", "", _md(g), ""]
    if "class_weight" in res:
        r = res["class_weight"]
        out += [
            "## Iteration 2: class-weight tuning",
            "",
            "**Hypothesis.** M3 showed balanced weights lift macro-F1 over no weights (product"
            " 0.771 vs 0.737, issue 0.487 vs 0.402 at alpha 1e-5, reports/m3/model_comparison.md)"
            " but may over-predict small classes. A softer weighting (balanced ** power) could"
            " keep the minority-class recall and recover precision.",
            "",
            f"**Change.** Retrain product and issue on all of train with the primary model's"
            f" saved vectorizer and classifier settings, class weights balanced ** power, power"
            f" in {cfg['class_weight_powers']}.",
            "",
            "**Result.**",
            "",
            "| task | power | val-B macro-F1 base -> new | val-B weighted-F1 base -> new |"
            " val-A macro-F1 base -> new | n_iter / converged | adopt | run_id |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for key, t in r["tasks"].items():
            b, a = t["before"], t["after"]
            out.append(
                f"| {key.split('/')[0]} | {t['power']} | {_f(b['val_b']['macro_f1'])} ->"
                f" {_f(a['val_b']['macro_f1'])} | {_f(b['val_b']['weighted_f1'])} ->"
                f" {_f(a['val_b']['weighted_f1'])} | {_f(b['val_a']['macro_f1'])} ->"
                f" {_f(a['val_a']['macro_f1'])} | {t['conv']['n_iter']} /"
                f" {t['conv']['converged']} | {t['adopt']} | `{t['run_id']}` |"
            )
        out.append("")
    else:
        out += ["## Iteration 2: class-weight tuning", "", "TODO: not run yet"
                " (`python -m complaintiq.models.iterations run --only class_weight`).", ""]
    if "consistency" in res:
        r = res["consistency"]
        b, a = r["before"], r["after"]
        out += [
            "## Iteration 3: issue restricted to the predicted product",
            "",
            f"**Hypothesis (measured).** Of {r['issue_errors']:,} issue errors on val,"
            f" {r['cross_product_share']:.4f} predict an issue never (or rarely) seen with the"
            " true product in train. The product model is much stronger than the issue model,"
            " so forcing issue to agree with the predicted product should remove some of them.",
            "",
            f"**Change.** Zero the probability of issues seen with the predicted product in fewer"
            f" than {cfg['issue_product_min_rows']} training rows, then renormalize"
            f" ({r['allowed_pairs']} of {r['n_pairs']} product-issue pairs allowed).",
            "",
            "**Result.**",
            "",
            "| split | macro-F1 base -> new | weighted-F1 base -> new | top-3 base -> new |",
            "|---|---|---|---|",
        ]
        for s in ("val_a", "val_b"):
            out.append(f"| {s.replace('_', '-')} | {_f(b[s]['macro_f1'])} -> {_f(a[s]['macro_f1'])}"
                       f" | {_f(b[s]['weighted_f1'])} -> {_f(a[s]['weighted_f1'])} |"
                       f" {_f(b[s]['top3'])} -> {_f(a[s]['top3'])} |")
        out += ["", f"Adopt: {r['adopt']} (run_id `{r['run_id']}`).", ""]
    path = resolve(cfg["report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n")


def _md(df: pl.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in r) + " |"
            for r in df.iter_rows()]
    return "\n".join([head, sep, *body])


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m complaintiq.models.iterations")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only", default="prior,consistency", help=f"comma list of {ITERATIONS}")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    if args.cmd == "report":
        write_report()
        return
    names = args.only.split(",")
    unknown = set(names) - set(ITERATIONS)
    if unknown:
        raise SystemExit(f"unknown iterations {sorted(unknown)}")
    res = run(names)
    print(json.dumps({n: "done" for n in res}))


if __name__ == "__main__":
    main()
