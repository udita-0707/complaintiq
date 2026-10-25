"""M2 data pipeline entry point.

    python -m complaintiq.data.pipeline propose-mappings   # make data-mappings
    python -m complaintiq.data.pipeline build              # make data

``propose-mappings`` regenerates the issue mapping and writes a review report; ``build``
applies the reviewed mappings and writes the processed splits and the stats report.
Only aggregates are ever printed or written to reports.
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

import polars as pl

from complaintiq.config import load_config
from complaintiq.data import stats, taxonomy
from complaintiq.data.clean import CleanResult, clean
from complaintiq.data.load import resolve, scan_raw
from complaintiq.data.priority import derive_priority, severity_issues
from complaintiq.data.split import compute_cutoffs, time_split_expr


def run_clean(cfg: dict[str, Any]) -> tuple[CleanResult, dict[str, date]]:
    """Load and clean, then attach the time split; returns the result and the cutoffs."""
    res = clean(scan_raw(cfg), cfg, taxonomy.product_excluded(cfg))
    s = cfg["split"]
    cutoffs = compute_cutoffs(res.df["date_received"], s["train_frac"], s["val_frac"])
    res.df = res.df.with_columns(time_split_expr(cutoffs))
    return res, cutoffs


def md_table(df: pl.DataFrame) -> str:
    """Render a small aggregate DataFrame as a Markdown table."""
    cols = df.columns
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.iter_rows():
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def fmt(v: object) -> str:
    """Format one table cell."""
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v).replace("|", "/")


def coverage(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """First/last date and per-split row counts for each value of ``col``."""
    return (
        df.group_by(col)
        .agg(
            rows=pl.len(),
            first=pl.col("date_received").min(),
            last=pl.col("date_received").max(),
            train=(pl.col("split") == "train").sum(),
            val=(pl.col("split") == "val").sum(),
            test=(pl.col("split") == "test").sum(),
        )
        .sort(["rows", col], descending=[True, False])
    )


def topn_coverage(df: pl.DataFrame, merges: dict[str, str], ns: list[int]) -> pl.DataFrame:
    """Share of rows (overall and per split) covered by the top-N harmonized issues."""
    h = df.select("split", harmonized=taxonomy.harmonized_issue_expr(merges))
    order = (
        h.group_by("harmonized")
        .agg(n=pl.len(), n_train=(pl.col("split") == "train").sum())
        .filter(pl.col("n_train") > 0)
        .sort(["n", "harmonized"], descending=[True, False])["harmonized"]
        .to_list()
    )
    rows = []
    for n in ns:
        keep = h.with_columns(kept=pl.col("harmonized").is_in(order[:n]))
        row: dict[str, Any] = {"top_n": n, "overall": keep["kept"].mean()}
        for s in ("train", "val", "test"):
            row[s] = keep.filter(pl.col("split") == s)["kept"].mean()
        rows.append(row)
    return pl.DataFrame(rows)


def propose_mappings(cfg: dict[str, Any]) -> None:
    """Regenerate issue_mapping.yaml and write reports/m2_mapping_review.md."""
    res, cutoffs = run_clean(cfg)
    df = res.df
    tax = cfg["taxonomy"]
    other, top_n = tax["other_label"], int(tax["issue_top_n"])
    merges = taxonomy.issue_merges(cfg)
    pmap = taxonomy.product_map(cfg)
    unmapped = sorted(set(df["product"].unique().to_list()) - set(pmap))
    if unmapped:
        raise ValueError(f"unmapped Product values: {unmapped}")

    force = taxonomy.issue_force_keep(cfg)
    imap, no_train = taxonomy.propose_issue_mapping(df, merges, top_n, other, force)
    n_forced = len(set(imap.values()) - {other}) - top_n
    taxonomy.write_issue_mapping(cfg, imap, top_n, n_forced)

    mapped = df.with_columns(
        product_class=pl.col("product").replace_strict(pmap, return_dtype=pl.String),
        issue_class=pl.col("issue").replace_strict(imap, return_dtype=pl.String),
    )
    severity = severity_issues(cfg)
    pri = derive_priority(mapped.lazy(), cfg, severity).collect()

    out: list[str] = ["# M2 mapping review (checkpoint, step 3)", ""]
    out += [
        "Aggregates only. Rows = cleaned narrative rows (after min_words and dedup): "
        f"{df.height:,}. Time-split cutoffs: train <= {cutoffs['train_end']}, "
        f"val <= {cutoffs['val_end']}, test after.",
        "",
        "## 1. Product classes: date coverage and split counts",
        "",
        md_table(coverage(mapped, "product_class")),
        "",
        "### Raw Product values and their class",
        "",
        md_table(
            coverage(mapped, "product").with_columns(
                product_class=pl.col("product").replace_strict(pmap, return_dtype=pl.String)
            )
        ),
        "",
        "## 2. Issue top-N coverage",
        "",
        md_table(topn_coverage(df, merges, [10, 15, 20, 25, 30, 40])),
        "",
        f"## 3. Issue classes (top_n = {top_n}): date coverage and split counts",
        "",
        md_table(coverage(mapped, "issue_class")),
        "",
        "### Harmonized issues with zero training rows (forced to OTHER)",
        "",
        "\n".join(f"- {x}" for x in no_train) or "- none",
        "",
        "### Merged raw issues (old/new names)",
        "",
        md_table(
            coverage(df.filter(pl.col("issue").is_in(list(merges))), "issue")
            .with_columns(harmonized=pl.col("issue").replace(merges))
            .select("issue", "harmonized", "rows", "first", "last")
        ),
        "",
        "## 4. Severity list: rows per entry and resulting HIGH rate",
        "",
        md_table(
            pl.DataFrame({"issue": severity})
            .join(
                df.group_by("issue").agg(
                    rows=pl.len(),
                    train=(pl.col("split") == "train").sum(),
                    val=(pl.col("split") == "val").sum(),
                    test=(pl.col("split") == "test").sum(),
                ),
                on="issue",
                how="left",
            )
            .fill_null(0)
        ),
        "",
        md_table(stats.priority_rates(pri, "split")),
        "",
    ]
    path = resolve("reports/m2_mapping_review.md")
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {path} and {tax['issue_mapping_path']}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["propose-mappings", "build"])
    args = parser.parse_args()
    cfg = load_config("data")
    if args.stage == "propose-mappings":
        propose_mappings(cfg)
    else:
        from complaintiq.data.build import build

        build(cfg)


if __name__ == "__main__":
    main()
