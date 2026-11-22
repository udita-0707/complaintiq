"""M5 runtime through the wired API (synthetic predictors and data only).

Mixes areas on purpose (flagged in docs/COMMIT_PLAN_M5.md): P4's app wiring, fallback,
timeout and /metrics exercise P3's scrub, quality check, rate limit and request log.
"""

import logging
import sqlite3
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from complaintiq.config import load_config
from complaintiq.models import baseline
from complaintiq.monitoring.metrics import Metrics
from complaintiq.serving import predictor as pr
from complaintiq.serving.app import InMemoryFeedbackStore, Services, app, build_services
from complaintiq.serving.gate import ConfidenceGate
from complaintiq.serving.predictor import Prediction, StubPredictor
from complaintiq.serving.request_log import RequestLog
from complaintiq.serving.router import Router
from complaintiq.serving.runtime import GuardedPredictor, TestHooks
from complaintiq.serving.security import TokenBucketLimiter

LONG_TEXT = (
    "A debt collector keeps calling me about a debt I do not owe. I asked them to send "
    "written proof of the debt and they never did, but the calls continue every day."
)
# Synthetic PII (reserved/test values) that must never reach a log, the store or the model.
PII = ["jane.doe@example.com", "(555) 010-4477", "078-05-1120", "4111 1111 1111 1111"]
PII_TEXT = LONG_TEXT + " Reach me at " + ", ".join(PII) + "."
SPANISH = ("Me están cobrando una deuda que no debo y llaman todos los días a mi trabajo, ya "
           "les dije que no es mía y siguen llamando sin parar por favor ayuda")


class SpyPredictor:
    """Records the text it receives; fixed confident prediction."""

    def __init__(self, delay_s: float = 0.0, fail: bool = False,
                 version: str = "spy-1") -> None:
        self.seen: list[str] = []
        self.delay_s, self.fail, self._v = delay_s, fail, version

    @property
    def model_version(self) -> str:
        return self._v

    def predict(self, text: str) -> Prediction:
        self.seen.append(text)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("boom")
        return Prediction("Debt collection", 0.97, [("Attempts to collect debt not owed", 0.8),
                                                     ("Communication tactics", 0.1)],
                          "NORMAL", 0.1)


