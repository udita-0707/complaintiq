"""FastAPI app: /v1/triage, /v1/feedback, /health, /v1/model, /metrics (SPEC C7).

Run with ``uvicorn complaintiq.serving.app:app``. Raw complaint text is never logged or
stored: the PII scrub runs first (FR2) and only the scrubbed text reaches the model; the
audit log keeps a hash of it.

/v1/triage pipeline (M5):

1. FR1 length check on the raw text (400);
2. PII scrub with counts (P3, ``privacy.pii``) -> metrics;
3. input quality heuristic (P3, ``serving.input_quality``) on the scrubbed text;
4. guarded inference (``serving.runtime``): timeout -> HUMAN_REVIEW ``timeout``; failure ->
   runtime fallback, else 503;
5. confidence gate (tau) and router; a failed quality check forces HUMAN_REVIEW;
6. audit row (P3, ``serving.request_log``; buffered if the store is down) and metrics.

Middlewares, outermost first: metrics, CORS (only if origins are configured), rate limit
(P3), body size limit (P3). Security settings are read at import from
``configs/safety.yaml``; restart the API to change them.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from complaintiq.config import load_config
from complaintiq.monitoring.metrics import Metrics, MetricsMiddleware
from complaintiq.privacy.pii import scrub_with_counts
from complaintiq.serving.gate import ConfidenceGate
from complaintiq.serving.input_quality import assess
from complaintiq.serving.predictor import (
    Prediction,
    Predictor,
    configured_kind,
    resolve_predictor,
    resolve_runtime_fallback,
)
from complaintiq.serving.request_log import RequestLog, RequestRow, text_hash
from complaintiq.serving.router import Router
from complaintiq.serving.runtime import GuardedPredictor, Outcome, TestHooks
from complaintiq.serving.schemas import (
    MAX_TEXT_CHARS,
    MIN_TEXT_CHARS,
    UNAVAILABLE_LABEL,
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
from complaintiq.serving.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    TokenBucketLimiter,
    cors_origins,
)

logger = logging.getLogger("complaintiq.serving")


@dataclass
class InMemoryFeedbackStore:
    """Feedback store used when no request log is configured (tests, disabled log)."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, feedback: FeedbackRequest) -> None:
        self.items.append(feedback.model_dump())


@dataclass
class Services:
    """Everything the endpoints need, built once at startup.

    The M5 fields have defaults so tests can inject a minimal ``Services`` (M3/M4 style):
    without ``guard`` the predictor is called directly, without ``request_log`` feedback goes
    to the in-memory store, and without ``metrics`` nothing is counted.
    """

    predictor: Predictor | None
    gate: ConfidenceGate
    router: Router
    feedback: InMemoryFeedbackStore
    predictor_name: str
    thresholds: dict[str, float] = field(default_factory=dict)
    guard: GuardedPredictor | None = None
    request_log: RequestLog | None = None
    metrics: Metrics | None = None
    rate_limiter: TokenBucketLimiter | None = None
    quality_cfg: dict[str, Any] = field(default_factory=dict)
    scrub: bool = True


