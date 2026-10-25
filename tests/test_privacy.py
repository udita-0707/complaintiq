"""Unit tests for PII scrub patterns (synthetic strings only)."""

import polars as pl
import pytest

from complaintiq.privacy.pii import leak_report, luhn_ok, scrub


@pytest.mark.parametrize(
    "text",
    [
        "write to jane.doe+cfpb@example.co.uk today",
        "call (555) 123-4567 now",
        "call 555-123-4567 now",
        "call +1 555.123.4567 now",
        "ssn 123-45-6789 here",
        "card 4111 1111 1111 1111 here",
        "card 4111-1111-1111-1111 here",
        "account 1234567890 here",
    ],
)
def test_scrub_removes_pii(text: str) -> None:
    out = scrub(text)
    assert "[REDACTED]" in out


@pytest.mark.parametrize(
    "text",
    [
        "I paid $1500.00 on 12/01/2020 and again in 2021.",
        "Account ending in 1234 was charged 3 times.",
        "Reference [REDACTED] was closed.",
    ],
)
def test_scrub_keeps_non_pii(text: str) -> None:
    assert scrub(text) == text


def test_luhn() -> None:
    assert luhn_ok("4111 1111 1111 1111")
    assert not luhn_ok("4111 1111 1111 1112")
    assert not luhn_ok("1234")


def test_non_luhn_16_digits_is_still_long_digit_run() -> None:
    # Not a valid card, but a 16-digit run is still flagged by the long-digit rule.
    assert scrub("id 4111111111111112 x") == "id [REDACTED] x"


def test_leak_report_counts_rows() -> None:
    df = pl.DataFrame(
        {
            "split": ["train", "train", "test"],
            "narrative": ["mail a@b.com", "nothing here", "ssn 123-45-6789"],
        }
    )
    cfg = {"pii": {"long_digit_min": 9}}
    rep = leak_report(df, cfg).filter(pl.col("split") == "all").row(0, named=True)
    assert rep["rows"] == 3
    assert rep["pii_email"] == pytest.approx(1 / 3)
    assert rep["pii_ssn"] == pytest.approx(1 / 3)
    assert rep["pii_any"] == pytest.approx(2 / 3)
