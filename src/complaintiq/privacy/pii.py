"""Residual PII checks and scrubbing (SPEC C4 Privacy, C10).

Regex only: emails, US phone numbers, SSNs, payment card numbers (Luhn-checked) and long
digit runs. Names are NOT detected, so residual name leaks are not measured.
``scrub(text)`` is the reusable function for inference-time scrubbing and
``scrub_with_counts(text)`` also returns how many spans were redacted and how many pattern
hits remain afterwards (M5, SPEC C8 "PII detected post-scrub"). Reports and metrics contain
counts only, never matched text.

polars is imported lazily (only the dataset leak report needs it), so the API image can
scrub without the data extra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
    return scrub_with_counts(text, placeholder).text


@dataclass(frozen=True)
class ScrubResult:
    """Scrubbed text plus counts (never the matched strings)."""

    text: str
    redactions: int  # spans replaced by the placeholder
    residual: int  # pattern hits still present after scrubbing (should be 0)
    by_pattern: dict[str, int]  # redactions per pattern name


def residual_hits(text: str) -> int:
    """Number of PII pattern hits in ``text`` (cards only when Luhn-valid)."""
    n = 0
    for name, rx in _COMPILED.items():
        if name == "card":
            n += sum(1 for m in rx.finditer(text) if luhn_ok(m.group(0)))
        else:
            n += sum(1 for _ in rx.finditer(text))
    return n


def scrub_with_counts(text: str, placeholder: str = PLACEHOLDER) -> ScrubResult:
    """Scrub ``text`` like :func:`scrub` and count what was replaced and what is left.

    ``residual`` re-runs every pattern on the output; a non-zero value means a pattern
    overlap the scrub order did not catch. The caller should treat it as an alert
    (counter), never log the text.
    """
    out = text
    by_pattern: dict[str, int] = {}
    for name, rx in _COMPILED.items():
        if name == "card":
            hits = 0

            def _card(m: re.Match[str]) -> str:
                nonlocal hits
                if luhn_ok(m.group(0)):
                    hits += 1
                    return placeholder
                return m.group(0)

            out = rx.sub(_card, out)
        else:
            out, hits = rx.subn(placeholder, out)
        by_pattern[name] = hits
    return ScrubResult(
        text=out,
        redactions=sum(by_pattern.values()),
        residual=residual_hits(out),
        by_pattern=by_pattern,
    )


def flag_exprs(col: str = "narrative", min_digits: int = 9) -> dict[str, pl.Expr]:
    """Per-pattern boolean expressions (row contains at least one hit).

    ``card`` here is the regex-only candidate count; ``leak_report`` adds the Luhn-valid
    count separately because Luhn needs Python.
    """
    import polars as pl

    return {f"pii_{n}": pl.col(col).str.contains(p) for n, p in patterns(min_digits).items()}


def leak_report(df: pl.DataFrame, cfg: dict[str, Any], by: str = "split") -> pl.DataFrame:
    """Leak rate (share of rows with >= 1 hit) per pattern, grouped by ``by`` and overall."""
    import polars as pl

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