def services(primary, *, fallback=None, timeout_s: float = 2.0, log: RequestLog | None = None,
             limiter: TokenBucketLimiter | None = None) -> Services:
    m = Metrics()
    m.set_model(primary.model_version, "spy")
    if log is not None:
        m.watch_request_log(log)
    return Services(
        predictor=primary, gate=ConfidenceGate(tau=0.8), router=Router.from_config(),
        feedback=InMemoryFeedbackStore(), predictor_name="spy", thresholds={"tau": 0.8},
        guard=GuardedPredictor(primary, fallback=fallback, timeout_s=timeout_s),
        request_log=log if log is not None else RequestLog(":memory:"), metrics=m,
        rate_limiter=limiter, quality_cfg=load_config("safety")["input_quality"],
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
    if hasattr(app.state, "services"):
        del app.state.services


def metric(client: TestClient, name: str) -> float:
    """Sum of all samples of ``name`` in /metrics (0 if absent)."""
    total = 0.0
    for line in client.get("/metrics").text.splitlines():
        if line.startswith(name + " ") or line.startswith(name + "{"):
            total += float(line.rsplit(" ", 1)[1])
    return total


def test_pii_is_scrubbed_before_the_model_and_never_logged_or_stored(
        client: TestClient, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    spy = SpyPredictor()
    db = tmp_path / "req.sqlite"
    app.state.services = services(spy, log=RequestLog(db))
    with caplog.at_level(logging.DEBUG):
        r = client.post("/v1/triage", json={"text": PII_TEXT, "request_id": "pii-1"})
    assert r.status_code == 200
    assert len(spy.seen) == 1
    dump = "\n".join(sqlite3.connect(db).iterdump())
    for secret in PII:
        assert secret not in spy.seen[0]
        assert secret not in caplog.text
        assert secret not in r.text
        assert secret not in dump
    assert "[REDACTED]" in spy.seen[0]
    assert LONG_TEXT[:40] not in dump  # no text at all in the store
    assert metric(client, "ciq_pii_redactions_total") == 4
    assert metric(client, "ciq_pii_residual_total") == 0


def test_quality_failure_forces_human_review_even_when_confident(client: TestClient) -> None:
    app.state.services = services(SpyPredictor())
    body = client.post("/v1/triage", json={"text": SPANISH}).json()
    assert (body["route"], body["reason"], body["team"]) == (
        "HUMAN_REVIEW", "non_english", "Human Review Queue")
    assert body["product"]["label"] == "Debt collection"  # still scored, for the reviewer
    body = client.post("/v1/triage", json={"text": "My bank charged me a fee twice."}).json()
    assert body["reason"] == "short_text"
    body = client.post("/v1/triage", json={"text": LONG_TEXT}).json()
    assert (body["route"], body["reason"]) == ("AUTO", None)
    assert body["team"] == "Collections Compliance"
    assert metric(client, 'ciq_triage_route_total{reason="non_english",route="HUMAN_REVIEW"}') \
        == 1


def test_timeout_returns_human_review_without_prediction(client: TestClient) -> None:
    app.state.services = services(SpyPredictor(delay_s=0.5), timeout_s=0.05)
    r = client.post("/v1/triage", json={"text": LONG_TEXT})
    assert r.status_code == 200
    body = r.json()
    assert (body["route"], body["reason"], body["team"]) == (
        "HUMAN_REVIEW", "timeout", "Human Review Queue")
    assert body["product"] == {"label": "UNAVAILABLE", "confidence": 0.0}
    assert body["issue_top3"] == []
    assert metric(client, "ciq_inference_timeouts_total") == 1
    stats = app.state.services.request_log.correction_rate()
    assert stats["routes"] == {"HUMAN_REVIEW": 1}


def test_runtime_fallback_and_503_without_one(client: TestClient) -> None:
    fb = pr.FlaggedPredictor(StubPredictor("baseline-x"))
    app.state.services = services(SpyPredictor(fail=True), fallback=fb)
    body = client.post("/v1/triage", json={"text": LONG_TEXT}).json()
    assert body["model_version"] == "baseline-x-fallback"
    assert metric(client, "ciq_fallback_predictions_total") == 1
    app.state.services = services(SpyPredictor(fail=True))
    r = client.post("/v1/triage", json={"text": LONG_TEXT})
    assert r.status_code == 503 and r.json() == {"detail": "Model unavailable"}
    assert metric(client, "ciq_model_errors_total") == 1
    assert metric(client, 'ciq_errors_total{endpoint="/v1/triage"}') == 1


def test_metrics_endpoint_format_and_counts(client: TestClient) -> None:
    app.state.services = services(SpyPredictor())
    client.post("/v1/triage", json={"text": LONG_TEXT})
    client.post("/v1/triage", json={"text": "too short"})  # 400
    r = client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert 'ciq_model_info{model_version="spy-1",predictor="spy"} 1.0' in r.text
    assert metric(client, 'ciq_requests_total{endpoint="/v1/triage",status="200"}') == 1
    assert metric(client, 'ciq_requests_total{endpoint="/v1/triage",status="400"}') == 1
    assert metric(client, 'ciq_predicted_product_total{product="Debt collection"}') == 1
    assert metric(client, "ciq_product_confidence_count") == 1
    if sys.platform.startswith("linux"):  # the process collector reads /proc
        assert "process_resident_memory_bytes" in r.text


def test_feedback_links_to_request_and_flags_unknown_ids(client: TestClient) -> None:
    app.state.services = services(SpyPredictor())
    client.post("/v1/triage", json={"text": LONG_TEXT, "request_id": "r-1"})
    assert client.post("/v1/feedback", json={"request_id": "r-1", "issue": "Fees or interest"}
                       ).status_code == 200
    assert client.post("/v1/feedback", json={"request_id": "ghost", "product": "Mortgage"}
                       ).json() == {"request_id": "ghost", "status": "accepted"}
    stats = app.state.services.request_log.correction_rate()
    assert stats["corrected"] == 1 and stats["feedback_unknown_request"] == 1
    assert metric(client, 'ciq_feedback_total{known_request="true"}') == 1
    assert metric(client, 'ciq_feedback_total{known_request="false"}') == 1


def test_rate_limit_429_is_counted(client: TestClient) -> None:
    app.state.services = services(SpyPredictor(),
                                  limiter=TokenBucketLimiter(requests_per_minute=1, burst=2))
    codes = [client.post("/v1/triage", json={"text": LONG_TEXT}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.get("/health").status_code == 200  # not limited
    assert metric(client, "ciq_rate_limited_total") == 1
    assert metric(client, 'ciq_requests_total{endpoint="/v1/triage",status="429"}') == 1


def test_oversized_body_is_413(client: TestClient) -> None:
    app.state.services = services(SpyPredictor())
    limit = int(load_config("safety")["security"]["max_body_bytes"])
    r = client.post("/v1/triage", content=b'{"text": "' + b"a" * limit + b'"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_store_down_still_answers_and_reports_buffer(client: TestClient) -> None:
    def broken(path: str) -> sqlite3.Connection:
        raise sqlite3.OperationalError("unable to open database file")

    app.state.services = services(SpyPredictor(), log=RequestLog("x.sqlite", connect=broken))
    assert client.post("/v1/triage", json={"text": LONG_TEXT}).status_code == 200
    assert client.post("/v1/triage", json={"text": LONG_TEXT}).status_code == 200
    assert metric(client, "ciq_request_log_buffer_rows") == 2
    assert metric(client, "ciq_request_log_write_errors") == 2


# ------------------------------------------------------------------ load-time chain


@pytest.fixture(scope="module")
def tiny_model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    texts, labels = [], {"product": [], "issue": [], "priority": []}
    for text, prod, issue, prio in [
        ("collector calls about a debt i do not owe", "Debt collection", "Attempts", "HIGH"),
        ("servicer denied my mortgage modification", "Mortgage", "Struggling", "NORMAL"),
    ]:
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
    d = tmp_path_factory.mktemp("m5") / "bl"
    model.save(d)
    return d


def test_chain_transformer_to_baseline_and_no_stub_when_disabled(tiny_model_dir: Path,
                                                                 tmp_path: Path) -> None:
    serving = {"fallback_model_version": "stub", "allow_stub_fallback": False,
               "baseline": {"model_dir": str(tiny_model_dir)},
               "transformer": {"model_dir": str(tmp_path / "missing")}}
    pred, kind = pr.resolve_predictor({"predictor": "transformer"}, serving, {"tau": 0.8})
    assert kind == "baseline" and pred.model_version == "baseline-unit-fallback"
    assert pred.predict("a collector keeps calling about a debt").product == "Debt collection"
    gone = {**serving, "baseline": {"model_dir": str(tmp_path / "missing")}}
    assert pr.resolve_predictor({"predictor": "baseline"}, gone, {"tau": 0.8}) == (None, "none")
    assert pr.resolve_runtime_fallback("baseline", serving, {}) is None
    rt = pr.resolve_runtime_fallback("transformer", serving, {"tau": 0.8})
    assert rt is not None and rt.model_version == "baseline-unit-fallback"


def test_env_overrides_kind_root_and_hooks(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    monkeypatch.setenv(pr.PREDICTOR_ENV, "stub")
    assert pr.configured_kind({"predictor": "baseline"}) == "stub"
    monkeypatch.setenv("COMPLAINTIQ_ROOT", str(tmp_path))
    assert pr.resolve("models/x") == tmp_path / "models" / "x"
    monkeypatch.delenv("COMPLAINTIQ_ENABLE_TEST_HOOKS", raising=False)
    monkeypatch.setenv("COMPLAINTIQ_TEST_DELAY_S", "3")
    assert not TestHooks.from_env().active  # ignored unless the flag is set
    monkeypatch.setenv("COMPLAINTIQ_ENABLE_TEST_HOOKS", "1")
    monkeypatch.setenv("COMPLAINTIQ_TEST_FAIL_PRIMARY", "1")
    hooks = TestHooks.from_env()
    assert hooks.delay_s == 3.0 and hooks.fail_primary


def test_repo_config_without_model_is_degraded_not_stub(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    monkeypatch.delenv(pr.PREDICTOR_ENV, raising=False)
    monkeypatch.setenv("COMPLAINTIQ_ROOT", str(tmp_path))  # no models/ here
    monkeypatch.setenv("COMPLAINTIQ_REQUEST_LOG", ":memory:")
    svc = build_services()
    assert svc.predictor is None and svc.predictor_name == "none"
    app.state.services = svc
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "degraded", "model_loaded": False,
                                           "model_version": "none"}
        assert c.post("/v1/triage", json={"text": LONG_TEXT}).status_code == 503
    del app.state.services
