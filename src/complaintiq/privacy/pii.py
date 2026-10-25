"""Residual PII checks and scrubbing (SPEC C4 Privacy, C10).

Regex only: emails, US phone numbers, SSNs, payment card numbers (Luhn-checked) and long
digit runs. Names are NOT detected, so residual name leaks are not measured.
``scrub(text)`` is the reusable function for inference-time scrubbing. Reports contain
counts only, never matched text.
"""

from __future__ import annotations

import re
from typing import Any

import polars as pl

PLACEHOLDER = "[REDACTED]"

EMAIL = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
PHONE = r"(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\b\d{3})[\s.\-]?\d{3}[\s.\-]\d{4}\b"
SSN = r"\b\d{3}-\d{2}-\d{4}\b"
# 13-19 digits, optionally grouped by single spaces or dashes; Luhn check in Python.
CARD = r"\b(?:\d[ \-]?){12,18}\d\b"


def long_digits_pattern(min_len: int = 9) -> str:
    """Pattern for a run of at least ``min_len`` consecutive digits."""
    return rf"\b\d{{{min_len},}}\b"


def patterns(min_digits: int = 9) -> dict[str, str]:
    """All PII patterns by name, in scrub order (most specific first)."""
    return {
        "email": EMAIL,
        "ssn": SSN,
        "card": CARD,
        "phone": PHONE,
        "long_digits": long_digits_pattern(min_digits),
    }


def luhn_ok(candidate: str) -> bool:
    """True if the digits of ``candidate`` (13-19 of them) pass the Luhn checksum."""
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_COMPILED = {name: re.compile(p) for name, p in patterns().items()}


def scrub(text: str, placeholder: str = PLACEHOLDER) -> str:
    """Replace emails, SSNs, Luhn-valid card numbers, phone numbers and long digit runs
    in ``text`` with ``placeholder``."""
    out = text
    for name, rx in _COMPILED.items():
        if name == "card":
            out = rx.sub(lambda m: placeholder if luhn_ok(m.group(0)) else m.group(0), out)
        else:
            out = rx.sub(placeholder, out)
    return out


def flag_exprs(col: str = "narrative", min_digits: int = 9) -> dict[str, pl.Expr]:
    """Per-pattern boolean expressions (row contains at least one hit).

    ``card`` here is the regex-only candidate count; ``leak_report`` adds the Luhn-valid
    count separately because Luhn needs Python.
    """
    return {f"pii_{n}": pl.col(col).str.contains(p) for n, p in patterns(min_digits).items()}


def leak_report(df: pl.DataFrame, cfg: dict[str, Any], by: str = "split") -> pl.DataFrame:
    """Leak rate (share of rows with >= 1 hit) per pattern, grouped by ``by`` and overall."""
    min_digits = int(cfg["pii"]["long_digit_min"])
    flags = flag_exprs("narrative", min_digits)
    card_luhn = (
        pl.col("narrative")
        .str.extract_all(CARD)
        .list.eval(pl.element().map_elements(luhn_ok, return_dtype=pl.Boolean))
        .list.any()
        .fill_null(False)
        .alias("pii_card_luhn")
    )
    f = df.select(by, "narrative").with_columns(**flags).with_columns(card_luhn)
    names = [*flags, "pii_card_luhn"]
    f = f.with_columns(pii_any=pl.any_horizontal([n for n in names if n != "pii_card"]))
    aggs = [pl.len().alias("rows"), *[pl.col(n).mean().alias(n) for n in [*names, "pii_any"]]]
    grouped = f.group_by(by).agg(*aggs).with_columns(pl.col(by).cast(pl.String)).sort(by)
    overall = f.select(pl.lit("all").alias(by), *aggs)
    return pl.concat([grouped, overall])
