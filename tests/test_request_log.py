"""M5 request log: audit rows, feedback linking, correction rate, store-down buffering."""

import json
import sqlite3
from pathlib import Path

import pytest

from complaintiq.serving import request_log as rl
from complaintiq.serving.request_log import RequestLog, RequestRow, text_hash


def row(request_id: str, product: str = "Mortgage", route: str = "AUTO") -> RequestRow:
    return RequestRow(
        request_id=request_id, text_hash=text_hash("scrubbed text " + request_id), n_chars=120,
        model_version="baseline-unit-cal", predictor="baseline", product=product,
        product_conf=0.91, issue="Struggling to pay mortgage", issue_p=0.6, priority="NORMAL",
        priority_score=0.2, route=route, team="Lending Servicing", reason=None, latency_ms=11,
        pii_redactions=1, pii_residual=0,
    )


def test_rows_feedback_and_correction_rate(tmp_path: Path) -> None:
    log = RequestLog(tmp_path / "sub" / "req.sqlite")
    assert log.record_request(row("r1"))
    assert log.record_request(row("r2", route="HUMAN_REVIEW"))
    assert log.record_request(row("r3"))
    fb = log.record_feedback("r1", {"product": "Debt collection"})
    assert fb.known_request is True
    log.record_feedback("r1", {"product": "Debt collection"})  # repeated: counted once
    log.record_feedback("r2", {"product": "Mortgage"})  # same as predicted: not a correction
    unknown = log.record_feedback("nope", {"team": "Card Operations"})
    assert unknown.known_request is False  # stored and flagged, no 404
    stats = log.correction_rate()
    assert stats["requests"] == 3
    assert stats["requests_with_feedback"] == 2
    assert stats["corrected"] == 1
    assert stats["correction_rate"] == pytest.approx(1 / 3)
    assert stats["corrected_by_field"] == {"product": 1, "issue": 0, "priority": 0, "team": 0}
    assert stats["feedback_unknown_request"] == 1
    assert stats["routes"] == {"AUTO": 2, "HUMAN_REVIEW": 1}
    assert log.correction_rate(since="2999-01-01")["requests"] == 0
    log.close()


def test_schema_has_no_text_column(tmp_path: Path) -> None:
    log = RequestLog(tmp_path / "req.sqlite")
    log.record_request(row("r1"))
    log.close()
    con = sqlite3.connect(tmp_path / "req.sqlite")
    cols = {r[1] for t in ("requests", "feedback")
            for r in con.execute(f"PRAGMA table_info({t})")}
    assert not cols & {"text", "narrative", "body", "raw_text"}
    assert "text_hash" in cols


def test_text_hash_salted() -> None:
    assert text_hash("a") != text_hash("a", salt="k")
    assert len(text_hash("a", salt="k")) == 64


def test_store_down_buffers_then_flushes(tmp_path: Path) -> None:
    calls = {"n": 0}
    fail = {"on": True}

    def connect(path: str) -> sqlite3.Connection:
        calls["n"] += 1
        if fail["on"]:
            raise sqlite3.OperationalError("unable to open database file")
        return sqlite3.connect(path, check_same_thread=False)

    log = RequestLog(tmp_path / "req.sqlite", buffer_max_rows=2, connect=connect)
    assert log.record_request(row("r1")) is False
    assert log.record_request(row("r2")) is False
    assert log.record_request(row("r3")) is False  # buffer full: oldest dropped
    assert (log.buffer_size, log.write_errors, log.dropped) == (2, 3, 1)
    assert log.known_request("r3") is None  # cannot answer while down
    fail["on"] = False
    assert log.record_request(row("r4")) is True  # flushes r2, r3 first
    assert log.buffer_size == 0
    assert log.correction_rate()["requests"] == 3
    assert log.known_request("r3") is True


def test_feedback_while_down_is_buffered_with_unknown_flag(tmp_path: Path) -> None:
    def connect(path: str) -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk I/O error")

    log = RequestLog(tmp_path / "x.sqlite", connect=connect)
    fb = log.record_feedback("r1", {"issue": "Fees or interest"})
    assert fb.known_request is None
    assert log.buffer_size == 1
    assert log.flush() == 1


def test_from_config_env_override_and_disabled(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(rl.PATH_ENV, ":memory:")
    monkeypatch.setenv("CIQ_TEST_SALT", "pepper")
    log = RequestLog.from_config({"enabled": True, "path": "ignored.sqlite",
                                  "salt_env": "CIQ_TEST_SALT"})
    assert log is not None and log.path == ":memory:" and log.salt == "pepper"
    assert log.record_request(row("r1"))
    assert RequestLog.from_config({"enabled": False}) is None
    monkeypatch.setenv(rl.PATH_ENV, str(tmp_path / "e.sqlite"))
    assert RequestLog.from_config({"enabled": True}).path == str(tmp_path / "e.sqlite")


def test_cli_stats_prints_aggregates_only(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    p = tmp_path / "req.sqlite"
    log = RequestLog(p)
    log.record_request(row("r1"))
    log.close()
    rl.main(["stats", "--path", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert out["requests"] == 1 and out["routes"] == {"AUTO": 1}


def test_unwritable_directory_is_buffered_not_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")  # a file where the log directory should be
    log = RequestLog(blocker / "sub" / "req.sqlite")
    assert log.record_request(row("r1")) is False
    assert (log.buffer_size, log.write_errors) == (1, 1)
    assert log.known_request("r1") is None