def build_services() -> Services:
    """Load configs and construct predictor chain, gate, router, audit log and metrics.

    ``configs/thresholds.yaml`` is read once: ``tau`` for the gate, and (M4) the
    temperatures and priority threshold for the baseline predictor, so the gate compares
    tau with calibrated confidence.
    """
    thresholds = load_config("thresholds")
    serving = load_config("serving")
    safety = load_config("safety")
    model_cfg = {**load_config("model")}
    model_cfg["predictor"] = configured_kind(model_cfg)
    predictor, predictor_name = resolve_predictor(model_cfg, serving, thresholds)
    guard = None
    if predictor is not None:
        guard = GuardedPredictor(
            predictor,
            fallback=resolve_runtime_fallback(predictor_name, serving, thresholds),
            timeout_s=float(serving.get("inference_timeout_s", 2.0)),
            workers=int(serving.get("inference_workers", 4)),
            hooks=TestHooks.from_env(),
        )
    request_log = RequestLog.from_config()
    metrics = Metrics()
    metrics.set_model(predictor.model_version if predictor else "none", predictor_name)
    if request_log is not None:
        metrics.watch_request_log(request_log)
    return Services(
        predictor=predictor,
        gate=ConfidenceGate.from_config(thresholds),
        router=Router.from_config(),
        feedback=InMemoryFeedbackStore(),
        predictor_name=predictor_name,
        thresholds={k: float(v) for k, v in thresholds.items() if isinstance(v, int | float)},
        guard=guard,
        request_log=request_log,
        metrics=metrics,
        rate_limiter=TokenBucketLimiter.from_config(safety["security"].get("rate_limit", {})),
        quality_cfg=safety.get("input_quality", {}),
        scrub=bool(safety.get("pii", {}).get("scrub_before_inference", True)),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build services at startup unless a test already injected them; clean up at exit."""
    if not hasattr(app.state, "services"):
        app.state.services = build_services()
    yield
    svc = getattr(app.state, "services", None)
    if svc is not None:
        if svc.guard is not None:
            svc.guard.shutdown()
        if svc.request_log is not None:
            svc.request_log.close()


def _state_services(scope: dict[str, Any]) -> Services | None:
    app_ = scope.get("app")
    return getattr(getattr(app_, "state", None), "services", None)


def _limiter(scope: dict[str, Any]) -> TokenBucketLimiter | None:
    svc = _state_services(scope)
    return svc.rate_limiter if svc is not None else None


def _metrics(scope: dict[str, Any]) -> Metrics | None:
    svc = _state_services(scope)
    return svc.metrics if svc is not None else None


def _count_rate_limited(scope: dict[str, Any]) -> None:
    m = _metrics(scope)
    if m is not None:
        m.rate_limited.inc()


app = FastAPI(
    title="ComplaintIQ",
    version="0.1.0",
    lifespan=lifespan,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)

_SECURITY = load_config("safety").get("security", {})
_RATE = _SECURITY.get("rate_limit", {}) or {}
# add_middleware wraps: the last one added is the outermost.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=int(_SECURITY.get("max_body_bytes",
                                                                         131072)))
app.add_middleware(
    RateLimitMiddleware,
    get_limiter=_limiter,
    paths=_RATE.get("paths", ["/v1/triage", "/v1/feedback"]),
    bypass_token_env=_RATE.get("bypass_token_env"),
    on_limited=_count_rate_limited,
)
if cors_origins(_SECURITY):
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(_SECURITY),
                       allow_methods=["GET", "POST"], allow_headers=["content-type"])
app.add_middleware(MetricsMiddleware, get_metrics=_metrics)


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
        thresholds={**svc.thresholds, "tau": svc.gate.tau},
    )


@app.get("/metrics", include_in_schema=True)
def metrics(request: Request) -> Response:
    """Prometheus metrics (FR6, US6)."""
    m = _services(request).metrics
    if m is None:
        raise HTTPException(status_code=503, detail="Metrics unavailable")
    body, content_type = m.render()
    return Response(content=body, media_type=content_type)


def _predict(svc: Services, text: str) -> Outcome:
    if svc.guard is not None:
        return svc.guard.predict(text)
    assert svc.predictor is not None
    return Outcome(svc.predictor.predict(text), svc.predictor.model_version, "ok")


@app.post("/v1/triage", response_model=TriageResponse)
def triage(body: TriageRequest, request: Request) -> TriageResponse:
    """Scrub, check, classify, gate and route a complaint; audit the decision."""
    start = time.perf_counter()
    svc = _services(request)
    m = svc.metrics

    n_chars = len(body.text.strip())
    if not MIN_TEXT_CHARS <= n_chars <= MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"text must be {MIN_TEXT_CHARS}-{MAX_TEXT_CHARS} characters, got {n_chars}",
        )
    if svc.predictor is None:
        raise HTTPException(status_code=503, detail="Model unavailable")

    # FR2: everything after this line sees only the scrubbed text.
    scrubbed = scrub_with_counts(body.text) if svc.scrub else None
    text = scrubbed.text if scrubbed is not None else body.text
    if m is not None and scrubbed is not None:
        m.pii_redactions.inc(scrubbed.redactions)
        if scrubbed.residual:
            m.pii_residual.inc(scrubbed.residual)
    quality = assess(text, svc.quality_cfg) if svc.quality_cfg else None

    outcome = _predict(svc, text)
    if outcome.status == "error":
        if m is not None:
            m.model_errors.inc()
        raise HTTPException(status_code=503, detail="Model unavailable")
    if m is not None and outcome.status == "fallback":
        m.fallbacks.inc()

    pred: Prediction | None = outcome.prediction
    if pred is None:  # timeout
        if m is not None:
            m.timeouts.inc()
        route, reason, team = "HUMAN_REVIEW", "timeout", svc.router.human_review_team
        product = LabelScore(label=UNAVAILABLE_LABEL, confidence=0.0)
        issues: list[LabelProb] = []
        priority = Priority(label="NORMAL", score=0.0)
    else:
        top_issue = pred.issue_top3[0][0] if pred.issue_top3 else ""
        route = svc.gate.decide(pred.product_confidence)
        reason = None if route == "AUTO" else "low_confidence"
        if quality is not None and not quality.ok:
            route, reason = "HUMAN_REVIEW", quality.reason
        team = (svc.router.route(pred.product, top_issue, pred.priority) if route == "AUTO"
                else svc.router.human_review_team)
        product = LabelScore(label=pred.product, confidence=pred.product_confidence)
        issues = [LabelProb(label=lbl, p=p) for lbl, p in pred.issue_top3[:3]]
        priority = Priority(label=pred.priority, score=pred.priority_score)

    request_id = body.request_id or uuid.uuid4().hex
    latency_ms = round((time.perf_counter() - start) * 1000)
    logger.info(
        "triage request_id=%s model=%s route=%s reason=%s team=%s latency_ms=%d",
        request_id, outcome.model_version, route, reason or "-", team, latency_ms,
    )
    if svc.request_log is not None:
        try:
            svc.request_log.record_request(RequestRow(
                request_id=request_id,
                text_hash=text_hash(text, svc.request_log.salt),
                n_chars=n_chars,
                model_version=outcome.model_version,
                predictor=svc.predictor_name,
                product=product.label if pred is not None else None,
                product_conf=product.confidence if pred is not None else None,
                issue=issues[0].label if issues else None,
                issue_p=issues[0].p if issues else None,
                priority=priority.label if pred is not None else None,
                priority_score=priority.score if pred is not None else None,
                route=route,
                team=team,
                reason=reason,
                latency_ms=latency_ms,
                pii_redactions=scrubbed.redactions if scrubbed is not None else 0,
                pii_residual=scrubbed.residual if scrubbed is not None else 0,
            ))
        except Exception as exc:  # the audit log must never break a response
            logger.warning("request log error (%s)", type(exc).__name__)
    if m is not None:
        m.observe_triage(route, reason, product.label if pred is not None else None,
                         product.confidence if pred is not None else None)
    return TriageResponse(
        request_id=request_id,
        model_version=outcome.model_version,
        product=product,
        issue_top3=issues,
        priority=priority,
        route=route,
        team=team,
        summary=None,  # summarization is a stretch goal
        latency_ms=latency_ms,
        reason=reason,
    )


@app.post("/v1/feedback", response_model=FeedbackResponse)
def feedback(body: FeedbackRequest, request: Request) -> FeedbackResponse:
    """Store an agent's correction linked to a request ID (US4).

    Unknown request IDs are stored and flagged (``known_request = 0``), not rejected: the
    free-tier log restarts empty, so a valid correction must not be lost.
    """
    svc = _services(request)
    if svc.request_log is not None:
        row = svc.request_log.record_feedback(
            body.request_id,
            {"product": body.product, "issue": body.issue, "priority": body.priority,
             "team": body.team},
        )
        known = "unknown" if row.known_request is None else str(row.known_request).lower()
    else:
        svc.feedback.add(body)
        known = "unknown"
    if svc.metrics is not None:
        svc.metrics.feedback.labels(known_request=known).inc()
    return FeedbackResponse(request_id=body.request_id)
