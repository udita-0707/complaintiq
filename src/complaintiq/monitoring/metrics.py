"""Prometheus metrics for the API (SPEC B4 FR6, B3 US6, C9; M5).

One :class:`Metrics` per running app, with its own registry (tests build fresh ones).
``GET /metrics`` serves :meth:`Metrics.render` in the Prometheus text format. Labels are
bounded: endpoint names come from a fixed list, product labels from the model's classes.
Nothing here ever sees complaint text.

=====================================  ================================================
metric                                 meaning
=====================================  ================================================
ciq_requests_total{endpoint,status}    HTTP requests (all endpoints, incl. 4xx/5xx)
ciq_errors_total{endpoint}             responses with status >= 500
ciq_request_latency_seconds{endpoint}  latency histogram (server side)
ciq_triage_route_total{route,reason}   AUTO vs HUMAN_REVIEW (fallback rate) and why
ciq_predicted_product_total{product}   predicted class distribution
ciq_product_confidence                 calibrated product confidence histogram
ciq_pii_redactions_total               spans scrubbed before inference (FR2)
ciq_pii_residual_total                 pattern hits left after scrubbing (C8 alert)
ciq_inference_timeouts_total           predictions slower than the timeout (C8)
ciq_fallback_predictions_total         answers from the runtime fallback model (C8)
ciq_model_errors_total                 predictions that failed with no fallback (503)
ciq_rate_limited_total                 429 responses (C10)
ciq_feedback_total{known_request}      corrections received (US4)
ciq_request_log_buffer_rows            audit rows waiting while the store is down
ciq_request_log_write_errors           failed audit writes since start
ciq_request_log_dropped_rows           audit rows lost because the buffer was full
ciq_model_info{model_version,predictor} 1 for the model in use
process_*                              process memory/CPU (Linux process collector)
=====================================  ================================================
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ProcessCollector,
    generate_latest,
)

ENDPOINTS = frozenset({"/v1/triage", "/v1/feedback", "/health", "/v1/model", "/metrics"})
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.3, 0.5, 1.0, 2.0, 5.0)
CONFIDENCE_BUCKETS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0)


def endpoint_label(path: str) -> str:
    """Bounded endpoint label: known paths as-is, everything else ``other``."""
    return path if path in ENDPOINTS else "other"


class Metrics:
    """All API metrics in one registry."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        ProcessCollector(registry=r)
        self.requests = Counter("ciq_requests_total", "HTTP requests by endpoint and status",
                                ["endpoint", "status"], registry=r)
        self.errors = Counter("ciq_errors_total", "Responses with status >= 500",
                              ["endpoint"], registry=r)
        self.latency = Histogram("ciq_request_latency_seconds", "Server-side request latency",
                                 ["endpoint"], buckets=LATENCY_BUCKETS, registry=r)
        self.routes = Counter("ciq_triage_route_total", "Triage routes and reasons",
                              ["route", "reason"], registry=r)
        self.products = Counter("ciq_predicted_product_total", "Predicted product class",
                                ["product"], registry=r)
        self.confidence = Histogram("ciq_product_confidence", "Calibrated product confidence",
                                    buckets=CONFIDENCE_BUCKETS, registry=r)
        self.pii_redactions = Counter("ciq_pii_redactions_total",
                                      "PII spans scrubbed before inference", registry=r)
        self.pii_residual = Counter("ciq_pii_residual_total",
                                    "PII pattern hits left after scrubbing", registry=r)
        self.timeouts = Counter("ciq_inference_timeouts_total", "Inference timeouts",
                                registry=r)
        self.fallbacks = Counter("ciq_fallback_predictions_total",
                                 "Predictions served by the runtime fallback", registry=r)
        self.model_errors = Counter("ciq_model_errors_total",
                                    "Failed predictions with no fallback", registry=r)
        self.rate_limited = Counter("ciq_rate_limited_total", "Requests answered 429",
                                    registry=r)
        self.feedback = Counter("ciq_feedback_total", "Corrections received",
                                ["known_request"], registry=r)
        self.log_buffer = Gauge("ciq_request_log_buffer_rows",
                                "Audit rows waiting to be written", registry=r)
        self.log_errors = Gauge("ciq_request_log_write_errors",
                                "Failed audit writes since start", registry=r)
        self.log_dropped = Gauge("ciq_request_log_dropped_rows",
                                 "Audit rows dropped (buffer full)", registry=r)
        self.model_info = Gauge("ciq_model_info", "Model in use (value 1)",
                                ["model_version", "predictor"], registry=r)

    def set_model(self, model_version: str, predictor: str) -> None:
        """Expose the model in use as ``ciq_model_info{...} 1``."""
        self.model_info.labels(model_version=model_version, predictor=predictor).set(1)

    def watch_request_log(self, log: Any) -> None:
        """Read the audit-log counters at scrape time."""
        self.log_buffer.set_function(lambda: float(log.buffer_size))
        self.log_errors.set_function(lambda: float(log.write_errors))
        self.log_dropped.set_function(lambda: float(log.dropped))

    def observe_request(self, endpoint: str, status: int, seconds: float) -> None:
        self.requests.labels(endpoint=endpoint, status=str(status)).inc()
        self.latency.labels(endpoint=endpoint).observe(seconds)
        if status >= 500:
            self.errors.labels(endpoint=endpoint).inc()

    def observe_triage(self, route: str, reason: str | None, product: str | None,
                       confidence: float | None) -> None:
        self.routes.labels(route=route, reason=reason or "none").inc()
        if product is not None:
            self.products.labels(product=product).inc()
        if confidence is not None:
            self.confidence.observe(confidence)

    def render(self) -> tuple[bytes, str]:
        """Prometheus text exposition and its content type."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


class MetricsMiddleware:
    """Pure ASGI middleware: count and time every HTTP request (status incl. 4xx/5xx).

    ``get_metrics(scope)`` returns the app's :class:`Metrics` or ``None`` to skip.
    """

    def __init__(self, app: Any, get_metrics: Callable[[dict[str, Any]], Metrics | None]) -> None:
        self.app = app
        self.get_metrics = get_metrics

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        metrics = self.get_metrics(scope)
        if metrics is None:
            await self.app(scope, receive, send)
            return
        status = {"code": 500}
        start = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            metrics.observe_request(endpoint_label(scope.get("path", "")), status["code"],
                                    time.perf_counter() - start)
