"""Guarded inference for /v1/triage (SPEC C8; M5).

:class:`GuardedPredictor` runs the primary predictor in a small thread pool with a timeout:

- finished in time -> ``status="ok"``;
- slower than ``inference_timeout_s`` -> ``status="timeout"``; the API answers
  ``route=HUMAN_REVIEW`` with ``reason="timeout"`` (C8 "Timeout (> 2 s)");
- raised -> the runtime fallback (the baseline behind a transformer, flagged
  ``-fallback``) answers with ``status="fallback"``; without a fallback ``status="error"``
  and the API answers 503 (C7 "503 model unavailable (triggers fallback first)").

Test hooks exist only for failure tests: they are read from the environment **only** when
``COMPLAINTIQ_ENABLE_TEST_HOOKS=1`` (never set in the deployed Space):
``COMPLAINTIQ_TEST_DELAY_S`` sleeps before the primary predicts, and
``COMPLAINTIQ_TEST_FAIL_PRIMARY=1`` makes the primary raise.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Literal

from complaintiq.serving.predictor import Prediction, Predictor

logger = logging.getLogger("complaintiq.serving")

HOOKS_ENV = "COMPLAINTIQ_ENABLE_TEST_HOOKS"
DELAY_ENV = "COMPLAINTIQ_TEST_DELAY_S"
FAIL_ENV = "COMPLAINTIQ_TEST_FAIL_PRIMARY"

Status = Literal["ok", "fallback", "timeout", "error"]


@dataclass(frozen=True)
class TestHooks:
    """Failure injection for scripts/failure_tests.py (disabled unless the env flag is 1)."""

    __test__ = False  # not a pytest test class

    delay_s: float = 0.0
    fail_primary: bool = False

    @classmethod
    def from_env(cls) -> TestHooks:
        if os.environ.get(HOOKS_ENV) != "1":
            return cls()
        return cls(delay_s=float(os.environ.get(DELAY_ENV, "0") or 0),
                   fail_primary=os.environ.get(FAIL_ENV) == "1")

    @property
    def active(self) -> bool:
        return self.delay_s > 0 or self.fail_primary


class InjectedFailure(RuntimeError):
    """Raised by the fail-primary test hook."""


@dataclass(frozen=True)
class Outcome:
    """Result of one guarded prediction."""

    prediction: Prediction | None
    model_version: str
    status: Status


class GuardedPredictor:
    """Primary predictor with timeout and an optional runtime fallback."""

    def __init__(
        self,
        primary: Predictor,
        fallback: Predictor | None = None,
        timeout_s: float = 2.0,
        workers: int = 4,
        hooks: TestHooks | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.timeout_s = float(timeout_s)
        self.hooks = hooks or TestHooks()
        self._pool = ThreadPoolExecutor(max_workers=int(workers), thread_name_prefix="ciq-infer")
        if self.hooks.active:
            logger.warning("failure-test hooks are ACTIVE (%s=1); never use in deployment",
                           HOOKS_ENV)

    @property
    def model_version(self) -> str:
        return self.primary.model_version

    def _primary(self, text: str) -> Prediction:
        if self.hooks.delay_s > 0:
            time.sleep(self.hooks.delay_s)
        if self.hooks.fail_primary:
            raise InjectedFailure("injected primary failure")
        return self.primary.predict(text)

    def predict(self, text: str) -> Outcome:
        """Predict with the timeout; never raises."""
        future = self._pool.submit(self._primary, text)
        try:
            return Outcome(future.result(timeout=self.timeout_s), self.primary.model_version, "ok")
        except FutureTimeout:
            future.cancel()
            logger.warning("inference timeout after %.2f s", self.timeout_s)
            return Outcome(None, self.primary.model_version, "timeout")
        except Exception as exc:
            logger.warning("primary predictor failed (%s)", type(exc).__name__)
        if self.fallback is None:
            return Outcome(None, self.primary.model_version, "error")
        try:
            pred = self._pool.submit(self.fallback.predict, text).result(timeout=self.timeout_s)
            return Outcome(pred, self.fallback.model_version, "fallback")
        except FutureTimeout:
            return Outcome(None, self.fallback.model_version, "timeout")
        except Exception as exc:
            logger.warning("fallback predictor failed (%s)", type(exc).__name__)
            return Outcome(None, self.primary.model_version, "error")

    def shutdown(self) -> None:
        """Stop the worker pool without waiting for hung predictions."""
        self._pool.shutdown(wait=False, cancel_futures=True)
