"""API tests: schemas, error paths, gate wiring.

M5: the repo config now serves the baseline, so these tests select the stub with
COMPLAINTIQ_PREDICTOR=stub and keep the audit log in memory. The stub text is long enough
(>= 20 words) to pass the input quality check, so the gate decides the route.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from complaintiq.serving.app import app, build_services
from complaintiq.serving.gate import ConfidenceGate

VALID_TEXT = (
    "A debt collector keeps calling me about a debt I do not owe. I asked them to send "
    "written proof of the debt and they never did, but the calls continue every day."
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("COMPLAINTIQ_PREDICTOR", "stub")
    monkeypatch.setenv("COMPLAINTIQ_REQUEST_LOG", ":memory:")
    app.state.services = build_services()
    with TestClient(app) as c:
        yield c
    del app.state.services


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_model_info(client: TestClient) -> None:
    body = client.get("/v1/model").json()
    assert body["predictor"] == "stub"
    assert "tau" in body["thresholds"]


def test_triage_auto_route(client: TestClient) -> None:
    r = client.post("/v1/triage", json={"text": VALID_TEXT, "request_id": "abc"})
    assert r.status_code == 200
    body = r.json()
    assert body["request_id"] == "abc"
    assert body["route"] == "AUTO"
    assert body["team"] == "Collections Compliance"
    assert len(body["issue_top3"]) == 3
    assert body["summary"] is None
    assert body["reason"] is None


def test_triage_low_confidence_goes_to_human(client: TestClient) -> None:
    app.state.services.gate = ConfidenceGate(tau=0.99)
    body = client.post("/v1/triage", json={"text": VALID_TEXT}).json()
    assert body["route"] == "HUMAN_REVIEW"
    assert body["team"] == "Human Review Queue"
    assert body["reason"] == "low_confidence"


@pytest.mark.parametrize("text", ["too short", "x" * 10_001])
def test_triage_length_out_of_range_is_400(client: TestClient, text: str) -> None:
    assert client.post("/v1/triage", json={"text": text}).status_code == 400


def test_triage_schema_error_is_422(client: TestClient) -> None:
    assert client.post("/v1/triage", json={}).status_code == 422


def test_triage_without_model_is_503(client: TestClient) -> None:
    app.state.services.predictor = None
    assert client.post("/v1/triage", json={"text": VALID_TEXT}).status_code == 503


def test_feedback_accepted(client: TestClient) -> None:
    client.post("/v1/triage", json={"text": VALID_TEXT, "request_id": "abc"})
    r = client.post("/v1/feedback", json={"request_id": "abc", "product": "Mortgage"})
    assert r.status_code == 200
    assert r.json() == {"request_id": "abc", "status": "accepted"}
    stats = app.state.services.request_log.correction_rate()
    assert stats["requests_with_feedback"] == 1 and stats["corrected"] == 1


def test_feedback_requires_a_correction(client: TestClient) -> None:
    assert client.post("/v1/feedback", json={"request_id": "abc"}).status_code == 422
