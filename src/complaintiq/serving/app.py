"""FastAPI app: /v1/triage, /v1/feedback, /health, /v1/model (SPEC C7).

Run with ``uvicorn complaintiq.serving.app:app``. Raw complaint text is never logged.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from complaintiq.config import load_config
from complaintiq.serving.gate import ConfidenceGate
from complaintiq.serving.predictor import Predictor, build_predictor
from complaintiq.serving.router import Router
from complaintiq.serving.schemas import (
    MAX_TEXT_CHARS,
    MIN_TEXT_CHARS,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    LabelProb,
    LabelScore,
    ModelInfoResponse,
    Priority,
    TriageRequest,
    TriageResponse,
)

logger = logging.getLogger("complaintiq.serving")


@dataclass
class InMemoryFeedbackStore:
    """Placeholder feedback store; replace with the request log (SQLite/Postgres)."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, feedback: FeedbackRequest) -> None:
        self.items.append(feedback.model_dump())


@dataclass
class Services:
    """Everything the endpoints need, built once at startup."""

    predictor: Predictor | None
    gate: ConfidenceGate
    router: Router
    feedback: InMemoryFeedbackStore
    predictor_name: str


def build_services() -> Services:
    """Load configs and construct predictor, gate, router and feedback store."""
    model_cfg = load_config("model")
    return Services(
        predictor=build_predictor(model_cfg),
        gate=ConfidenceGate.from_config(),
        router=Router.from_config(),
        feedback=InMemoryFeedbackStore(),
        predictor_name=str(model_cfg.get("predictor", "stub")),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build services at startup unless a test already injected them."""
    if not hasattr(app.state, "services"):
        app.state.services = build_services()
    yield


app = FastAPI(
    title="ComplaintIQ",
    version="0.1.0",
    lifespan=lifespan,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Generic 500 without stack traces in the response (SPEC C7)."""
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _services(request: Request) -> Services:
    return request.app.state.services


@app.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Liveness plus whether a model is loaded."""
    svc = _services(request)
    loaded = svc.predictor is not None
    return HealthResponse(
        status="ok" if loaded else "degraded",
        model_loaded=loaded,
        model_version=svc.predictor.model_version if loaded else "none",
    )


@app.get("/v1/model", response_model=ModelInfoResponse)
def model_info(request: Request) -> ModelInfoResponse:
    """Model version, predictor type and active thresholds."""
    svc = _services(request)
    return ModelInfoResponse(
        model_version=svc.predictor.model_version if svc.predictor else "none",
        predictor=svc.predictor_name,
        thresholds={"tau": svc.gate.tau},
    )


@app.post("/v1/triage", response_model=TriageResponse)
def triage(body: TriageRequest, request: Request) -> TriageResponse:
    """Classify a complaint, apply the confidence gate, and route it."""
    start = time.perf_counter()
    svc = _services(request)

    n_chars = len(body.text.strip())
    if not MIN_TEXT_CHARS <= n_chars <= MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"text must be {MIN_TEXT_CHARS}-{MAX_TEXT_CHARS} characters, got {n_chars}",
        )
    if svc.predictor is None:
        raise HTTPException(status_code=503, detail="Model unavailable")

    # TODO(M2/M5): PII scrub (FR2) and fallback predictor (C8) go here.
    pred = svc.predictor.predict(body.text)
    top_issue = pred.issue_top3[0][0] if pred.issue_top3 else ""

    route = svc.gate.decide(pred.product_confidence)
    if route == "AUTO":
        team = svc.router.route(pred.product, top_issue, pred.priority)
    else:
        team = svc.router.human_review_team

    request_id = body.request_id or uuid.uuid4().hex
    latency_ms = round((time.perf_counter() - start) * 1000)
    logger.info(
        "triage request_id=%s model=%s route=%s team=%s latency_ms=%d",
        request_id,
        svc.predictor.model_version,
        route,
        team,
        latency_ms,
    )
    return TriageResponse(
        request_id=request_id,
        model_version=svc.predictor.model_version,
        product=LabelScore(label=pred.product, confidence=pred.product_confidence),
        issue_top3=[LabelProb(label=lbl, p=p) for lbl, p in pred.issue_top3[:3]],
        priority=Priority(label=pred.priority, score=pred.priority_score),
        route=route,
        team=team,
        summary=None,  # summarization is a stretch goal
        latency_ms=latency_ms,
    )


@app.post("/v1/feedback", response_model=FeedbackResponse)
def feedback(body: FeedbackRequest, request: Request) -> FeedbackResponse:
    """Store an agent's correction linked to a request ID (US4)."""
    _services(request).feedback.add(body)
    return FeedbackResponse(request_id=body.request_id)
