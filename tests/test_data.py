"""Unit and data tests for the M2 pipeline pieces (synthetic rows only)."""

from datetime import date

import polars as pl
import pytest

from complaintiq.config import load_config
from complaintiq.data import taxonomy
from complaintiq.data.clean import clean, normalize_expr
from complaintiq.data.priority import assert_no_forbidden, derive_priority
from complaintiq.data.split import (
    assert_no_overlap,
    assert_time_order,
    compute_cutoffs,
    random_split_expr,
    time_split_expr,
)


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config("data")


def norm(text: str) -> str:
    return pl.DataFrame({"narrative": [text]}).select(normalize_expr())["narrative"][0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("On XX/XX/XXXX I called XXXX XXXX bank.", "On [REDACTED] I called [REDACTED] bank."),
        ("acct XXXX1234 and XXXXbank", "acct [REDACTED] 1234 and [REDACTED] bank"),
        ("a b\n\n  c\t", "a b c"),
        ("ﬁle Exxon taxx", "file Exxon taxx"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert norm(raw) == expected


def words(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def test_clean_filters_and_dedups(cfg: dict) -> None:
    long_a, long_b = words(25, "a"), words(25, "b")
    lf = pl.LazyFrame(
        {
            "complaint_id": [1, 2, 3, 3, 4],
            "date_received": [date(2020, 1, d) for d in (5, 1, 2, 2, 3)],
            "narrative": [long_a, long_a.upper(), long_b, long_b, "too short"],
            "product": ["P1", "P2", "P1", "P1", "P1"],
            "issue": ["I1", "I1", "I2", "I2", "I1"],
        }
    )
    res = clean(lf, cfg)
    assert res.counts["after_min_words"] == 4
    assert res.counts["after_dedup_id"] == 3
    assert res.counts["after_dedup_text"] == 2
    # Duplicate text keeps the earliest row (id 2, Jan 1).
    assert sorted(res.df["complaint_id"].to_list()) == [2, 3]
    # The one duplicate group has conflicting product labels.
    assert res.dup_groups["products"].list.len().to_list() == [2]


def test_priority_rules_and_outcome_drop(cfg: dict) -> None:
    lf = pl.LazyFrame(
        {
            "issue": ["Fraud or scam", "Other", "Other", "Other", "Other"],
            "company_response_to_consumer": [
                "Closed with explanation",
                "Closed with monetary relief",
                "Closed with explanation",
                None,
                "Closed with explanation",
            ],
            "timely_response": ["Yes", "Yes", "No", "Yes", None],
        }
    )
    out = derive_priority(lf, cfg, severity=["Fraud or scam"]).collect()
    assert out["priority"].to_list() == ["HIGH", "HIGH", "HIGH", "NORMAL", "NORMAL"]
    assert_no_forbidden(out.columns, cfg)


def test_forbidden_columns_detected(cfg: dict) -> None:
    with pytest.raises(AssertionError):
        assert_no_forbidden(["narrative", "timely_response"], cfg)


def test_time_split_order_and_fractions() -> None:
    dates = pl.Series("date_received", [date(2020, 1, 1 + i // 10) for i in range(200)])
    cut = compute_cutoffs(dates, 0.70, 0.15)
    df = pl.DataFrame(
        {"date_received": dates, "complaint_id": range(200), "text_hash": range(200)}
    ).with_columns(time_split_expr(cut))
    shares = df["split"].value_counts(normalize=True).sort("split")
    assert dict(shares.iter_rows()) == pytest.approx({"test": 0.15, "train": 0.70, "val": 0.15})
    assert_time_order(df)
    assert_no_overlap(df)


def test_overlap_detected() -> None:
    df = pl.DataFrame({"complaint_id": [1, 2], "text_hash": [9, 9], "split": ["train", "test"]})
    with pytest.raises(AssertionError):
        assert_no_overlap(df)


def test_random_split_is_stratified_and_deterministic(cfg: dict) -> None:
    df = pl.DataFrame({"complaint_id": range(1000), "product_class": ["A"] * 800 + ["B"] * 200})
    a = df.with_columns(random_split_expr(cfg, seed=42))
    b = df.with_columns(random_split_expr(cfg, seed=42))
    assert a["split"].to_list() == b["split"].to_list()
    share_b = a.filter(pl.col("product_class") == "B")["split"].value_counts(normalize=True)
    assert dict(share_b.iter_rows())["train"] == pytest.approx(0.70)


def test_mapping_files_cover_known_values(cfg: dict) -> None:
    pmap = taxonomy.product_map(cfg)
    assert "Credit reporting or other personal consumer reports" in pmap
    classes = set(pmap.values())
    assert 10 <= len(classes) <= 14
    imap = taxonomy.issue_map(cfg)
    other = cfg["taxonomy"]["other_label"]
    kept = {v for v in imap.values() if v != other}
    force = set(taxonomy.issue_force_keep(cfg))
    top_n = cfg["taxonomy"]["issue_top_n"]
    assert force <= kept
    assert top_n <= len(kept) <= top_n + len(force)
    assert "Consumer Loan" in taxonomy.product_excluded(cfg)
    assert "Consumer Loan" not in pmap


def test_jensen_shannon_bounds() -> None:
    import numpy as np

    from complaintiq.data.analysis import jensen_shannon

    assert jensen_shannon(np.array([5.0, 5.0]), np.array([1.0, 1.0])) == pytest.approx(0.0)
    assert jensen_shannon(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(1.0)


def test_shift_tests_detects_shift() -> None:
    from complaintiq.data.analysis import shift_tests

    df = pl.DataFrame(
        {
            "split": ["train"] * 100 + ["val"] * 100 + ["test"] * 100,
            "y": ["a"] * 50 + ["b"] * 50 + ["a"] * 50 + ["b"] * 50 + ["a"] * 90 + ["b"] * 10,
        }
    )
    out = {r["comparison"]: r for r in shift_tests(df, ["y"]).iter_rows(named=True)}
    assert out["train vs val"]["jsd"] == pytest.approx(0.0)
    assert float(out["train vs val"]["p_value"]) > 0.99
    assert float(out["train vs test"]["p_value"]) < 1e-6
    assert out["train vs test"]["cramers_v"] > 0.3
