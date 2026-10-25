"""Priority proxy label (SPEC B5).

HIGH if the raw Issue is in ``configs/severity_issues.yaml``, OR company response is
"Closed with monetary relief", OR "Timely response?" is "No"; otherwise NORMAL. The
outcome columns are used only here and are dropped afterwards (SPEC C4).
"""

from __future__ import annotations

from typing import Any

import polars as pl

from complaintiq.data.taxonomy import load_yaml


def severity_issues(cfg: dict[str, Any]) -> list[str]:
    """Return the severity issue names."""
    data = load_yaml(cfg["taxonomy"]["severity_issues_path"])
    return [entry["name"] for entry in data["issues"]]


def rule_exprs(cfg: dict[str, Any], severity: list[str]) -> dict[str, pl.Expr]:
    """Boolean expression per B5 rule (null outcome values count as False)."""
    p = cfg["priority"]
    return {
        "rule_severity": pl.col("issue").is_in(severity).fill_null(False),
        "rule_monetary": (
            pl.col("company_response_to_consumer") == p["monetary_relief_value"]
        ).fill_null(False),
        "rule_untimely": (pl.col("timely_response") == p["untimely_value"]).fill_null(False),
    }


def derive_priority(
    lf: pl.LazyFrame, cfg: dict[str, Any], severity: list[str] | None = None
) -> pl.LazyFrame:
    """Add ``priority`` and the per-rule flags, then drop the outcome columns."""
    rules = rule_exprs(cfg, severity if severity is not None else severity_issues(cfg))
    return (
        lf.with_columns(**rules)
        .with_columns(
            priority=pl.when(pl.any_horizontal(*rules))
            .then(pl.lit("HIGH"))
            .otherwise(pl.lit("NORMAL"))
        )
        .drop(cfg["forbidden_input_columns"])
    )


def assert_no_forbidden(columns: list[str], cfg: dict[str, Any]) -> None:
    """Fail if any outcome column survived into the outputs."""
    bad = sorted(set(columns) & set(cfg["forbidden_input_columns"]))
    if bad:
        raise AssertionError(f"forbidden outcome columns in outputs: {bad}")
