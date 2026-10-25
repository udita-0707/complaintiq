"""Confidence gate (SPEC B4 FR4): auto-route only when confidence >= tau."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from complaintiq.config import load_config

Route = Literal["AUTO", "HUMAN_REVIEW"]


@dataclass(frozen=True)
class ConfidenceGate:
    """Send predictions below the threshold ``tau`` to human review."""

    tau: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.tau <= 1.0:
            raise ValueError(f"tau must be in [0, 1], got {self.tau}")

    @classmethod
    def from_config(cls, thresholds: dict[str, Any] | None = None) -> ConfidenceGate:
        """Build from a thresholds mapping, defaulting to ``configs/thresholds.yaml``."""
        cfg = thresholds if thresholds is not None else load_config("thresholds")
        if "tau" not in cfg:
            raise ValueError("thresholds config is missing 'tau'")
        return cls(tau=float(cfg["tau"]))

    def decide(self, confidence: float) -> Route:
        """Return ``AUTO`` if ``confidence >= tau``, else ``HUMAN_REVIEW``."""
        return "AUTO" if confidence >= self.tau else "HUMAN_REVIEW"
