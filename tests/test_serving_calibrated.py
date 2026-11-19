"""M4 serving: gate with tau from thresholds.yaml on calibrated confidence (synthetic model).

Mixes areas on purpose: serving (P4) loads a tiny P2 baseline and uses P3's temperature.
"""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from complaintiq.config import load_config
from complaintiq.models import baseline
from complaintiq.models.calibrate import apply_temperature
from complaintiq.serving.app import Services, app
from complaintiq.serving.gate import ConfidenceGate
from complaintiq.serving.predictor import calibration_kwargs, resolve_predictor
from complaintiq.serving.router import Router

TEXTS = [
    ("collector calls about a debt i do not owe", "Debt collection", "Attempts to collect", "HIGH"),
    ("servicer denied my mortgage modification", "Mortgage", "Struggling to pay", "NORMAL"),
    ("wrong account on my credit report", "Credit reporting", "Incorrect information", "NORMAL"),
    ("card charged twice for one purchase", "Credit card", "Problem with a purchase", "NORMAL"),
]
QUERY = "a debt collector keeps calling about a debt i do not owe and my credit report"


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
    model.meta["model_version"] = "baseline-tfidf_unit-dv1"
    d = tmp_path_factory.mktemp("m") / "bl"
    model.save(d)
    return d


def serving_cfg(d: Path) -> dict:
    return {"fallback_model_version": "stub", "baseline": {"model_dir": str(d)},
            "transformer": {"model_dir": str(d / "nope")}}


def test_repo_thresholds_feed_gate_and_predictor() -> None:
    th = load_config("thresholds")
    gate = ConfidenceGate.from_config(th)
    assert gate.tau == float(th["tau"])
    assert gate.decide(gate.tau) == "AUTO"
    assert gate.decide(np.nextafter(gate.tau, 0)) == "HUMAN_REVIEW"
    kw = calibration_kwargs(th)
    assert set(kw["temperatures"]) <= {"product", "issue"}
    assert kw["priority_threshold"] is None or 0 < kw["priority_threshold"] < 1


def test_calibration_kwargs_defaults_are_m3() -> None:
    assert calibration_kwargs({"tau": 0.8}) == {"temperatures": {}, "priority_threshold": None}


def test_predictor_confidence_is_temperature_scaled(model_dir: Path) -> None:
    th = {"tau": 0.5, "temperature_product": 3.0, "temperature_issue": 2.0,
          "priority_threshold": 0.9}
    pred, kind = resolve_predictor({"predictor": "baseline"}, serving_cfg(model_dir), th)
    raw, _ = resolve_predictor({"predictor": "baseline"}, serving_cfg(model_dir), {"tau": 0.5})
    assert kind == "baseline"
    m = baseline.BaselineModel.load(model_dir)
    _, p = m.scores("product", m.vectorizer.transform([QUERY]))
    expected = apply_temperature(p, 3.0).max()
    out, out_raw = pred.predict(QUERY), raw.predict(QUERY)
    assert out.product == out_raw.product
    assert out.product_confidence == pytest.approx(expected)
    assert out.product_confidence < out_raw.product_confidence  # T > 1 softens
    assert pred.priority_threshold == 0.9
    assert pred.model_version == "baseline-tfidf_unit-dv1-cal"
    assert raw.model_version == "baseline-tfidf_unit-dv1"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
    if hasattr(app.state, "services"):
        del app.state.services


def _services(model_dir: Path, th: dict) -> Services:
    pred, kind = resolve_predictor({"predictor": "baseline"}, serving_cfg(model_dir), th)
    return Services(predictor=pred, gate=ConfidenceGate.from_config(th),
                    router=Router.from_config(), feedback=__import__(
                        "complaintiq.serving.app", fromlist=["InMemoryFeedbackStore"]
                    ).InMemoryFeedbackStore(), predictor_name=kind, thresholds=th)


def test_gate_uses_calibrated_confidence_and_tau(model_dir: Path, client: TestClient) -> None:
    raw, _ = resolve_predictor({"predictor": "baseline"}, serving_cfg(model_dir), {})
    c_raw = raw.predict(QUERY).product_confidence
    soft = {"temperature_product": 5.0}
    c_cal, _ = resolve_predictor({"predictor": "baseline"}, serving_cfg(model_dir), soft)
    c_soft = c_cal.predict(QUERY).product_confidence
    tau = (c_raw + c_soft) / 2  # raw confidence passes, calibrated does not
    app.state.services = _services(model_dir, {"tau": tau})
    body = client.post("/v1/triage", json={"text": QUERY}).json()
    assert body["route"] == "AUTO"
    app.state.services = _services(model_dir, {"tau": tau, **soft})
    body = client.post("/v1/triage", json={"text": QUERY}).json()
    assert body["route"] == "HUMAN_REVIEW" and body["team"] == "Human Review Queue"
    assert body["model_version"].endswith("-cal")
    assert set(body) == {"request_id", "model_version", "product", "issue_top3", "priority",
                         "route", "team", "summary", "latency_ms"}
    info = client.get("/v1/model").json()
    assert info["thresholds"]["tau"] == pytest.approx(tau)
    assert info["thresholds"]["temperature_product"] == 5.0
