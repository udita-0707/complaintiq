"""Small stdlib client for the ComplaintIQ API, used by the Streamlit reviewer UI (FR7).

No third-party dependencies, so it is unit-tested without Streamlit. Never logs or stores
the complaint text.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

API_URL_ENV = "CIQ_API_URL"
DEFAULT_API_URL = "http://127.0.0.1:8000"
TIMEOUT_S = 30.0  # a free Space can take a while to wake up
PRIORITIES = ("NORMAL", "HIGH")

REASONS = {
    None: "Confidence is above the gate threshold, so the complaint was routed automatically.",
    "low_confidence": "The model is not confident enough to route this automatically.",
    "short_text": "The text is shorter than the narratives the model was trained on "
                  "(fewer than 20 words).",
    "low_quality_text": "The text does not read like a complaint narrative (too few real "
                        "words or mostly fragments).",
    "non_english": "The text looks non-English; the model only handles English.",
    "timeout": "The model did not answer in time, so no prediction is shown.",
}


class ApiError(RuntimeError):
    """An API call failed; ``status`` is 0 when the API could not be reached."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def api_url() -> str:
    """Base URL from ``CIQ_API_URL`` (no trailing slash)."""
    return os.environ.get(API_URL_ENV, DEFAULT_API_URL).rstrip("/")


def _call(method: str, url: str, payload: dict[str, Any] | None = None,
          timeout: float = TIMEOUT_S) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed URL)
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("detail", exc.reason)
        except (ValueError, AttributeError):
            detail = str(exc.reason)
        raise ApiError(exc.code, str(detail)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(0, f"API not reachable ({type(exc).__name__})") from None


def triage(text: str, base: str | None = None) -> dict[str, Any]:
    """POST /v1/triage."""
    return _call("POST", f"{base or api_url()}/v1/triage", {"text": text})


def model_info(base: str | None = None) -> dict[str, Any]:
    """GET /v1/model."""
    return _call("GET", f"{base or api_url()}/v1/model", timeout=10.0)


def feedback_payload(result: dict[str, Any], product: str = "", issue: str = "",
                     priority: str = "", team: str = "") -> dict[str, Any]:
    """Feedback body with only the fields the reviewer changed. Raises if nothing changed."""
    predicted = {
        "product": result["product"]["label"],
        "issue": result["issue_top3"][0]["label"] if result.get("issue_top3") else "",
        "priority": result["priority"]["label"],
        "team": result["team"],
    }
    given = {"product": product.strip(), "issue": issue.strip(), "priority": priority.strip(),
             "team": team.strip()}
    changed = {k: v for k, v in given.items() if v and v != predicted[k]}
    if not changed:
        raise ValueError("Change at least one field before sending a correction.")
    return {"request_id": result["request_id"], **changed}


def send_feedback(payload: dict[str, Any], base: str | None = None) -> dict[str, Any]:
    """POST /v1/feedback."""
    return _call("POST", f"{base or api_url()}/v1/feedback", payload)


def explain(result: dict[str, Any]) -> str:
    """Plain-language reason for the route."""
    return REASONS.get(result.get("reason"), "Sent to human review.")


def error_message(err: ApiError) -> str:
    """What went wrong and what to do, in the UI's voice."""
    if err.status == 0:
        return ("The API is not responding. A free Space sleeps when idle; wait a minute and "
                "try again.")
    if err.status == 400:
        return f"The text was rejected: {err.detail}."
    if err.status == 413:
        return "The text is too large. Paste at most 10,000 characters."
    if err.status == 429:
        return "Too many requests from this address. Wait a minute and try again."
    if err.status == 503:
        return "The model is unavailable right now. Try again later."
    return f"The API returned an error ({err.status})."
