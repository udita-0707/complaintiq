"""Pydantic request/response schemas for the API (SPEC C7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 10_000

PriorityLabel = Literal["HIGH", "NORMAL"]
RouteLabel = Literal["AUTO", "HUMAN_REVIEW"]


class TriageRequest(BaseModel):
    """Body of ``POST /v1/triage``.

    Text length (20-10,000 chars) is checked in the endpoint so that violations
    return 400 as the spec requires, rather than Pydantic's 422.
    """

    text: str
    request_id: str | None = Field(default=None, max_length=128)
    include_summary: bool = False


class LabelScore(BaseModel):
    """Top-1 label with its calibrated confidence."""

    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class LabelProb(BaseModel):
    """One entry of a top-k list."""

    label: str
    p: float = Field(ge=0.0, le=1.0)


class Priority(BaseModel):
    """Priority flag and score for the HIGH class."""

    label: PriorityLabel
    score: float = Field(ge=0.0, le=1.0)


class TriageResponse(BaseModel):
    """Response of ``POST /v1/triage``."""

    request_id: str
    model_version: str
    product: LabelScore
    issue_top3: list[LabelProb] = Field(max_length=3)
    priority: Priority
    route: RouteLabel
    team: str
    summary: str | None = None
    latency_ms: int


class FeedbackRequest(BaseModel):
    """Body of ``POST /v1/feedback``: corrected labels for an earlier request."""

    request_id: str = Field(min_length=1, max_length=128)
    product: str | None = None
    issue: str | None = None
    priority: PriorityLabel | None = None
    team: str | None = None

    @model_validator(mode="after")
    def _at_least_one_correction(self) -> FeedbackRequest:
        if not any((self.product, self.issue, self.priority, self.team)):
            raise ValueError("provide at least one corrected field")
        return self


class FeedbackResponse(BaseModel):
    """Acknowledgement of stored feedback."""

    request_id: str
    status: Literal["accepted"] = "accepted"


class HealthResponse(BaseModel):
    """Response of ``GET /health``."""

    status: Literal["ok", "degraded"]
    model_loaded: bool
    model_version: str


class ModelInfoResponse(BaseModel):
    """Response of ``GET /v1/model``."""

    model_version: str
    predictor: str
    thresholds: dict[str, float]


class ErrorResponse(BaseModel):
    """Generic error body (no stack traces)."""

    detail: str
