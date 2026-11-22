"""Audit log and feedback store in SQLite (SPEC B3 US4-US5, C8, C10; M5). Stdlib only.

Every /v1/triage response becomes one ``requests`` row and every /v1/feedback call one
``feedback`` row linked by ``request_id``. Rows hold a hash of the scrubbed text, labels,
scores, model_version, route, reason and latency. **No complaint text is ever stored.**

If the store is unavailable (C8 "Log store down": SQLite errors, or an unwritable or missing
directory), the API still answers: the row goes to a
bounded in-memory buffer, ``write_errors`` (and ``dropped`` once the buffer is full) count
it, and buffered rows are retried before every later write.

CLI (aggregates only)::

    python -m complaintiq.serving.request_log stats [--path FILE] [--since 2026-11-01]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from complaintiq.config import load_config, resolve_path

logger = logging.getLogger("complaintiq.serving.request_log")

PATH_ENV = "COMPLAINTIQ_REQUEST_LOG"
FEEDBACK_FIELDS = ("product", "issue", "priority", "team")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    request_id TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    n_chars INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    predictor TEXT NOT NULL,
    product TEXT,
    product_conf REAL,
    issue TEXT,
    issue_p REAL,
    priority TEXT,
    priority_score REAL,
    route TEXT NOT NULL,
    team TEXT NOT NULL,
    reason TEXT,
    latency_ms INTEGER NOT NULL,
    pii_redactions INTEGER NOT NULL,
    pii_residual INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_requests_request_id ON requests (request_id);
CREATE INDEX IF NOT EXISTS ix_requests_ts ON requests (ts_utc);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    request_id TEXT NOT NULL,
    known_request INTEGER,
    product TEXT,
    issue TEXT,
    priority TEXT,
    team TEXT
);
CREATE INDEX IF NOT EXISTS ix_feedback_request_id ON feedback (request_id);
"""


