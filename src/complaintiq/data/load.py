"""Lazy loading of the raw Parquet mirror (SPEC C4).

Only the columns in ``configs/data.yaml: input_columns`` are ever read, and only rows
with a non-empty narrative are kept. Never prints or logs complaint text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve(path: str | Path) -> Path:
    """Resolve a config path relative to the repo root."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def scan_raw(cfg: dict[str, Any], source: str | Path | None = None) -> pl.LazyFrame:
    """Scan the raw Parquet files lazily and return the narrative-bearing rows.

    Columns are renamed to snake_case per ``input_columns``; ``date_received`` is
    parsed to ``pl.Date``. ``source`` overrides ``raw_parquet_glob`` (used by tests).
    """
    columns: dict[str, str] = cfg["input_columns"]
    src = source if source is not None else resolve(cfg["raw_parquet_glob"])
    narrative = columns_inverse(columns)["narrative"]
    return (
        pl.scan_parquet(src)
        .select(list(columns))
        .filter(pl.col(narrative).str.strip_chars().str.len_chars() > 0)
        .rename(columns)
        .with_columns(pl.col("date_received").str.to_date("%Y-%m-%d", strict=True))
    )


def columns_inverse(columns: dict[str, str]) -> dict[str, str]:
    """Map snake_case names back to raw headers."""
    return {v: k for k, v in columns.items()}
