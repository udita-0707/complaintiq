"""M5 input safety: scrub counts, quality heuristic, body limit, rate limit, CORS (synthetic).

API-level checks (scrub before predict, no PII in captured logs) are in
tests/test_api_runtime.py because they need the wired app.
"""

import asyncio
import subprocess
import sys

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from complaintiq.config import load_config
from complaintiq.privacy.pii import PLACEHOLDER, residual_hits, scrub, scrub_with_counts
from complaintiq.serving.input_quality import assess, is_junk
from complaintiq.serving.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    TokenBucketLimiter,
    cors_origins,
)

# Synthetic PII only (reserved/test values).
PII_TEXT = (
    "Email jane.doe@example.com, phone (555) 010-4477, SSN 078-05-1120, "
    "card 4111 1111 1111 1111, account 123456789012."
)
CFG = load_config("safety")["input_quality"]
LONG_EN = (
    "I am writing about my credit report. The account listed on my report does not belong "
    "to me and I have disputed it twice with the bureau. They say I owe a balance that I "
    "already paid in full last year. Please help me resolve this issue."
)


def test_scrub_with_counts_counts_without_returning_matches() -> None:
    r = scrub_with_counts(PII_TEXT)
    assert r.redactions == 5
    assert r.residual == 0
    assert r.by_pattern == {"email": 1, "ssn": 1, "card": 1, "phone": 1, "long_digits": 1}
    for secret in ("jane.doe@example.com", "078-05-1120", "4111 1111 1111 1111", "123456789012"):
        assert secret not in r.text
    assert r.text.count(PLACEHOLDER) == 5
    assert scrub(PII_TEXT) == r.text  # scrub() keeps its M2 behaviour


def test_non_luhn_card_kept_and_residual_detects_leftovers() -> None:
    assert scrub_with_counts("card 4111 1111 1111 1112 here").redactions == 0
    assert residual_hits("write to a@b.co") == 1
    assert residual_hits(scrub("write to a@b.co")) == 0


def test_pii_module_imports_without_polars() -> None:
    code = "import sys, complaintiq.privacy.pii; print('polars' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out == "False"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (LONG_EN, None),
        ("A debt collector keeps calling me about a debt I do not owe.", "short_text"),
        ("Me están cobrando una deuda que no debo y llaman todos los días a mi trabajo, ya les "
         "dije que no es mía y siguen llamando sin parar por favor ayuda", "non_english"),
        ("Je suis très mécontent de ma banque car ils ont fermé mon compte sans raison et je ne "
         "peux pas accéder à mon argent depuis deux semaines", "non_english"),
        ("\u6211\u7684\u4fe1\u7528\u62a5\u544a\u4e0a\u6709\u4e00\u4e2a\u4e0d\u5c5e\u4e8e"
         "\u6211\u7684\u8d26\u6237\uff0c\u6211\u5df2\u7ecf\u63d0\u51fa\u4e86\u4e24\u6b21"
         "\u4e89\u8bae\u3002", "non_english"),
        ("asdf qwer zxcv sdfghjkl asdf qwer zxcv lkjh mnbv asdf qwer zxcv poiu",
         "low_quality_text"),
        ("aaaaaaa bbbbbbbbb ccccccc dddddddd eeeeeeee ffffff ggggggg hhhhhhhh",
         "low_quality_text"),
        (f"{PLACEHOLDER} {PLACEHOLDER} XXXX XXXX {PLACEHOLDER} 12345 XX/XX/XXXX",
         "low_quality_text"),
    ],
)
def test_quality_reasons(text: str, reason: str | None) -> None:
    r = assess(text, CFG)
    assert r.reason == reason
    assert r.ok is (reason is None)


def test_quality_disabled_and_junk_tokens() -> None:
    assert assess("asdf qwer zxcv", {**CFG, "enabled": False}).ok
    assert is_junk("sdfghjkl", CFG) and is_junk("zzzzz", CFG) and is_junk("x" * 30, CFG)
    assert not is_junk("strengths", CFG) and not is_junk("mortgage", CFG)


