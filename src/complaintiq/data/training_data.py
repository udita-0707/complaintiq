"""Training-data access for M3 (SPEC C5): split loading, sampling, priors, data version.

The test split is off limits during model development: ``load_split("test")`` raises
unless the environment variable ``CIQ_ALLOW_TEST=1`` is set (reserved for M4).
Never prints or logs complaint text.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import polars as pl

from complaintiq.config import load_config
from complaintiq.data.load import resolve
from complaintiq.data.priority import severity_issues

LABEL_COLS: dict[str, str] = {
    "product": "product_class",
    "issue": "issue_class",
    "priority": "priority",
}
DEV_SPLITS = ("train", "val")
TEST_ENV_VAR = "CIQ_ALLOW_TEST"
_ALL_SPLITS = ("train", "val", "test")


def split_dir(scheme: str = "time", processed_dir: str | Path | None = None) -> Path:
    """Directory holding ``{train,val,test}.parquet`` for a split scheme."""
    base = processed_dir if processed_dir is not None else load_config("data")["processed_dir"]
    return resolve(base) / scheme


def _check_split(split: str) -> None:
    if split not in _ALL_SPLITS:
        raise ValueError(f"unknown split '{split}'; expected one of {DEV_SPLITS}")
    if split == "test" and os.environ.get(TEST_ENV_VAR) != "1":
        raise PermissionError(
            f"the test split is off limits during model development; set {TEST_ENV_VAR}=1 "
            "only for final M4 reporting"
        )


def load_split(
    split: str,
    scheme: str = "time",
    columns: list[str] | None = None,
    processed_dir: str | Path | None = None,
) -> pl.DataFrame:
    """Load one processed split as a polars DataFrame.

    Args:
        split: ``"train"`` or ``"val"`` (``"test"`` only with ``CIQ_ALLOW_TEST=1``).
        scheme: split scheme subdirectory (``time`` or ``random``).
        columns: subset of columns to read; ``None`` reads all.
        processed_dir: override for ``configs/data.yaml: processed_dir`` (tests).
    """
    _check_split(split)
    path = split_dir(scheme, processed_dir) / f"{split}.parquet"
    return pl.read_parquet(path, columns=columns)


def sample_train(
    df: pl.DataFrame,
    label_col: str,
    cap_per_class: int | None = None,
    max_rows: int | None = None,
    seed: int = 42,
) -> pl.DataFrame:
    """Seeded stratified subsample that never drops a class.

    ``cap_per_class`` first clips every class to at most that many rows. ``max_rows``
    then scales every class proportionally so the total is about ``max_rows``, keeping
    at least one row per class. Rows inside a class are chosen by a seeded shuffle.
    """
    if df.height == 0:
        return df
    counts = df.group_by(label_col).len().rename({"len": "n"})
    quota = counts.with_columns(q=pl.col("n").cast(pl.Int64))  # u32 counts overflow below
    if cap_per_class is not None:
        quota = quota.with_columns(q=pl.min_horizontal(pl.col("q"), pl.lit(cap_per_class)))
    total = int(quota["q"].sum())
    if max_rows is not None and total > max_rows:
        quota = quota.with_columns(
            q=pl.max_horizontal(
                pl.lit(1), (pl.col("q").cast(pl.Float64) * max_rows / total).floor().cast(pl.Int64)
            )
        )
    shuffled = df.sample(fraction=1.0, shuffle=True, seed=seed)
    return (
        shuffled.join(quota.select(label_col, "q"), on=label_col, how="left")
        .with_columns(_rank=pl.int_range(pl.len()).over(label_col))
        .filter(pl.col("_rank") < pl.col("q"))
        .drop("_rank", "q")
    )


def class_priors(df: pl.DataFrame, label_col: str) -> dict[str, float]:
    """Share of each class in ``df[label_col]`` (sums to 1), sorted by label."""
    counts = df.group_by(label_col).len().sort(label_col)
    n = int(counts["len"].sum())
    return {str(k): v / n for k, v in zip(counts[label_col], counts["len"], strict=True)}


def data_version(scheme: str = "time", processed_dir: str | Path | None = None) -> str:
    """First 12 hex chars of SHA-256 over the three split files (bytes only; never parsed).

    Identifies the exact data a run used; any change to any split file changes it.
    """
    d = split_dir(scheme, processed_dir)
    stats = []
    for s in _ALL_SPLITS:
        st = os.stat(d / f"{s}.parquet")
        stats.append((str(d / f"{s}.parquet"), st.st_mtime_ns, st.st_size))
    return _hash_files(tuple(stats))


@lru_cache(maxsize=8)
def _hash_files(stats: tuple[tuple[str, int, int], ...]) -> str:
    """Hash file bytes; cached on (path, mtime, size) so repeated calls are cheap."""
    h = hashlib.sha256()
    for path, _mtime, _size in stats:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()[:12]


def severity_mask(raw_issue: pl.Series) -> pl.Series:
    """True where the RAW issue is on the B5 severity list (``configs/severity_issues.yaml``).

    Reuses ``priority.severity_issues``; used for evaluation slices only, never as a feature.
    """
    return raw_issue.is_in(severity_issues(load_config("data"))).fill_null(False)