def utc_now() -> str:
    """ISO-8601 UTC timestamp with seconds."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_hash(text: str, salt: str = "") -> str:
    """HMAC-SHA256 of ``text`` with ``salt`` (plain SHA-256 when ``salt`` is empty)."""
    data = text.encode("utf-8")
    if salt:
        return hmac.new(salt.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class RequestRow:
    """One audited /v1/triage response (no text)."""

    request_id: str
    text_hash: str
    n_chars: int
    model_version: str
    predictor: str
    product: str | None
    product_conf: float | None
    issue: str | None
    issue_p: float | None
    priority: str | None
    priority_score: float | None
    route: str
    team: str
    reason: str | None
    latency_ms: int
    pii_redactions: int
    pii_residual: int
    ts_utc: str = ""


@dataclass(frozen=True)
class FeedbackRow:
    """One correction from /v1/feedback; ``known_request`` is None if the store was down."""

    request_id: str
    known_request: bool | None
    product: str | None = None
    issue: str | None = None
    priority: str | None = None
    team: str | None = None
    ts_utc: str = ""


class RequestLog:
    """SQLite-backed audit log with a bounded retry buffer (thread-safe)."""

    def __init__(
        self,
        path: str | Path,
        buffer_max_rows: int = 1000,
        timeout_s: float = 1.0,
        salt: str = "",
        connect: Callable[[str], sqlite3.Connection] | None = None,
    ) -> None:
        self.path = str(path)
        self.salt = salt
        self.timeout_s = float(timeout_s)
        self._connect_fn = connect
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._buffer: deque[tuple[str, dict[str, Any]]] = deque(maxlen=int(buffer_max_rows))
        self.write_errors = 0
        self.dropped = 0

    # ------------------------------------------------------------------ connection

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._connect_fn is not None:
                conn = self._connect_fn(self.path)
            else:
                if self.path != ":memory:":
                    Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(self.path, timeout=self.timeout_s,
                                       check_same_thread=False)
                if self.path != ":memory:":
                    conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            self._conn = conn
        return self._conn

    def _reset(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
        self._conn = None

    @property
    def buffer_size(self) -> int:
        """Rows waiting to be written."""
        return len(self._buffer)

    # ------------------------------------------------------------------ writes

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
        cols = list(row)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[c] for c in cols],
        )

    def _write(self, table: str, row: dict[str, Any]) -> bool:
        """Write ``row`` (after any buffered rows). Buffer it if the store fails."""
        with self._lock:
            try:
                conn = self._connect()
                while self._buffer:
                    t, r = self._buffer[0]
                    self._insert(conn, t, r)
                    self._buffer.popleft()
                self._insert(conn, table, row)
                conn.commit()
                return True
            except (sqlite3.Error, OSError) as exc:
                self.write_errors += 1
                if len(self._buffer) == self._buffer.maxlen:
                    self.dropped += 1
                self._buffer.append((table, row))
                logger.warning("request log unavailable (%s); %d rows buffered",
                               type(exc).__name__, len(self._buffer))
                self._reset()
                return False

    def record_request(self, row: RequestRow) -> bool:
        """Store one triage row. Returns False if it was buffered instead."""
        data = asdict(row)
        data["ts_utc"] = data["ts_utc"] or utc_now()
        return self._write("requests", data)

    def known_request(self, request_id: str) -> bool | None:
        """True/False if the store can answer; None if it is unavailable."""
        with self._lock:
            try:
                cur = self._connect().execute(
                    "SELECT 1 FROM requests WHERE request_id = ? LIMIT 1", (request_id,)
                )
                found = cur.fetchone() is not None
            except (sqlite3.Error, OSError):
                self._reset()
                return None
        if not found:  # it may still be waiting in the buffer
            found = any(t == "requests" and r["request_id"] == request_id
                        for t, r in list(self._buffer))
        return found

    def record_feedback(self, request_id: str, corrections: dict[str, str | None]) -> FeedbackRow:
        """Store a correction linked to ``request_id`` (unknown ids are stored and flagged)."""
        row = FeedbackRow(
            request_id=request_id,
            known_request=self.known_request(request_id),
            ts_utc=utc_now(),
            **{f: corrections.get(f) for f in FEEDBACK_FIELDS},
        )
        data = asdict(row)
        data["known_request"] = None if row.known_request is None else int(row.known_request)
        self._write("feedback", data)
        return row

    def flush(self) -> int:
        """Retry buffered rows now; returns how many are still waiting."""
        with self._lock:
            try:
                conn = self._connect()
                while self._buffer:
                    t, r = self._buffer[0]
                    self._insert(conn, t, r)
                    self._buffer.popleft()
                conn.commit()
            except (sqlite3.Error, OSError):
                self._reset()
            return len(self._buffer)

    def close(self) -> None:
        """Flush what can be flushed and close the connection."""
        self.flush()
        with self._lock:
            self._reset()

    # ------------------------------------------------------------------ reads

    def correction_rate(self, since: str | None = None) -> dict[str, Any]:
        """Share of logged requests whose feedback changed at least one predicted field.

        Counts distinct request_ids, so repeated feedback for one request counts once.
        ``since`` is an ISO date/time compared with ``requests.ts_utc``.
        """
        where, params = ("WHERE r.ts_utc >= ?", [since]) if since else ("", [])
        changed = " OR ".join(
            f"(f.{c} IS NOT NULL AND (r.{c} IS NULL OR f.{c} != r.{c}))" for c in FEEDBACK_FIELDS
        )
        with self._lock:
            conn = self._connect()
            n_req = conn.execute(f"SELECT COUNT(*) FROM requests r {where}", params).fetchone()[0]
            n_fb = conn.execute(
                f"SELECT COUNT(DISTINCT f.request_id) FROM feedback f JOIN requests r "
                f"ON r.request_id = f.request_id {where}", params).fetchone()[0]
            n_corr = conn.execute(
                f"SELECT COUNT(DISTINCT f.request_id) FROM feedback f JOIN requests r "
                f"ON r.request_id = f.request_id {where} {'AND' if where else 'WHERE'} "
                f"({changed})", params).fetchone()[0]
            per_field = {
                c: conn.execute(
                    f"SELECT COUNT(DISTINCT f.request_id) FROM feedback f JOIN requests r "
                    f"ON r.request_id = f.request_id {where} {'AND' if where else 'WHERE'} "
                    f"f.{c} IS NOT NULL AND (r.{c} IS NULL OR f.{c} != r.{c})", params
                ).fetchone()[0]
                for c in FEEDBACK_FIELDS
            }
            n_unknown = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE known_request = 0"
                + (" AND ts_utc >= ?" if since else ""), params).fetchone()[0]
            routes = dict(conn.execute(
                f"SELECT route, COUNT(*) FROM requests r {where} GROUP BY route", params
            ).fetchall())
        return {
            "requests": n_req,
            "requests_with_feedback": n_fb,
            "corrected": n_corr,
            "correction_rate": (n_corr / n_req) if n_req else None,
            "corrected_by_field": per_field,
            "feedback_unknown_request": n_unknown,
            "routes": routes,
        }

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> RequestLog | None:
        """Log from ``configs/request_log.yaml`` (``None`` when disabled)."""
        c = cfg if cfg is not None else load_config("request_log")
        if not c.get("enabled", True):
            return None
        raw = os.environ.get(PATH_ENV) or c.get("path", "runtime/requests.sqlite")
        path = raw if raw == ":memory:" else str(resolve_path(raw))
        return cls(
            path,
            buffer_max_rows=int(c.get("buffer_max_rows", 1000)),
            timeout_s=float(c.get("sqlite_timeout_s", 1.0)),
            salt=os.environ.get(str(c.get("salt_env", "")), "") if c.get("salt_env") else "",
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Print aggregate stats of a request log (never text)."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("stats", help="request counts, routes and correction rate")
    st.add_argument("--path", default=None, help="SQLite file (default from config)")
    st.add_argument("--since", default=None, help="ISO date, e.g. 2026-11-01")
    args = ap.parse_args(argv)
    log = (RequestLog(str(resolve_path(args.path))) if args.path
           else RequestLog.from_config())
    if log is None:
        raise SystemExit("request log disabled in configs/request_log.yaml")
    print(json.dumps(log.correction_rate(args.since), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