# ------------------------------------------------------------------ middlewares


async def _echo(request):
    body = await request.body()
    return JSONResponse({"n": len(body)})


def _app(limiter=None, max_bytes=100, bypass_env=None, hits=None) -> Starlette:
    app = Starlette(routes=[Route("/v1/triage", _echo, methods=["POST"]),
                            Route("/health", _echo, methods=["GET", "POST"])])
    app.add_middleware(RateLimitMiddleware, get_limiter=lambda scope: limiter,
                       paths=["/v1/triage"], bypass_token_env=bypass_env,
                       on_limited=(lambda scope: hits.append(1)) if hits is not None else None)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    return app


def test_body_limit_by_header_and_passthrough() -> None:
    with TestClient(_app()) as c:
        assert c.post("/v1/triage", content=b"x" * 100).json() == {"n": 100}
        r = c.post("/v1/triage", content=b"x" * 101)
        assert r.status_code == 413
        assert c.get("/health").status_code == 200


def test_body_limit_counts_streamed_chunks_without_content_length() -> None:
    sent: list[dict] = []
    called: list[bool] = []

    async def inner(scope, receive, send):
        called.append(True)

    chunks = [{"type": "http.request", "body": b"x" * 60, "more_body": True},
              {"type": "http.request", "body": b"x" * 60, "more_body": False}]

    async def receive():
        return chunks.pop(0)

    async def send(msg):
        sent.append(msg)

    mw = BodySizeLimitMiddleware(inner, max_bytes=100)
    asyncio.run(mw({"type": "http", "method": "POST", "headers": []}, receive, send))
    assert not called
    assert sent[0]["status"] == 413


def test_token_bucket_burst_refill_and_prune() -> None:
    now = [0.0]
    lim = TokenBucketLimiter(requests_per_minute=60, burst=2, max_clients=1, clock=lambda: now[0])
    assert lim.allow("a")[0] and lim.allow("a")[0]
    allowed, wait = lim.allow("a")
    assert not allowed and wait == pytest.approx(1.0)
    now[0] = 1.0
    assert lim.allow("a")[0]
    now[0] = 100.0
    lim.allow("b")  # two keys > max_clients=1 -> idle "a" is pruned
    assert "a" not in lim._buckets


def test_rate_limit_429_paths_and_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    hits: list[int] = []
    lim = TokenBucketLimiter(requests_per_minute=1, burst=1)
    monkeypatch.setenv("CIQ_TEST_BYPASS", "s3cret")
    with TestClient(_app(limiter=lim, bypass_env="CIQ_TEST_BYPASS", hits=hits)) as c:
        assert c.post("/v1/triage", content=b"{}").status_code == 200
        r = c.post("/v1/triage", content=b"{}")
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
        assert hits == [1]
        assert c.post("/health", content=b"{}").status_code == 200  # not a limited path
        ok = c.post("/v1/triage", content=b"{}", headers={"x-ciq-loadtest-token": "s3cret"})
        assert ok.status_code == 200
        bad = c.post("/v1/triage", content=b"{}", headers={"x-ciq-loadtest-token": "nope"})
        assert bad.status_code == 429


def test_limiter_from_config_and_cors() -> None:
    sec = load_config("safety")["security"]
    lim = TokenBucketLimiter.from_config(sec["rate_limit"])
    assert lim is not None and lim.burst == int(sec["rate_limit"]["burst"])
    assert TokenBucketLimiter.from_config({"enabled": False}) is None
    assert cors_origins(sec) == []
    assert cors_origins({"cors_origins": ["https://a.hf.space/"]}) == ["https://a.hf.space"]
    with pytest.raises(ValueError):
        cors_origins({"cors_origins": ["*"]})
