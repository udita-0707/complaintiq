"""Predictor interface, the stub, and config-driven predictor selection.

Real models (TF-IDF baseline, transformer) implement ``Predictor`` and are selected in
``resolve_predictor`` via ``configs/model.yaml: predictor`` and ``configs/serving.yaml``.

M5 fallback chain at load time (SPEC C8): transformer -> baseline -> (stub only when
``serving.yaml: allow_stub_fallback`` is true) -> none, in which case /v1/triage answers 503.
A predictor loaded as a fallback reports ``<model_version>-fallback``. The env var
``COMPLAINTIQ_PREDICTOR`` overrides ``model.yaml: predictor`` (the CI/dev image uses
``stub``; tests use it too).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from complaintiq.config import load_config, resolve_path

logger = logging.getLogger("complaintiq.serving")

PREDICTOR_ENV = "COMPLAINTIQ_PREDICTOR"
FALLBACK_SUFFIX = "-fallback"


def resolve(path: str | Path) -> Path:
    """Resolve a config path relative to ``COMPLAINTIQ_ROOT`` (default: the repo root)."""
    return resolve_path(path)


def configured_kind(model_config: dict[str, Any]) -> str:
    """Predictor kind from ``COMPLAINTIQ_PREDICTOR`` or ``model.yaml: predictor``."""
    return os.environ.get(PREDICTOR_ENV) or str(model_config.get("predictor", "stub"))


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


def calibration_kwargs(thresholds: dict[str, Any]) -> dict[str, Any]:
    """BaselinePredictor calibration arguments from ``configs/thresholds.yaml`` (M4).

    Missing keys keep the M3 behaviour (temperature 1, threshold from the model's meta).
    """
    temps = {
        task: float(thresholds[f"temperature_{task}"])
        for task in ("product", "issue")
        if f"temperature_{task}" in thresholds
    }
    thr = thresholds.get("priority_threshold")
    return {"temperatures": temps, "priority_threshold": None if thr is None else float(thr)}


class FlaggedPredictor:
    """Wraps a predictor that serves as a fallback: same predictions, flagged version."""

    def __init__(self, inner: Predictor, suffix: str = FALLBACK_SUFFIX) -> None:
        self.inner = inner
        self._suffix = suffix

    @property
    def model_version(self) -> str:
        return f"{self.inner.model_version}{self._suffix}"

    def predict(self, text: str) -> Prediction:
        return self.inner.predict(text)


def load_predictor(
    kind: str, serving: dict[str, Any], thresholds_config: dict[str, Any] | None = None
) -> Predictor | None:
    """Load one real predictor, or return ``None`` (with a warning) if it cannot load."""
    model_dir = resolve(serving[kind]["model_dir"])
    if not _artifact_ready(kind, model_dir):
        logger.warning("%s artifact missing at %s", kind, model_dir)
        return None
    try:
        if kind == "baseline":
            from complaintiq.models.baseline import BaselinePredictor

            th = thresholds_config if thresholds_config is not None else load_config("thresholds")
            return BaselinePredictor(model_dir, **calibration_kwargs(th))
        from complaintiq.models.transformer import TransformerPredictor

        return TransformerPredictor(model_dir)
    except Exception as exc:  # ImportError, corrupt artifact, missing task ...
        logger.warning("%s predictor unavailable (%s)", kind, type(exc).__name__)
        return None


def resolve_predictor(
    model_config: dict[str, Any],
    serving_config: dict[str, Any] | None = None,
    thresholds_config: dict[str, Any] | None = None,
) -> tuple[Predictor | None, str]:
    """Create the predictor named by ``model_config['predictor']`` and return it with the
    kind actually in use.

    ``baseline`` and ``transformer`` are imported lazily. Chain (SPEC C8): the configured
    kind, then ``baseline`` if the configured kind was ``transformer`` (flagged
    ``-fallback``), then the stub (``model_version`` = ``fallback_model_version``) when
    ``serving['allow_stub_fallback']`` is true (the default, kept for M3/M4 callers), else
    ``(None, "none")``. The baseline gets its temperatures and priority threshold from
    ``thresholds_config`` (default ``configs/thresholds.yaml``), so the gate sees calibrated
    confidence. This function does not read ``COMPLAINTIQ_PREDICTOR``; see
    :func:`configured_kind`.
    """
    kind = model_config.get("predictor", "stub")
    version = str(model_config.get("model_version", "stub-0.0.0"))
    if kind == "stub":
        return StubPredictor(model_version=version), "stub"
    if kind not in ("baseline", "transformer"):
        raise ValueError(f"Unknown predictor '{kind}'; expected stub, baseline or transformer")

    serving = serving_config if serving_config is not None else load_config("serving")
    pred = load_predictor(kind, serving, thresholds_config)
    if pred is not None:
        return pred, kind
    if kind == "transformer":
        base = load_predictor("baseline", serving, thresholds_config)
        if base is not None:
            logger.warning("transformer unavailable; serving the baseline fallback")
            return FlaggedPredictor(base), "baseline"
    if serving.get("allow_stub_fallback", True):
        logger.warning("%s unavailable; falling back to the stub", kind)
        return StubPredictor(model_version=str(serving.get("fallback_model_version", "stub"))), \
            "stub"
    logger.error("%s unavailable and stub fallback disabled; /v1/triage will answer 503", kind)
    return None, "none"


def resolve_runtime_fallback(
    kind_in_use: str,
    serving_config: dict[str, Any] | None = None,
    thresholds_config: dict[str, Any] | None = None,
) -> Predictor | None:
    """Predictor used when the primary fails at inference time (C8): the baseline behind a
    transformer, flagged ``-fallback``; ``None`` for any other primary."""
    if kind_in_use != "transformer":
        return None
    serving = serving_config if serving_config is not None else load_config("serving")
    base = load_predictor("baseline", serving, thresholds_config)
    return FlaggedPredictor(base) if base is not None else None


def build_predictor(
    model_config: dict[str, Any], serving_config: dict[str, Any] | None = None
) -> Predictor | None:
    """Create the configured predictor (see :func:`resolve_predictor`)."""
    return resolve_predictor(model_config, serving_config)[0]
