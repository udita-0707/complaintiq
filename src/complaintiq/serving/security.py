"""Request-level security for the API (SPEC C10; M5). Pure ASGI, stdlib only.

- :class:`BodySizeLimitMiddleware`: 413 for request bodies above ``max_body_bytes``, checked
  before FastAPI parses anything.
- :class:`TokenBucketLimiter` + :class:`RateLimitMiddleware`: per-client-IP token bucket on
  the configured paths; 429 with ``Retry-After`` when the bucket is empty.
- :func:`cors_origins`: the allowed browser origins, refusing ``"*"``.

Settings come from ``configs/safety.yaml: security``. Nothing here reads or logs bodies.
"""

from __future__ import annotations

import hmac
import json
import math
import os
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOADTEST_HEADER = b"x-ciq-loadtest-token"
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def cors_origins(security_cfg: dict[str, Any]) -> list[str]:
    """Allowed CORS origins from config; raises on a wildcard (C10: CORS restricted)."""
    origins = [str(o).rstrip("/") for o in security_cfg.get("cors_origins") or []]
    if any("*" in o for o in origins):
        raise ValueError("configs/safety.yaml: security.cors_origins must not contain '*'")
    return origins


async def _send_json(send: Send, status: int, body: dict[str, Any],
                     headers: Iterable[tuple[bytes, bytes]] = ()) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()), *headers],
    })
    await send({"type": "http.response.body", "body": payload})


class BodySizeLimitMiddleware:
    """Reject bodies larger than ``max_bytes`` with 413 (header check, then counted read)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                await _send_json(send, 413, {"detail": "Request body too large"})
                return
        # Read the (small) body once, enforcing the limit, then replay it to the app.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await _send_json(send, 413, {"detail": "Request body too large"})
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


@dataclass
class TokenBucketLimiter:
    """Per-key token bucket: ``burst`` tokens, refilled at ``requests_per_minute``."""

    requests_per_minute: float
    burst: int
    max_clients: int = 10_000
    clock: Callable[[], float] = time.monotonic
    _buckets: dict[str, tuple[float, float]] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def rate_per_s(self) -> float:
        return float(self.requests_per_minute) / 60.0

    def allow(self, key: str) -> tuple[bool, float]:
        """Take one token for ``key``. Returns (allowed, seconds until a token is free)."""
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.rate_per_s)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                allowed, wait = True, 0.0
            else:
                self._buckets[key] = (tokens, now)
                allowed = False
                wait = (1.0 - tokens) / self.rate_per_s if self.rate_per_s > 0 else math.inf
            if len(self._buckets) > self.max_clients:
                self._prune(now)
        return allowed, wait

    def _prune(self, now: float) -> None:
        """Drop buckets that have refilled completely (idle clients)."""
        full_after = float(self.burst) / self.rate_per_s if self.rate_per_s > 0 else math.inf
        for k in [k for k, (_t, last) in self._buckets.items() if now - last >= full_after]:
            del self._buckets[k]

    @classmethod
    def from_config(cls, rate_cfg: dict[str, Any]) -> TokenBucketLimiter | None:
        """Limiter from ``security.rate_limit``; ``None`` when disabled."""
        if not rate_cfg or not rate_cfg.get("enabled", False):
            return None
        return cls(
            requests_per_minute=float(rate_cfg["requests_per_minute"]),
            burst=int(rate_cfg["burst"]),
            max_clients=int(rate_cfg.get("max_clients", 10_000)),
        )


def _client_key(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


class RateLimitMiddleware:
    """429 when the client's bucket is empty, on ``paths`` only.

    ``get_limiter(scope)`` returns the limiter to use (or ``None`` to skip), so tests and
    the app can swap it at runtime. A request whose ``x-ciq-loadtest-token`` header equals
    the env var named by ``bypass_token_env`` is not limited (load tests only).
    ``on_limited(scope)`` is called for every 429 (e.g. to count it).
    """

    def __init__(
        self,
        app: ASGIApp,
        get_limiter: Callable[[Scope], TokenBucketLimiter | None],
        paths: Iterable[str],
        bypass_token_env: str | None = None,
        on_limited: Callable[[Scope], None] | None = None,
    ) -> None:
        self.app = app
        self.get_limiter = get_limiter
        self.paths = frozenset(paths)
        self.bypass_token_env = bypass_token_env
        self.on_limited = on_limited

    def _bypassed(self, scope: Scope) -> bool:
        if not self.bypass_token_env:
            return False
        expected = os.environ.get(self.bypass_token_env, "")
        if not expected:
            return False
        for name, value in scope.get("headers", []):
            if name == LOADTEST_HEADER:
                return hmac.compare_digest(value, expected.encode())
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in self.paths:
            await self.app(scope, receive, send)
            return
        limiter = self.get_limiter(scope)
        if limiter is None or self._bypassed(scope):
            await self.app(scope, receive, send)
            return
        allowed, wait = limiter.allow(_client_key(scope))
        if allowed:
            await self.app(scope, receive, send)
            return
        if self.on_limited is not None:
            self.on_limited(scope)
        retry = str(max(1, math.ceil(wait))) if math.isfinite(wait) else "60"
        await _send_json(send, 429, {"detail": "Too many requests"},
                         headers=[(b"retry-after", retry.encode())])
