"""Unit tests for the confidence gate."""

import pytest

from complaintiq.serving.gate import ConfidenceGate


def test_at_or_above_tau_is_auto() -> None:
    gate = ConfidenceGate(tau=0.8)
    assert gate.decide(0.8) == "AUTO"
    assert gate.decide(0.99) == "AUTO"


def test_below_tau_is_human_review() -> None:
    assert ConfidenceGate(tau=0.8).decide(0.79) == "HUMAN_REVIEW"


def test_from_config_file_reads_tau() -> None:
    assert 0.0 <= ConfidenceGate.from_config().tau <= 1.0


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_invalid_tau_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        ConfidenceGate(tau=bad)


def test_missing_tau_rejected() -> None:
    with pytest.raises(ValueError):
        ConfidenceGate.from_config({})
