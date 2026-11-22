"""M5 drift monitoring: PSI/KL, confidence, length and OOV drift, replay (synthetic only)."""

import math
from datetime import date

import polars as pl
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from complaintiq.config import load_config
from complaintiq.models import baseline
from complaintiq.monitoring import drift


def test_psi_kl_basics() -> None:
    ref = {"a": 0.5, "b": 0.5}
    assert drift.psi(ref, ref) == pytest.approx(0.0)
    assert drift.kl(ref, ref) == pytest.approx(0.0)
    cur = {"a": 0.9, "b": 0.1}
    expected = (0.9 - 0.5) * math.log(0.9 / 0.5) + (0.1 - 0.5) * math.log(0.1 / 0.5)
    assert drift.psi(ref, cur) == pytest.approx(expected)
    assert drift.kl(cur, ref) > 0
    assert drift.psi({"a": 1.0}, {"b": 1.0}, eps=1e-4) > 10  # disjoint supports are huge
    assert math.isnan(drift.psi({}, cur))


def test_distribution_confidence_and_drop() -> None:
    assert drift.distribution(["x", "y", "x", "x"]) == {"x": 0.75, "y": 0.25}
    assert drift.distribution([]) == {}
    st = drift.confidence_stats([0.2, 0.4, 0.6, 0.8], (0.5,))
    assert st == {"mean": pytest.approx(0.5), "q50": pytest.approx(0.5)}
    assert math.isnan(drift.confidence_stats([])["mean"])
    assert drift.relative_drop(0.8, 0.7) == pytest.approx(0.125)
    assert math.isnan(drift.relative_drop(0.0, 0.5))


def test_length_buckets_match_m2_labels() -> None:
    edges = [100, 200, 400]
    assert [drift.bucket_label(n, edges) for n in (20, 100, 199, 399, 400)] == [
        "<100", "100-199", "100-199", "200-399", ">=400"]
    assert drift.length_distribution([20, 30, 150, 500], edges) == {
        "100-199": 0.25, "<100": 0.5, ">=400": 0.25}


def test_oov_rate_uses_vectorizer_tokens_and_unigrams_only() -> None:
    vec = TfidfVectorizer(ngram_range=(1, 2)).fit(["debt collector calls", "credit report error"])
    vocab = drift.unigram_vocabulary(vec)
    assert "debt" in vocab and "debt collector" not in vocab
    rate = drift.oov_rate(["debt collector zebra", "credit unicorn"], vec.build_analyzer(), vocab)
    assert rate == pytest.approx(2 / 5)
    assert math.isnan(drift.oov_rate([], vec.build_analyzer(), vocab))


def test_top_shifts_and_flags() -> None:
    shifts = drift.top_shifts({"a": 0.6, "b": 0.4}, {"a": 0.2, "b": 0.5, "c": 0.3}, k=2)
    assert [s["label"] for s in shifts] == ["a", "c"]
    cfg = load_config("monitoring")
    stats = {"n": 10_000, "product": {"psi_vs_train": 0.3}, "issue": {"psi_vs_train": 0.1},
             "confidence": {"drop_vs_reference": 0.15}, "length": {"psi_vs_train": math.nan}}
    assert drift.period_flags(stats, cfg) == ["product PSI", "confidence drop"]
    assert drift.period_flags({**stats, "n": 10}, cfg) == []


TEMPLATES = {
    "Debt collection": ("collector keeps calling about a debt i do not owe",
                        "Attempts to collect"),
    "Mortgage": ("servicer denied my mortgage modification request", "Struggling to pay"),
    "Credit card": ("card was charged twice for one purchase at a store",
                    "Problem with a purchase"),
}


def _frame(spec: list[tuple[str, date, int]]) -> pl.DataFrame:
    rows = []
    for product, day, n in spec:
        text, issue = TEMPLATES[product]
        for i in range(n):
            rows.append({"narrative": f"{text} and they never answered my letter number {i}",
                         "product_class": product, "issue_class": issue,
                         "n_words": 14 + (i % 300), "date_received": day})
    return pl.DataFrame(rows)


@pytest.fixture(scope="module")
def tiny() -> tuple:
    train = _frame([(p, date(2020, 1, 1), 40) for p in TEMPLATES])
    cfg = baseline.load_baseline_config()
    params = baseline.variant_params(cfg, cfg["default_variant"])
    params["features"].update(min_df=1, max_df=1.0)
    labels = {"product": train["product_class"].to_list(),
              "issue": train["issue_class"].to_list(),
              "priority": ["NORMAL", "HIGH"] * (train.height // 2)}
    model = baseline.fit_model(train["narrative"].to_list(), labels, params)
    return train, model


def test_replay_flags_the_shifted_month_and_reports_no_text(tiny: tuple) -> None:
    train, model = tiny
    val = _frame([
        ("Debt collection", date(2022, 9, 5), 30), ("Mortgage", date(2022, 9, 6), 30),
        ("Credit card", date(2022, 9, 7), 30),
        ("Debt collection", date(2022, 10, 5), 30), ("Mortgage", date(2022, 10, 6), 30),
        ("Credit card", date(2022, 10, 7), 30),
        ("Mortgage", date(2022, 11, 3), 90),  # November: everything is mortgage
        ("Credit card", date(2022, 12, 1), 5),  # tiny period: reported, never flagged
    ]).drop("product_class", "issue_class")
    cfg = {**load_config("monitoring"), "min_rows_per_period": 50, "oov_sample_rows": 40,
           "vectorize_chunk_rows": 25}
    th = {"tau": 0.5, "temperature_product": 1.5, "temperature_issue": 1.0}
    res = drift.replay_frames(train, val, model, th, cfg)
    by = {p["period"]: p for p in res["periods"]}
    assert list(by) == ["2022-09", "2022-10", "2022-11", "2022-12"]
    assert res["confidence_reference_period"] == "2022-09"
    assert by["2022-09"]["product"]["psi_vs_train"] < 0.05
    assert by["2022-09"]["confidence"]["drop_vs_reference"] == pytest.approx(0.0)
    assert "product PSI" in by["2022-11"]["flags"]
    assert by["2022-11"]["product"]["psi_vs_reference_period"] > 0.2
    assert by["2022-12"]["flags"] == []
    assert res["flagged_periods"] == ["2022-11"]
    assert 0.0 <= by["2022-10"]["oov_rate"] <= 1.0
    md = drift.render_report(res, {"model_id": "m", "model_version": "v",
                                   "data_version": "d", "run_id": "r"})
    assert "| 2022-11 |" in md and "product PSI" in md
    assert "never answered my letter" not in md
