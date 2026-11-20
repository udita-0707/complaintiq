"""Config-driven predictor selection: baseline loading and stub fallback.

Mixes areas on purpose: serving (P4) loading a baseline (P2) fitted on synthetic text here.
"""

import logging
from pathlib import Path

import pytest

from complaintiq.models import baseline
from complaintiq.serving.predictor import (
    Predictor,
    StubPredictor,
    build_predictor,
    resolve_predictor,
)

TEXTS = [
    ("collector calls about a debt i do not owe", "Debt collection", "Attempts to collect", "HIGH"),
    ("servicer denied my mortgage modification", "Mortgage", "Struggling to pay", "NORMAL"),
    ("wrong account on my credit report", "Credit reporting", "Incorrect information", "NORMAL"),
    ("card charged twice for one purchase", "Credit card", "Problem with a purchase", "NORMAL"),
]


@pytest.fixture
def tiny_model_dir(tmp_path: Path) -> Path:
    texts, labels = [], {"product": [], "issue": [], "priority": []}
    for text, prod, issue, prio in TEXTS:
        for i in range(10):
            texts.append(f"{text} number {i}")
            labels["product"].append(prod)
            labels["issue"].append(issue)
            labels["priority"].append(prio)
    cfg = baseline.load_baseline_config()
    params = baseline.variant_params(cfg, cfg["default_variant"])
    params["features"].update(min_df=1, max_df=1.0)
    model = baseline.fit_model(texts, labels, params)
    model.meta["model_version"] = "baseline-unit"
    model.save(tmp_path / "bl")
    return tmp_path / "bl"


def serving_cfg(model_dir: Path) -> dict:
    return {
        "fallback_model_version": "stub",
        "baseline": {"model_dir": str(model_dir)},
        "transformer": {"model_dir": str(model_dir / "nope")},
    }


def test_baseline_loaded_through_config(tiny_model_dir: Path) -> None:
    pred, kind = resolve_predictor({"predictor": "baseline"}, serving_cfg(tiny_model_dir))
    assert kind == "baseline"
    assert isinstance(pred, Predictor)
    assert pred.model_version == "baseline-unit"
    out = pred.predict("a debt collector keeps calling about a debt i do not owe")
    assert out.product == "Debt collection"
    assert len(out.issue_top3) == 3
    assert out.priority in {"HIGH", "NORMAL"}


@pytest.mark.parametrize("kind", ["baseline", "transformer"])
def test_missing_artifact_falls_back_to_stub(
    tmp_path: Path, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="complaintiq.serving"):
        pred, used = resolve_predictor({"predictor": kind}, serving_cfg(tmp_path / "missing"))
    assert used == "stub"
    assert isinstance(pred, StubPredictor)
    assert pred.model_version == "stub"
    assert "falling back to the stub" in caplog.text


def test_stub_and_unknown() -> None:
    assert build_predictor({"predictor": "stub", "model_version": "s-1"}).model_version == "s-1"
    with pytest.raises(ValueError):
        build_predictor({"predictor": "bogus"})
