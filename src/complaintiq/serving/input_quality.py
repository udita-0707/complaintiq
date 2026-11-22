"""Input quality heuristic for /v1/triage (SPEC C8; M5). No dependencies beyond stdlib.

Runs on the PII-scrubbed text and decides whether the prediction may be auto-routed. A
failing text is still scored, but the API answers ``route=HUMAN_REVIEW`` with a reason:

- ``non_english``: mostly non a-z letters, or Spanish/French function words outweigh English
  ones (the model and the SPEC scope are English only, A7);
- ``low_quality_text``: too few letter tokens, mostly junk tokens (keyboard mashing,
  repeated letters), or no English function words at all;
- ``short_text``: fewer whitespace words than the training data ever had
  (``configs/data.yaml: min_words``), so the model is out of distribution.

Thresholds live in ``configs/safety.yaml: input_quality``. It is a heuristic: it is meant
to catch obvious cases cheaply, and its misses still pass the confidence gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from complaintiq.privacy.pii import PLACEHOLDER

# Common English function words (closed class; topic-neutral).
ENGLISH = frozenset(
    """the and to of i my was in it that for is on they this with have not be me
    but are had at by an or from as were been their them we you your has would there
    so if all he she his her our no did do does what when which who will can could
    about after before because than then into over again also any only out up""".split()
)
# Spanish and French function words that are not also common English words.
OTHER = frozenset(
    """el la los las un una unos unas que y en por para con del al es son mi mis su
    sus pero porque como cuando muy sin sobre este esta esto estoy tengo fue han hay
    lo le les se ya yo nos des et est sont avec dans sur pas mon ma mes je vous
    nous il elle qui du au aux ce cette mais ou très été ai avait leur""".split()
)
VOWELS = frozenset("aeiouy")
_LETTERS = re.compile(r"[^\W\d_]+")
_PLACEHOLDER_WORD = PLACEHOLDER.strip("[]").lower()


@dataclass(frozen=True)
class QualityResult:
    """Outcome of :func:`assess`; aggregates only (safe to log)."""

    ok: bool
    reason: str | None
    n_words: int
    n_alpha_tokens: int
    junk_share: float
    english_share: float
    other_share: float
    ascii_letter_share: float


def _is_placeholder(token: str) -> bool:
    return token == _PLACEHOLDER_WORD or set(token) == {"x"}


def _consonant_run(token: str) -> int:
    best = run = 0
    for ch in token:
        run = run + 1 if ch.isalpha() and ch not in VOWELS else 0
        best = max(best, run)
    return best


def _repeat_run(token: str) -> int:
    best = run = 0
    prev = ""
    for ch in token:
        run = run + 1 if ch == prev else 1
        best = max(best, run)
        prev = ch
    return best


def is_junk(token: str, cfg: dict[str, Any]) -> bool:
    """True for tokens that do not look like words (no vowel, long consonant or repeat runs)."""
    if len(token) > int(cfg["max_token_len"]):
        return True
    if len(token) >= 4 and not (set(token) & VOWELS):
        return True
    if _consonant_run(token) >= int(cfg["max_consonant_run"]):
        return True
    return _repeat_run(token) >= int(cfg["max_repeat_run"])


def assess(text: str, cfg: dict[str, Any]) -> QualityResult:
    """Score ``text`` (already scrubbed) against ``configs/safety.yaml: input_quality``."""
    n_words = len(text.split())
    letters = [ch for ch in text if ch.isalpha()]
    ascii_share = (
        sum(1 for ch in letters if "a" <= ch.lower() <= "z") / len(letters) if letters else 0.0
    )
    tokens = [t for t in _LETTERS.findall(text.lower()) if len(t) >= 2 and not _is_placeholder(t)]
    n = len(tokens)
    english = sum(1 for t in tokens if t in ENGLISH) / n if n else 0.0
    other = sum(1 for t in tokens if t in OTHER) / n if n else 0.0
    junk = sum(1 for t in tokens if is_junk(t, cfg)) / n if n else 1.0

    def result(reason: str | None) -> QualityResult:
        return QualityResult(
            ok=reason is None,
            reason=reason,
            n_words=n_words,
            n_alpha_tokens=n,
            junk_share=round(junk, 4),
            english_share=round(english, 4),
            other_share=round(other, 4),
            ascii_letter_share=round(ascii_share, 4),
        )

    if not cfg.get("enabled", True):
        return result(None)
    if letters and ascii_share < float(cfg["min_ascii_letter_share"]):
        return result("non_english")
    if other >= float(cfg["other_language_min_share"]) and other > english:
        return result("non_english")
    if (
        n < int(cfg["min_alpha_tokens"])
        or junk >= float(cfg["junk_token_share"])
        or english < float(cfg["min_english_share"])
    ):
        return result("low_quality_text")
    if n_words < int(cfg["min_words"]):
        return result("short_text")
    return result(None)
