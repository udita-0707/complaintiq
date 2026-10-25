"""Leak-free splits (SPEC C4): primary time split plus a stratified random comparison."""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

SPLITS = ("train", "val", "test")


def compute_cutoffs(dates: pl.Series, train_frac: float, val_frac: float) -> dict[str, date]:
    """Return the last date of train and of val so that ~``train_frac`` / ``val_frac``
    of rows fall in each. All rows of one date stay in the same split."""
    daily = (
        dates.value_counts(name="n")
        .sort(dates.name)
        .with_columns(share=pl.col("n").cum_sum() / pl.col("n").sum())
    )
    train_end = daily.filter(pl.col("share") >= train_frac)[dates.name][0]
    val_end = daily.filter(pl.col("share") >= train_frac + val_frac)[dates.name][0]
    return {"train_end": train_end, "val_end": val_end}


def time_split_expr(cutoffs: dict[str, date], col: str = "date_received") -> pl.Expr:
    """Expression assigning ``train``/``val``/``test`` from the date cutoffs."""
    return (
        pl.when(pl.col(col) <= cutoffs["train_end"])
        .then(pl.lit("train"))
        .when(pl.col(col) <= cutoffs["val_end"])
        .then(pl.lit("val"))
        .otherwise(pl.lit("test"))
        .alias("split")
    )


def random_split_expr(cfg: dict[str, Any], seed: int) -> pl.Expr:
    """Stratified random split: within each stratum, rank rows by a seeded hash of the
    complaint ID and cut at the configured fractions. Deterministic and order-free."""
    split_cfg = cfg["split"]
    strat = split_cfg["random_stratify_on"]
    rank = pl.col("complaint_id").hash(seed=seed).rank("ordinal").over(strat)
    share = (rank - 1) / pl.len().over(strat)
    return (
        pl.when(share < split_cfg["train_frac"])
        .then(pl.lit("train"))
        .when(share < split_cfg["train_frac"] + split_cfg["val_frac"])
        .then(pl.lit("val"))
        .otherwise(pl.lit("test"))
        .alias("split")
    )


def assert_no_overlap(df: pl.DataFrame) -> None:
    """Fail if any complaint ID or normalized-text hash appears in more than one split."""
    for key in ("complaint_id", "text_hash"):
        multi = df.group_by(key).agg(pl.col("split").n_unique().alias("k")).filter(pl.col("k") > 1)
        if multi.height:
            raise AssertionError(f"{multi.height} {key} values appear in more than one split")


def assert_time_order(df: pl.DataFrame) -> None:
    """Fail unless every train date < every val date < every test date."""
    r = df.group_by("split").agg(lo=pl.col("date_received").min(), hi=pl.col("date_received").max())
    b = {row["split"]: row for row in r.iter_rows(named=True)}
    if not (b["train"]["hi"] < b["val"]["lo"] and b["val"]["hi"] < b["test"]["lo"]):
        raise AssertionError("time split date ordering violated")
