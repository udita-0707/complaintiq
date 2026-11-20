"""Predictor interface, the stub, and config-driven predictor selection.

Real models (TF-IDF baseline, transformer) implement ``Predictor`` and are selected in
``resolve_predictor`` via ``configs/model.yaml: predictor`` and ``configs/serving.yaml``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from complaintiq.config import load_config

logger = logging.getLogger("complaintiq.serving")


def resolve(path: str | Path) -> Path:
    """Resolve a config path relative to the repo root."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else Path(__file__).resolve().parents[3] / p


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


def _artifact_ready(kind: str, model_dir: Path) -> bool:
    """True if the files the predictor needs exist."""
    if kind == "baseline":
        return (model_dir / "meta.json").is_file()
    tasks = ("product", "issue", "priority")
    return all((model_dir / t / "ciq_meta.json").is_file() for t in tasks)


def resolve_predictor(
    model_config: dict[str, Any], serving_config: dict[str, Any] | None = None
) -> tuple[Predictor, str]:
    """Create the predictor named by ``model_config['predictor']`` and return it with the
    kind actually in use.

    ``baseline`` and ``transformer`` are imported lazily. If the artifact directory from
    ``configs/serving.yaml`` is missing or the model libraries are not installed, fall back
    to the stub (``model_version`` = ``fallback_model_version``) and log a warning.
    """
    kind = model_config.get("predictor", "stub")
    version = str(model_config.get("model_version", "stub-0.0.0"))
    if kind == "stub":
        return StubPredictor(model_version=version), "stub"
    if kind not in ("baseline", "transformer"):
        raise ValueError(f"Unknown predictor '{kind}'; expected stub, baseline or transformer")

    serving = serving_config if serving_config is not None else load_config("serving")
    fallback = StubPredictor(model_version=str(serving.get("fallback_model_version", "stub")))
    model_dir = resolve(serving[kind]["model_dir"])
    if not _artifact_ready(kind, model_dir):
        logger.warning("%s artifact missing at %s; falling back to the stub", kind, model_dir)
        return fallback, "stub"
    try:
        if kind == "baseline":
            from complaintiq.models.baseline import BaselinePredictor

            return BaselinePredictor(model_dir), kind
        from complaintiq.models.transformer import TransformerPredictor

        return TransformerPredictor(model_dir), kind
    except ImportError as exc:
        logger.warning("%s predictor unavailable (%s); falling back to the stub", kind, exc)
        return fallback, "stub"


def build_predictor(
    model_config: dict[str, Any], serving_config: dict[str, Any] | None = None
) -> Predictor:
    """Create the configured predictor (see :func:`resolve_predictor`)."""
    return resolve_predictor(model_config, serving_config)[0]
