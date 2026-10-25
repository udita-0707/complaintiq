"""Text normalization, length filter and deduplication (SPEC C4 cleaning steps 1, 2, 6).

Order: drop excluded products -> unicode NFKC -> collapse XXXX placeholder runs ->
collapse whitespace -> drop < ``min_words`` -> drop duplicate complaint IDs -> drop
duplicate normalized narratives (keep the earliest by date received). Only aggregates are returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import polars as pl

# A CFPB redaction token: a standalone XX/xxxx word, or an uppercase X{4,} run that may be
# glued to other characters (e.g. "XXXX1234"). A run of tokens separated only by
# whitespace or date/number punctuation collapses to one placeholder.
_TOKEN = r"(?:X{4,}|(?i:\bx{2,}\b))"
PLACEHOLDER_RUN = rf"{_TOKEN}(?:[\s/\-.,]*{_TOKEN})*"


def normalize_expr(col: str = "narrative", token: str = "[REDACTED]") -> pl.Expr:
    """Return an expression that normalizes unicode, placeholders and whitespace."""
    return (
        pl.col(col)
        .str.normalize("NFKC")
        .str.replace_all(PLACEHOLDER_RUN, token, literal=False)
        # Keep a placeholder that was glued to a word as its own token.
        .str.replace_all(rf"({re.escape(token)})(\w)", "$1 $2")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
    )


def word_count_expr(col: str = "narrative") -> pl.Expr:
    """Whitespace token count of an already-normalized column."""
    return pl.col(col).str.split(" ").list.len().cast(pl.Int32)


def text_hash_expr(col: str = "narrative") -> pl.Expr:
    """64-bit hash of the lowercased normalized text, used for duplicate checks.

    Stable within one polars version (``seed=0``); recomputed on every pipeline run.
    """
    return pl.col(col).str.to_lowercase().hash(seed=0)


@dataclass
class CleanResult:
    """Cleaned rows plus aggregate side tables for the report."""

    df: pl.DataFrame
    counts: dict[str, int]
    # Per raw product: rows before the min_words filter and rows dropped by it.
    short_by_product: pl.DataFrame
    # One row per duplicate-text group: size and the distinct raw labels in it.
    dup_groups: pl.DataFrame
    notes: list[str] = field(default_factory=list)


def clean(
    lf: pl.LazyFrame, cfg: dict[str, Any], exclude_products: list[str] | None = None
) -> CleanResult:
    """Apply the cleaning steps to the output of ``load.scan_raw``."""
    token = cfg["clean"]["placeholder_token"]
    min_words = int(cfg["min_words"])

    df = (
        lf.with_columns(normalize_expr("narrative", token))
        .with_columns(n_words=word_count_expr("narrative"))
        .collect(engine="streaming")
    )
    counts = {"narrative_rows": df.height}
    df = df.filter(~pl.col("product").is_in(exclude_products or []))
    counts["after_exclude_products"] = df.height

    short_by_product = (
        df.group_by("product")
        .agg(n_rows=pl.len(), n_dropped=(pl.col("n_words") < min_words).sum())
        .sort("product")
    )
    df = df.filter(pl.col("n_words") >= min_words)
    counts["after_min_words"] = df.height

    df = df.sort(["date_received", "complaint_id"]).unique(
        subset="complaint_id", keep="first", maintain_order=True
    )
    counts["after_dedup_id"] = df.height

    df = df.with_columns(text_hash=text_hash_expr("narrative"))
    dup_groups = (
        df.group_by("text_hash")
        .agg(
            n=pl.len(),
            products=pl.col("product").unique(),
            issues=pl.col("issue").unique(),
        )
        .filter(pl.col("n") > 1)
    )
    df = df.unique(subset="text_hash", keep="first", maintain_order=True)
    counts["after_dedup_text"] = df.height
    counts["duplicate_text_groups"] = dup_groups.height
    return CleanResult(
        df=df, counts=counts, short_by_product=short_by_product, dup_groups=dup_groups
    )
