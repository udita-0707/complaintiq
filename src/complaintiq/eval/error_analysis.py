"""Error analysis on val for the primary model (SPEC C6, M4).

Two steps:

1. ``auto``: predicts product and issue on val, writes the automatic statistics
   (top confusion pairs, per-class F1 with support, error rate by length bucket and year)
   to ``reports/m4/error_analysis.md`` and samples errors per task (seeded, stratified
   over the true class) to ``reports/m4/error_sample_LOCAL.csv``. That CSV contains
   narratives for the human labellers and is gitignored; it is never printed.
2. ``summarize``: reads the filled ``error_category`` column and writes counts and shares
   per category into the human section of the report.

The test split is never read. Nothing here prints or logs complaint text.

CLI::

    python -m complaintiq.eval.error_analysis auto [--overwrite-sample]
    python -m complaintiq.eval.error_analysis summarize
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from complaintiq.config import load_config
from complaintiq.data.load import resolve

logger = logging.getLogger("complaintiq.eval.error_analysis")

SAMPLE_COLUMNS = (
    "task", "complaint_id", "true", "predicted", "margin", "n_words", "narrative",
    "error_category",
)
HUMAN_START = "<!-- human-categories:start -->"
HUMAN_END = "<!-- human-categories:end -->"


# --------------------------------------------------------------------------- pure helpers


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    """Split ``n`` samples over classes in proportion to ``counts`` (largest remainder).

    Every class with rows gets at least one sample when ``n`` allows it; no class gets
    more than it has. Deterministic (ties broken by class name).
    """
    counts = {k: int(v) for k, v in counts.items() if v > 0}
    total = sum(counts.values())
    if n >= total:
        return dict(counts)
    keys = sorted(counts)
    quota = {k: 0 for k in keys}
    if n >= len(keys):
        quota = {k: 1 for k in keys}
    rest = n - sum(quota.values())
    room = {k: counts[k] - quota[k] for k in keys}
    room_total = sum(room.values())
    if rest > 0 and room_total > 0:
        exact = {k: rest * room[k] / room_total for k in keys}
        add = {k: min(int(np.floor(exact[k])), room[k]) for k in keys}
        left = rest - sum(add.values())
        order = sorted(keys, key=lambda k: (-(exact[k] - np.floor(exact[k])), k))
        while left > 0:
            moved = False
            for k in order:
                if left and add[k] < room[k]:
                    add[k] += 1
                    left -= 1
                    moved = True
            if not moved:
                break
        quota = {k: quota[k] + add[k] for k in keys}
    elif n < len(keys):  # fewer samples than classes: the largest classes first
        for k in sorted(keys, key=lambda k: (-counts[k], k))[:n]:
            quota[k] = 1
    return {k: v for k, v in quota.items() if v > 0}


def sample_errors(errors: pl.DataFrame, n: int, seed: int, class_col: str = "true") -> pl.DataFrame:
    """Seeded sample of ``n`` error rows, stratified over ``class_col`` (see :func:`allocate`)."""
    counts = dict(errors.group_by(class_col).len().iter_rows())
    quota = allocate(counts, n)
    q = pl.DataFrame({class_col: list(quota), "_q": list(quota.values())})
    return (
        errors.sample(fraction=1.0, shuffle=True, seed=seed)
        .join(q, on=class_col, how="inner")
        .with_columns(_r=pl.int_range(pl.len()).over(class_col))
        .filter(pl.col("_r") < pl.col("_q"))
        .drop("_r", "_q")
        .sort([class_col, "complaint_id"])
    )


def margins(prob: np.ndarray, pred_idx: np.ndarray, true_idx: np.ndarray) -> np.ndarray:
    """p(predicted) - p(true) per row (0 for correct rows)."""
    rows = np.arange(len(pred_idx))
    return prob[rows, pred_idx] - prob[rows, true_idx]


def top_confusions(y_true: Sequence[str], y_pred: Sequence[str], k: int = 20) -> pl.DataFrame:
    """The ``k`` most frequent (true, predicted) error pairs with their share of the true class
    and of all errors."""
    df = pl.DataFrame({"true": list(y_true), "predicted": list(y_pred)})
    support = df.group_by("true").len().rename({"len": "true_support"})
    err = df.filter(pl.col("true") != pl.col("predicted"))
    n_err = max(err.height, 1)
    return (
        err.group_by(["true", "predicted"]).len().rename({"len": "n"})
        .join(support, on="true")
        .with_columns(
            share_of_true=pl.col("n") / pl.col("true_support"),
            share_of_errors=pl.col("n") / n_err,
        )
        .sort(["n", "true", "predicted"], descending=[True, False, False])
        .head(k)
        .drop("true_support")
    )


def error_rate_by(frame: pl.DataFrame, by: str) -> pl.DataFrame:
    """``n``, ``errors`` and ``error_rate`` per value of ``by`` (``frame`` has ``is_error``)."""
    return (
        frame.group_by(by)
        .agg(n=pl.len(), errors=pl.col("is_error").sum())
        .with_columns(error_rate=pl.col("errors") / pl.col("n"))
        .sort(by)
    )


def length_bucket(n_words: pl.Expr, edges: Sequence[int]) -> pl.Expr:
    """Word-count bucket labels matching the M2/M3 reports (``<100``, ``100-199`` ...)."""
    expr = pl.when(n_words < edges[0]).then(pl.lit(f"<{edges[0]}"))
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        expr = expr.when(n_words < hi).then(pl.lit(f"{lo}-{hi - 1}"))
    return expr.otherwise(pl.lit(f">={edges[-1]}"))


def summarize_categories(sample: pl.DataFrame, categories: Sequence[str]) -> pl.DataFrame:
    """Counts and shares of ``error_category`` per task over the labelled rows.

    Raises ``ValueError`` on a category outside ``categories``. Unlabelled rows (empty
    category) are counted in a separate ``(unlabelled)`` row and excluded from shares.
    """
    s = sample.with_columns(
        error_category=pl.col("error_category").cast(pl.Utf8).fill_null("").str.strip_chars()
        .str.to_lowercase()
    )
    allowed = {c.lower() for c in categories}
    bad = set(s.filter(pl.col("error_category") != "")["error_category"].unique()) - allowed
    if bad:
        raise ValueError(f"unknown error categories: {sorted(bad)}; allowed: {sorted(allowed)}")
    rows = []
    for task in sorted(s["task"].unique()):
        t = s.filter(pl.col("task") == task)
        labelled = t.filter(pl.col("error_category") != "")
        n_lab = labelled.height
        for c in categories:
            n = int((labelled["error_category"] == c.lower()).sum())
            rows.append({"task": task, "category": c, "n": n,
                         "share": n / n_lab if n_lab else float("nan")})
        rows.append({"task": task, "category": "(unlabelled)", "n": t.height - n_lab,
                     "share": float("nan")})
    return pl.DataFrame(rows)


def replace_section(text: str, body: str) -> str:
    """Replace the text between the human-section markers (markers kept)."""
    start, end = text.index(HUMAN_START), text.index(HUMAN_END)
    return text[: start + len(HUMAN_START)] + "\n" + body.strip() + "\n" + text[end:]


def md_table(df: pl.DataFrame, digits: int = 3) -> str:
    """Render a DataFrame as a Markdown table."""
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


# --------------------------------------------------------------------------- runs


def _human_section(cfg: dict[str, Any], sample_path: Path) -> str:
    cats = cfg["categories"]
    if not sample_path.exists():
        return ("**TODO (human labelling):** the error sample has not been generated on this"
                " machine. Run `make error-sample`.")
    sample = pl.read_csv(sample_path, schema_overrides={"error_category": pl.Utf8,
                                                       "complaint_id": pl.Utf8})
    summary = summarize_categories(sample, cats)
    labelled = int(summary.filter(pl.col("category") != "(unlabelled)")["n"].sum())
    if labelled == 0:
        return (
            "**TODO (human labelling):** fill the `error_category` column of"
            f" `{cfg['local_path']}` (gitignored; contains narratives) with one of: "
            + ", ".join(f"`{c}`" for c in cats)
            + f". Then run `make error-summary`. {sample.height} rows are waiting"
            " (per task: "
            + ", ".join(
                f"{t} {n}" for t, n in sample.group_by("task").len().sort("task").iter_rows()
            )
            + ")."
        )
    return (
        f"Labelled rows: {labelled} of {sample.height}. Shares are over labelled rows per task.\n\n"
        + md_table(summary)
    )


def auto(overwrite_sample: bool = False) -> dict[str, Any]:
    """Compute the automatic statistics, write the report and the LOCAL error sample."""
    from complaintiq.data.training_data import LABEL_COLS, load_split
    from complaintiq.eval.metrics import compute_metrics
    from complaintiq.models.baseline import (
        TEXT_COL,
        BaselineModel,
        load_baseline_config,
        transform_chunked,
    )

    ecfg = load_config("eval")
    cfg = ecfg["error_analysis"]
    seed = int(ecfg["seed"])
    edges = load_config("data")["slices"]["length_bucket_edges"]
    model = BaselineModel.load(resolve(ecfg["primary_model_dir"]))
    val = load_split(
        "val",
        columns=["complaint_id", TEXT_COL, "date_received", "n_words",
                 *(LABEL_COLS[t] for t in cfg["tasks"])],
    ).with_columns(
        year=pl.col("date_received").dt.year().cast(pl.Utf8),
        length_bucket=length_bucket(pl.col("n_words"), edges),
        complaint_id=pl.col("complaint_id").cast(pl.Utf8),
    )
    X = transform_chunked(model.vectorizer, val[TEXT_COL],
                          load_baseline_config()["features"]["transform_chunk_rows"])
    sample_path = resolve(cfg["local_path"])
    write_sample = overwrite_sample or not sample_path.exists()
    samples = []
    sections: list[str] = []
    out: dict[str, Any] = {"n_val": val.height}
    for task in cfg["tasks"]:
        labels, prob = model.scores(task, X)
        prob = prob / prob.sum(axis=1, keepdims=True)
        y = val[LABEL_COLS[task]].to_numpy()
        index = {lbl: i for i, lbl in enumerate(labels)}
        true_idx = np.array([index[v] for v in y])
        pred_idx = prob.argmax(axis=1)
        pred = np.asarray(labels)[pred_idx]
        m = compute_metrics(y, pred, labels)
        frame = val.select("complaint_id", "year", "length_bucket", "n_words").with_columns(
            true=pl.Series(y), predicted=pl.Series(pred),
            margin=pl.Series(margins(prob, pred_idx, true_idx)),
            is_error=pl.Series(y != pred),
        )
        n_err = int(frame["is_error"].sum())
        pcf = (m["per_class"].filter(pl.col("support") > 0)
               .select("label", "support", "precision", "recall", "f1").sort("f1"))
        conf = top_confusions(y, pred, cfg["top_confusions"])
        out[task] = {"errors": n_err, "error_rate": n_err / val.height,
                     "macro_f1": m["macro_f1"], "top_confusions": conf.to_dicts()}
        sections += [
            f"## {LABEL_COLS[task]}",
            "",
            f"Errors: **{n_err:,}** of {val.height:,} val rows (error rate"
            f" {n_err / val.height:.4f}); macro-F1 {m['macro_f1']:.4f} (fixed val label set).",
            "",
            f"### Top {cfg['top_confusions']} confusion pairs",
            "",
            md_table(conf, 4),
            "",
            "### Per-class F1 with support (sorted by F1, weakest first)",
            "",
            md_table(pcf),
            "",
            "### Error rate by narrative length bucket (words)",
            "",
            md_table(error_rate_by(frame, "length_bucket"), 4),
            "",
            "### Error rate by year",
            "",
            md_table(error_rate_by(frame, "year"), 4),
            "",
        ]
        if write_sample:
            errs = frame.filter(pl.col("is_error")).join(
                val.select("complaint_id", TEXT_COL), on="complaint_id", how="left"
            )
            s = sample_errors(errs, cfg["n_sample"], seed).with_columns(
                task=pl.lit(task), error_category=pl.lit("")
            )
            samples.append(s.select(list(SAMPLE_COLUMNS)))
    if write_sample:
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        pl.concat(samples).write_csv(sample_path)
        logger.info("wrote %d sampled errors to %s", sum(s.height for s in samples), sample_path)
    else:
        logger.info("kept existing error sample %s (use --overwrite-sample)", sample_path)

    report = [
        "# M4 error analysis (validation split)",
        "",
        "Generated by `python -m complaintiq.eval.error_analysis auto` (`make error-sample`)"
        " and `summarize` (`make error-summary`). All numbers are on the **val** split"
        f" ({val.height:,} rows); the test split was not read. Predictions are the argmax of"
        f" the primary model `{ecfg['primary_model_id']}` (model_version"
        f" `{model.meta['model_version']}`, data_version `{model.meta['data_version']}`)."
        " Aggregates and labels only; no complaint text.",
        "",
        "## Human error categories",
        "",
        f"Sample: {cfg['n_sample']} val errors per task ({', '.join(cfg['tasks'])}), seeded"
        f" (seed {seed}) and stratified over the true class in proportion to its error count"
        " (at least one per class). `margin` = p(predicted) - p(true) from the model's"
        " uncalibrated probabilities. Categories (SPEC C6): "
        + ", ".join(f"`{c}`" for c in cfg["categories"]) + ".",
        "",
        HUMAN_START,
        _human_section(cfg, sample_path),
        HUMAN_END,
        "",
        "## Automatic statistics (no human step)",
        "",
        *sections,
    ]
    path = resolve(cfg["report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(report).rstrip() + "\n")
    return out


def summarize() -> None:
    """Rewrite the human-category section of the report from the filled LOCAL sample."""
    cfg = load_config("eval")["error_analysis"]
    path = resolve(cfg["report_path"])
    text = path.read_text()
    path.write_text(replace_section(text, _human_section(cfg, resolve(cfg["local_path"]))))


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m complaintiq.eval.error_analysis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auto", help="automatic statistics + LOCAL error sample")
    a.add_argument("--overwrite-sample", action="store_true",
                   help="resample even if the LOCAL CSV exists (discards labels)")
    sub.add_parser("summarize", help="write category counts from the filled LOCAL CSV")
    args = ap.parse_args(argv)
    if args.cmd == "auto":
        res = auto(args.overwrite_sample)
        print({t: {"errors": r["errors"], "macro_f1": round(r["macro_f1"], 4)}
               for t, r in res.items() if isinstance(r, dict)})
    else:
        summarize()
        print(f"updated {cfg_path()}")


def cfg_path() -> str:
    """Report path from config (for messages)."""
    return load_config("eval")["error_analysis"]["report_path"]


if __name__ == "__main__":
    main()
