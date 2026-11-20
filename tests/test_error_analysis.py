"""Tests for complaintiq.eval.error_analysis (synthetic data only; no data files)."""

import numpy as np
import polars as pl
import pytest

from complaintiq.eval import error_analysis as ea

CATS = ["label ambiguity", "multi-topic narrative", "short or uninformative",
        "taxonomy mismatch", "genuine model error"]


def test_allocate_proportional_min_one_and_capped() -> None:
    q = ea.allocate({"a": 900, "b": 90, "c": 9, "d": 1}, 20)
    assert sum(q.values()) == 20
    assert all(q[k] >= 1 for k in "abcd")
    assert q["a"] > q["b"] > 0
    assert q["d"] == 1
    assert ea.allocate({"a": 3, "b": 2}, 10) == {"a": 3, "b": 2}
    assert sum(ea.allocate({"a": 5, "b": 4, "c": 3}, 2).values()) == 2


def test_sample_errors_seeded_and_stratified() -> None:
    errs = pl.DataFrame({
        "complaint_id": [str(i) for i in range(300)],
        "true": ["x"] * 200 + ["y"] * 90 + ["z"] * 10,
    })
    s1 = ea.sample_errors(errs, 30, seed=42)
    s2 = ea.sample_errors(errs, 30, seed=42)
    assert s1.equals(s2)
    assert s1.height == 30
    counts = dict(s1.group_by("true").len().iter_rows())
    assert set(counts) == {"x", "y", "z"} and counts["x"] > counts["y"] > counts["z"] - 1
    assert s1["complaint_id"].n_unique() == 30


def test_margins_and_confusions() -> None:
    prob = np.array([[0.7, 0.2, 0.1], [0.1, 0.6, 0.3]])
    m = ea.margins(prob, np.array([0, 1]), np.array([1, 1]))
    assert m.tolist() == pytest.approx([0.5, 0.0])
    conf = ea.top_confusions(["a", "a", "a", "b", "b"], ["b", "b", "a", "a", "b"], k=5)
    assert conf.row(0, named=True) == {"true": "a", "predicted": "b", "n": 2,
                                       "share_of_true": pytest.approx(2 / 3),
                                       "share_of_errors": pytest.approx(2 / 3)}
    assert conf.height == 2


def test_error_rate_by_and_length_bucket() -> None:
    df = pl.DataFrame({"n_words": [20, 150, 250, 500], "is_error": [True, False, True, True]})
    df = df.with_columns(b=ea.length_bucket(pl.col("n_words"), [100, 200, 400]))
    assert df["b"].to_list() == ["<100", "100-199", "200-399", ">=400"]
    r = ea.error_rate_by(df.with_columns(g=pl.lit("all")), "g")
    assert r.row(0, named=True) == {"g": "all", "n": 4, "errors": 3, "error_rate": 0.75}


def test_summarize_categories_counts_shares_and_rejects_unknown() -> None:
    sample = pl.DataFrame({
        "task": ["issue"] * 4 + ["product"] * 2,
        "error_category": ["label ambiguity", "Label Ambiguity ", "genuine model error", "",
                           "taxonomy mismatch", None],
    })
    s = ea.summarize_categories(sample, CATS)
    issue = {r["category"]: r for r in s.filter(pl.col("task") == "issue").iter_rows(named=True)}
    assert issue["label ambiguity"]["n"] == 2
    assert issue["label ambiguity"]["share"] == pytest.approx(2 / 3)
    assert issue["(unlabelled)"]["n"] == 1
    prod = s.filter((pl.col("task") == "product") & (pl.col("category") == "taxonomy mismatch"))
    assert prod["share"][0] == 1.0
    with pytest.raises(ValueError):
        ea.summarize_categories(sample.with_columns(error_category=pl.lit("typo")), CATS)


def test_replace_section_keeps_markers() -> None:
    text = f"head\n{ea.HUMAN_START}\nold\n{ea.HUMAN_END}\ntail"
    out = ea.replace_section(text, "new body")
    assert "old" not in out and "new body" in out
    assert out.startswith("head") and out.endswith("tail")
    assert ea.HUMAN_START in out and ea.HUMAN_END in out
