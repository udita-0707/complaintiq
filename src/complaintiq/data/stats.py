"""Aggregate statistics for reports/m2_data_stats.md (SPEC C4 statistical analysis).

Every function returns a small aggregate DataFrame; no row-level text is ever emitted.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from complaintiq.data.split import SPLITS


def distribution(df: pl.DataFrame, label: str) -> pl.DataFrame:
    """Row count and share of each ``label`` value per split (wide: one column pair per split)."""
    long = (
        df.group_by("split", label)
        .agg(n=pl.len())
        .with_columns(share=pl.col("n") / pl.col("n").sum().over("split"))
    )
    out = long.select(label).unique()
    for s in SPLITS:
        part = long.filter(pl.col("split") == s).select(
            label, pl.col("n").alias(f"{s}_n"), pl.col("share").alias(f"{s}_share")
        )
        out = out.join(part, on=label, how="left")
    return out.fill_null(0).sort(f"{SPLITS[0]}_n", descending=True)


def imbalance(df: pl.DataFrame, label: str, other: str | None = None) -> pl.DataFrame:
    """Max/min class-size ratio per split, optionally excluding the OTHER class."""
    d = df if other is None else df.filter(pl.col(label) != other)
    return (
        d.group_by("split", label)
        .agg(n=pl.len())
        .group_by("split")
        .agg(
            classes=pl.len(),
            largest=pl.col("n").max(),
            smallest=pl.col("n").min(),
            ratio=pl.col("n").max() / pl.col("n").min(),
        )
        .sort("split")
    )


def length_stats(df: pl.DataFrame, by: str | None) -> pl.DataFrame:
    """Word-count summary, overall or grouped by ``by``."""
    w = pl.col("n_words")
    aggs = [
        pl.len().alias("rows"),
        w.mean().alias("mean"),
        w.quantile(0.10).alias("p10"),
        w.median().alias("p50"),
        w.quantile(0.90).alias("p90"),
        w.quantile(0.99).alias("p99"),
        w.max().alias("max"),
    ]
    if by is None:
        return df.select(*aggs)
    return df.group_by(by).agg(*aggs).sort("rows", descending=True)


def min_words_effect(short_by_product: pl.DataFrame, pmap: dict[str, str]) -> pl.DataFrame:
    """Rows removed by the min_words cutoff per product class (before dedup)."""
    return (
        short_by_product.with_columns(
            product_class=pl.col("product").replace_strict(pmap, return_dtype=pl.String)
        )
        .group_by("product_class")
        .agg(pl.col("n_rows").sum(), pl.col("n_dropped").sum())
        .with_columns(share_dropped=pl.col("n_dropped") / pl.col("n_rows"))
        .sort("n_rows", descending=True)
    )


def duplicate_conflicts(
    dup_groups: pl.DataFrame, pmap: dict[str, str], imap: dict[str, str]
) -> pl.DataFrame:
    """Duplicate-text groups whose members carry conflicting labels (label-noise estimate)."""
    g = dup_groups.with_columns(
        product_classes=pl.col("products")
        .list.eval(pl.element().replace_strict(pmap, return_dtype=pl.String))
        .list.unique(),
        issue_classes=pl.col("issues")
        .list.eval(pl.element().replace_strict(imap, return_dtype=pl.String))
        .list.unique(),
    )
    total = g.height

    def row(name: str, col: str) -> dict[str, Any]:
        k = int((g[col].list.len() > 1).sum())
        rows = int(g.filter(pl.col(col).list.len() > 1)["n"].sum())
        return {
            "label": name,
            "conflicting_groups": k,
            "share_of_groups": k / max(total, 1),
            "rows_in_conflicting_groups": rows,
        }

    return pl.DataFrame(
        [
            row("raw Product", "products"),
            row("raw Issue", "issues"),
            row("product_class", "product_classes"),
            row("issue_class", "issue_classes"),
        ]
    )


def by_year_share(df: pl.DataFrame, label: str) -> pl.DataFrame:
    """Share of each ``label`` value per year (rows = label values, columns = years)."""
    d = (
        df.with_columns(year=pl.col("date_received").dt.year().cast(pl.String))
        .group_by("year", label)
        .agg(n=pl.len())
        .with_columns(share=pl.col("n") / pl.col("n").sum().over("year"))
    )
    wide = d.pivot(on="year", index=label, values="share", sort_columns=True).fill_null(0.0)
    return wide.sort(label)


def priority_rates(pri: pl.DataFrame, by: str) -> pl.DataFrame:
    """HIGH rate and per-rule rates grouped by ``by``, plus an overall row."""
    aggs = [
        pl.len().alias("rows"),
        (pl.col("priority") == "HIGH").mean().alias("high_rate"),
        pl.col("rule_severity").mean().alias("severity_rule"),
        pl.col("rule_monetary").mean().alias("monetary_rule"),
        pl.col("rule_untimely").mean().alias("untimely_rule"),
    ]
    grouped = pri.group_by(by).agg(*aggs).with_columns(pl.col(by).cast(pl.String)).sort(by)
    overall = pri.select(pl.lit("all").alias(by), *aggs)
    return pl.concat([grouped, overall])


def slice_exprs(df: pl.DataFrame, cfg: dict[str, Any]) -> dict[str, pl.Expr]:
    """Suggested slice columns: year, length bucket, company size (top-N by train rows)."""
    sc = cfg["slices"]
    edges = list(sc["length_bucket_edges"])
    labels = [f"<{edges[0]}"] + [f"{a}-{b - 1}" for a, b in zip(edges[:-1], edges[1:], strict=True)]
    labels.append(f">={edges[-1]}")
    top = (
        df.filter(pl.col("split") == "train")
        .group_by("company")
        .agg(n=pl.len())
        .sort(["n", "company"], descending=[True, False])
        .head(int(sc["top_companies"]))["company"]
    )
    return {
        "year": pl.col("date_received").dt.year().cast(pl.String),
        "length_bucket": pl.col("n_words")
        .cut(edges, labels=labels, left_closed=True)
        .cast(pl.String),
        "company_size": pl.when(pl.col("company").is_in(top.implode()))
        .then(pl.lit(f"top {sc['top_companies']} companies"))
        .otherwise(pl.lit("other companies")),
    }


def slice_counts(df: pl.DataFrame, slice_col: str) -> pl.DataFrame:
    """Rows per slice value per split, plus HIGH rate."""
    out = (
        df.group_by(slice_col)
        .agg(
            *[(pl.col("split") == s).sum().alias(s) for s in SPLITS],
            high_rate=(pl.col("priority") == "HIGH").mean(),
        )
        .sort(slice_col)
    )
    return out


def priority_components(pri: pl.DataFrame, by: str = "split") -> pl.DataFrame:
    """Share of rows per mutually exclusive rule combination: severity-only,
    monetary-only, untimely-only, two or more rules (overlap), and HIGH total."""
    n_rules = (
        pl.col("rule_severity").cast(pl.Int8)
        + pl.col("rule_monetary").cast(pl.Int8)
        + pl.col("rule_untimely").cast(pl.Int8)
    )
    aggs = [
        pl.len().alias("rows"),
        ((n_rules == 1) & pl.col("rule_severity")).mean().alias("severity_only"),
        ((n_rules == 1) & pl.col("rule_monetary")).mean().alias("monetary_only"),
        ((n_rules == 1) & pl.col("rule_untimely")).mean().alias("untimely_only"),
        (n_rules >= 2).mean().alias("overlap_2plus"),
        (pl.col("priority") == "HIGH").mean().alias("high_rate"),
    ]
    grouped = pri.group_by(by).agg(*aggs).with_columns(pl.col(by).cast(pl.String)).sort(by)
    return pl.concat([grouped, pri.select(pl.lit("all").alias(by), *aggs)])


def dup_size_buckets(
    dup_groups: pl.DataFrame, pmap: dict[str, str], imap: dict[str, str]
) -> pl.DataFrame:
    """Duplicate groups by size bucket (2, 3-5, 6-20, >20) with class-level conflicts."""
    g = dup_groups.with_columns(
        p=pl.col("products")
        .list.eval(pl.element().replace_strict(pmap, return_dtype=pl.String))
        .list.n_unique(),
        i=pl.col("issues")
        .list.eval(pl.element().replace_strict(imap, return_dtype=pl.String))
        .list.n_unique(),
        bucket=pl.when(pl.col("n") == 2)
        .then(pl.lit("2"))
        .when(pl.col("n") <= 5)
        .then(pl.lit("3-5"))
        .when(pl.col("n") <= 20)
        .then(pl.lit("6-20"))
        .otherwise(pl.lit(">20")),
    )
    order = {"2": 0, "3-5": 1, "6-20": 2, ">20": 3}
    aggs = [
        pl.len().alias("groups"),
        pl.col("n").sum().alias("rows"),
        (pl.col("p") > 1).sum().alias("conflicting_product"),
        (pl.col("i") > 1).sum().alias("conflicting_issue"),
        ((pl.col("p") > 1) | (pl.col("i") > 1)).sum().alias("conflicting_product_or_issue"),
    ]
    out = (
        g.group_by("bucket")
        .agg(*aggs)
        .sort(pl.col("bucket").replace_strict(order, return_dtype=pl.Int8))
    )
    return pl.concat([out, g.select(pl.lit("all").alias("bucket"), *aggs)])


def class_sources(df: pl.DataFrame, label: str, value: str, raw: str) -> pl.DataFrame:
    """Rows of one harmonized class broken down by the raw value they came from."""
    return (
        df.filter(pl.col(label) == value)
        .group_by(raw)
        .agg(
            pl.col("date_received").min().alias("first"),
            pl.col("date_received").max().alias("last"),
            *[(pl.col("split") == s).sum().alias(s) for s in SPLITS],
        )
        .sort("train", descending=True)
    )


def class_share_by_split(df: pl.DataFrame, label: str, value: str) -> dict[str, float]:
    """Share of rows in each split that carry ``label == value``."""
    return {
        s: float((df.filter(pl.col("split") == s)[label] == value).mean() or 0.0) for s in SPLITS
    }
