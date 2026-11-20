"""Tests for complaintiq.models.calibrate (synthetic data only; no data files)."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from complaintiq.models import calibrate as cal


def test_split_val_ab_is_seeded_stratified_and_balanced() -> None:
    y = np.array(["a"] * 100 + ["b"] * 10 + ["c"] * 3)
    m1 = cal.split_val_ab(y, 0.5, seed=42)
    m2 = cal.split_val_ab(y, 0.5, seed=42)
    assert (m1 == m2).all()
    assert not (m1 == cal.split_val_ab(y, 0.5, seed=7)).all()
    assert m1[y == "a"].sum() == 50
    assert m1[y == "b"].sum() == 5
    assert 1 <= m1[y == "c"].sum() <= 2


def test_apply_temperature_keeps_argmax_and_rows_sum_to_one() -> None:
    rng = np.random.default_rng(0)
    p = rng.dirichlet(np.ones(5), size=50)
    for t in (0.5, 1.0, 3.0):
        q = cal.apply_temperature(p, t)
        assert np.allclose(q.sum(axis=1), 1)
        assert (q.argmax(axis=1) == p.argmax(axis=1)).all()
    assert (cal.apply_temperature(p, 3.0).max(1) < p.max(1) + 1e-12).all()  # T > 1 softens


def test_fit_temperature_recovers_overconfidence() -> None:
    rng = np.random.default_rng(1)
    n, k = 4000, 4
    logits = rng.normal(size=(n, k)) * 2
    true_p = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    y = np.array([rng.choice(k, p=row) for row in true_p])
    overconfident = cal.apply_temperature(true_p, 0.4)  # sharpened by 1 / 0.4
    t = cal.fit_temperature(overconfident, y)
    assert 2.0 < t < 3.2  # about 1 / 0.4 = 2.5
    conf_raw = overconfident.max(1)
    ok = overconfident.argmax(1) == y
    after = cal.apply_temperature(overconfident, t).max(1)
    assert cal.expected_calibration_error(after, ok) < cal.expected_calibration_error(conf_raw, ok)


def test_ece_zero_when_confidence_matches_accuracy() -> None:
    conf = np.array([0.8] * 10)
    ok = np.array([True] * 8 + [False] * 2)
    assert cal.expected_calibration_error(conf, ok, n_bins=10) == pytest.approx(0.0)
    assert cal.expected_calibration_error(np.array([1.0] * 4), np.array([False] * 4)) == 1.0


def test_choose_tau_max_coverage_at_target() -> None:
    conf = np.array([0.99, 0.95, 0.9, 0.8, 0.7, 0.6])
    ok = np.array([True, True, True, True, False, False])
    r = cal.choose_tau(conf, ok, target_precision=0.95)
    assert r == {"tau": 0.8, "precision": 1.0, "coverage": pytest.approx(4 / 6), "n_auto": 4}
    assert cal.choose_tau(conf, ok, target_precision=0.95, min_rows=5) is None
    assert cal.choose_tau(conf, np.zeros(6, bool), 0.95) is None


def test_choose_tau_respects_ties() -> None:
    conf = np.array([0.9, 0.8, 0.8, 0.7])
    ok = np.array([True, True, False, True])
    r = cal.choose_tau(conf, ok, target_precision=0.95)
    assert r is not None and r["tau"] == 0.9  # 0.8 would include the tied wrong row


def test_coverage_precision_and_priority_threshold() -> None:
    curve = cal.coverage_precision(np.array([0.9, 0.5]), np.array([True, False]), [0.0, 0.6, 1.0])
    assert curve["coverage"].to_list() == [1.0, 0.5, 0.0]
    assert curve["precision"].to_list()[:2] == [0.5, 1.0]
    y = np.array([1, 1, 1, 1, 0, 0])
    s = np.array([0.9, 0.8, 0.3, 0.2, 0.5, 0.1])
    thr = cal.choose_priority_threshold(y, s, target_recall=0.75)
    assert thr == 0.3
    assert cal.binary_at(y, s, thr)["recall"] == 0.75


def test_reliability_bins_and_plots(tmp_path: Path) -> None:
    conf = np.linspace(0.05, 0.95, 50)
    ok = conf > 0.5
    b = cal.reliability_bins(conf, ok, n_bins=5)
    assert b.height == 5 and int(b["n"].sum()) == 50
    cal.plot_reliability(b, b, "t", tmp_path / "r.png")
    curve = cal.coverage_precision(conf, ok, np.linspace(0, 1, 11).tolist())
    cal.plot_coverage_precision(curve, 0.5, 0.95, "t", tmp_path / "c.png")
    assert (tmp_path / "r.png").stat().st_size > 0 and (tmp_path / "c.png").stat().st_size > 0


def test_thresholds_yaml_keeps_tau_and_gate_reads_it() -> None:
    from complaintiq.serving.gate import ConfidenceGate

    text = cal.render_thresholds_yaml(
        {"tau": 0.5, "target_precision": 0.95, "temperature_product": 1.2,
         "temperature_issue": 0.9, "priority_threshold": 0.3, "priority_target_recall": 0.85},
        "unit test",
    )
    data = yaml.safe_load(text)
    assert set(data) == {"tau", "temperature_product", "temperature_issue", "priority_threshold"}
    assert ConfidenceGate.from_config(data).tau == 0.5
    assert isinstance(pl.DataFrame({"a": [1]}), pl.DataFrame)
