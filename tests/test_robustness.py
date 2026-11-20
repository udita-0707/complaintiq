"""Tests for M4 robustness, evaluation and iteration helpers (synthetic data only)."""

import numpy as np
import polars as pl
import pytest

from complaintiq.eval import robustness as rb
from complaintiq.eval.evaluation import paired_bootstrap_macro_f1
from complaintiq.models import iterations as it

TEXT = "The collector called me ten times. I do not owe this debt! Please stop the calls."
CFG = {
    "typo_rates": [0.01, 0.05], "truncate_words": [3], "boilerplate_prefix": "PRE.",
    "boilerplate_suffix": "SUF.", "redact_extra_frac": 0.5,
}


def test_typos_seeded_and_scaled() -> None:
    a = rb.add_typos(TEXT * 20, 0.05, np.random.default_rng(1))
    b = rb.add_typos(TEXT * 20, 0.05, np.random.default_rng(1))
    assert a == b and a != TEXT * 20
    assert rb.add_typos(TEXT, 0.0, np.random.default_rng(1)) == TEXT
    few = sum(x != y for x, y in zip(rb.add_typos(TEXT * 50, 0.01, np.random.default_rng(2)),
                                     TEXT * 50, strict=False))
    many = sum(x != y for x, y in zip(rb.add_typos(TEXT * 50, 0.05, np.random.default_rng(2)),
                                      TEXT * 50, strict=False))
    assert many >= few


def test_truncate_shuffle_boilerplate_redact() -> None:
    assert rb.truncate_words(TEXT, 3) == "The collector called"
    shuffled = rb.shuffle_sentences(TEXT, np.random.default_rng(0))
    assert sorted(shuffled.split()) == sorted(TEXT.split())
    assert rb.shuffle_sentences("one sentence only", np.random.default_rng(0)) == (
        "one sentence only")
    assert rb.add_boilerplate("x", "PRE.", "SUF.") == "PRE. x SUF."
    red = rb.redact_more(TEXT, 1.0, np.random.default_rng(0), "[REDACTED]")
    assert set(red.split()) == {"[REDACTED]"}
    assert rb.redact_more(TEXT, 0.0, np.random.default_rng(0), "[REDACTED]") == TEXT


def test_perturbation_names_and_apply_is_deterministic() -> None:
    p = rb.perturbations(CFG, "[REDACTED]")
    assert list(p) == ["typos_1pct", "typos_5pct", "truncate_first_3_words", "sentence_shuffle",
                       "added_boilerplate", "lowercase", "redacted_plus_50pct"]
    texts = [TEXT, TEXT.upper()]
    for name, fn in p.items():
        assert rb.apply(texts, fn, 42, name) == rb.apply(texts, fn, 42, name)
    assert rb.apply(texts, p["lowercase"], 42, "lowercase")[1] == TEXT.upper().lower()


def test_drop_table() -> None:
    t = rb.drop_table({"macro_f1": 0.8, "accuracy": 0.9},
                      {"typos": {"macro_f1": 0.7, "accuracy": 0.85, "flip_rate": 0.1}})
    assert t["drop"].to_list() == pytest.approx([0.0, 0.1])


def test_paired_bootstrap_identical_and_better() -> None:
    y = np.array(["a", "b", "c"] * 50)
    same = paired_bootstrap_macro_f1(y, y, y, n_boot=50)
    assert same["diff"] == 0 and same["lo"] == 0 and same["hi"] == 0
    worse = y.copy()
    worse[:30] = "c"
    r = paired_bootstrap_macro_f1(y, y, worse, n_boot=200)
    assert r["diff"] > 0 and r["lo"] > 0 and r["p_le_0"] == 0


def test_prior_adjust_and_class_weights() -> None:
    p = np.array([[0.6, 0.4], [0.45, 0.55]])
    assert np.allclose(it.prior_adjust(p, np.array([0.1, 0.9]), 0.0), p)
    adj = it.prior_adjust(p, np.array([0.1, 0.9]), 1.0)
    assert np.allclose(adj.sum(1), 1) and (adj.argmax(1) == 1).all()
    y = np.array(["a"] * 90 + ["b"] * 10)
    w1, w0, wh = (it.powered_class_weights(y, p) for p in (1.0, 0.0, 0.5))
    assert w1["b"] == pytest.approx(5.0) and w0 == {"a": 1.0, "b": 1.0}
    assert wh["b"] == pytest.approx(5.0 ** 0.5)


def test_issue_restriction() -> None:
    mask = it.allowed_issue_mask(
        np.array(["P1"] * 5 + ["P2"] * 5), np.array(["i1"] * 5 + ["i2"] * 4 + ["i1"]),
        ["P1", "P2", "P3"], ["i1", "i2"], min_rows=2,
    )
    assert mask.tolist() == [[True, False], [False, True], [True, True]]
    prob = np.array([[0.3, 0.7], [0.6, 0.4]])
    out = it.restrict_issues(prob, np.array([0, 2]), mask)
    assert out.tolist() == [[1.0, 0.0], [0.6, 0.4]]
    assert isinstance(pl.DataFrame(), pl.DataFrame)
