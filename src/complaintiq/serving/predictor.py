"""Predictor interface and the stub used by the walking skeleton.

Real models (TF-IDF+LR baseline, transformer/ONNX) implement ``Predictor`` and are
selected in ``build_predictor`` via ``configs/model.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Prediction:
    """Model output before gating and routing."""

    product: str
    product_confidence: float
    issue_top3: list[tuple[str, float]]
    priority: str  # "HIGH" | "NORMAL"
    priority_score: float


@runtime_checkable
class Predictor(Protocol):
    """Anything that turns (already PII-scrubbed) text into a ``Prediction``."""

    @property
    def model_version(self) -> str:
        """Version string returned in every response (FR5)."""
        ...

    def predict(self, text: str) -> Prediction:
        """Predict product, issue top-3 and priority for one complaint."""
        ...


class StubPredictor:
    """Returns a fixed dummy prediction. Placeholder until a real model exists."""

    def __init__(self, model_version: str = "stub-0.0.0") -> None:
        self._model_version = model_version

    @property
    def model_version(self) -> str:
        return self._model_version

    def predict(self, text: str) -> Prediction:
        return Prediction(
            product="Debt collection",
            product_confidence=0.94,
            issue_top3=[
                ("Attempts to collect debt not owed", 0.71),
                ("Communication tactics", 0.12),
                ("Written notification about debt", 0.07),
            ],
            priority="HIGH",
            priority_score=0.83,
        )


def build_predictor(model_config: dict[str, Any]) -> Predictor:
    """Create the predictor named by ``model_config['predictor']``."""
    kind = model_config.get("predictor", "stub")
    version = str(model_config.get("model_version", "stub-0.0.0"))
    if kind == "stub":
        return StubPredictor(model_version=version)
    raise ValueError(f"Unknown predictor '{kind}'; only 'stub' is available in the skeleton")
