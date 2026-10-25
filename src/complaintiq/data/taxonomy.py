"""Product/issue taxonomy harmonization (SPEC C4 steps 3-4).

``configs/product_mapping.yaml`` is curated by hand. ``configs/issue_mapping.yaml`` has a
curated ``merges`` table; its ``mapping`` (raw -> final class) is regenerated from the
merges, aggregate counts and ``taxonomy.issue_top_n``. Classes with no training rows go
to OTHER.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import yaml

from complaintiq.data.load import resolve


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML mapping file."""
    with resolve(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def product_map(cfg: dict[str, Any]) -> dict[str, str]:
    """Raw Product -> product class."""
    return dict(load_yaml(cfg["taxonomy"]["product_mapping_path"])["mapping"])


def product_excluded(cfg: dict[str, Any]) -> list[str]:
    """Raw Product values whose rows are dropped before cleaning."""
    return list(load_yaml(cfg["taxonomy"]["product_mapping_path"]).get("exclude") or [])


def issue_force_keep(cfg: dict[str, Any]) -> list[str]:
    """Harmonized issues kept as explicit classes regardless of top-N."""
    return list(load_yaml(cfg["taxonomy"]["issue_mapping_path"]).get("force_keep") or [])


def issue_merges(cfg: dict[str, Any]) -> dict[str, str]:
    """Raw Issue -> harmonized Issue for same-meaning renames."""
    return dict(load_yaml(cfg["taxonomy"]["issue_mapping_path"]).get("merges") or {})


def issue_map(cfg: dict[str, Any]) -> dict[str, str]:
    """Raw Issue -> final issue class (generated section)."""
    mapping = load_yaml(cfg["taxonomy"]["issue_mapping_path"]).get("mapping") or {}
    if not mapping:
        raise ValueError("issue_mapping.yaml has an empty `mapping`; run `make data-mappings`")
    return dict(mapping)


def harmonized_issue_expr(merges: dict[str, str]) -> pl.Expr:
    """Expression mapping raw ``issue`` through the merges table."""
    return pl.col("issue").replace(merges)


def propose_issue_mapping(
    df: pl.DataFrame,
    merges: dict[str, str],
    top_n: int,
    other: str,
    force_keep: list[str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Return raw -> class for every raw issue, and the harmonized issues sent to OTHER
    because they have zero training rows. ``df`` needs ``issue`` and ``split``.
    ``force_keep`` issues stay explicit classes even outside the top N."""
    h = df.select("issue", "split").with_columns(harmonized=harmonized_issue_expr(merges))
    counts = (
        h.group_by("harmonized")
        .agg(n=pl.len(), n_train=(pl.col("split") == "train").sum())
        .sort(["n", "harmonized"], descending=[True, False])
    )
    no_train = counts.filter(pl.col("n_train") == 0)["harmonized"].to_list()
    keep = counts.filter(pl.col("n_train") > 0).head(top_n)["harmonized"].to_list()
    keep_set = set(keep)
    for f in force_keep or []:
        if f in no_train or f not in set(counts["harmonized"].to_list()):
            raise ValueError(f"force_keep issue has no training rows: {f}")
        keep_set.add(f)
    raw = sorted(h["issue"].unique().to_list())
    mapping = {r: (merges.get(r, r) if merges.get(r, r) in keep_set else other) for r in raw}
    return mapping, sorted(no_train)


def write_issue_mapping(
    cfg: dict[str, Any], mapping: dict[str, str], top_n: int, n_forced: int = 0
) -> Path:
    """Rewrite the generated ``mapping`` section of issue_mapping.yaml, keeping the header
    and curated ``merges`` text exactly as written."""
    path = resolve(cfg["taxonomy"]["issue_mapping_path"])
    text = path.read_text(encoding="utf-8")
    head = text[: text.index("\nmapping:")].split("\n# Generated:")[0]
    body = yaml.safe_dump({"mapping": mapping}, sort_keys=False, allow_unicode=True, width=200)
    note = (
        f"\n# Generated: top {top_n} harmonized issues by frequency (with training rows)"
        f" plus {n_forced} force_keep outside the top {top_n}; rest -> OTHER.\n"
    )
    path.write_text(head + note + body, encoding="utf-8")
    return path


def apply_mappings(lf: pl.LazyFrame, cfg: dict[str, Any]) -> pl.LazyFrame:
    """Add ``product_class`` and ``issue_class``. Fails on any unmapped raw value."""
    pmap, imap = product_map(cfg), issue_map(cfg)
    return lf.with_columns(
        product_class=pl.col("product").replace_strict(pmap, return_dtype=pl.String),
        issue_class=pl.col("issue").replace_strict(imap, return_dtype=pl.String),
    )
