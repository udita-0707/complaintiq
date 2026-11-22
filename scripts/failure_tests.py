"""Failure tests for the deployed API (M5, SPEC C8, C10, C11).

Two modes, which can run together; each writes its rows into
``reports/m5/results/failure_tests.json`` (rows of the other mode are kept) and the report
``reports/m5/failure_tests.md`` is re-rendered from both:

- ``--url URL``: scenarios over HTTP against a running API (length limits, schema error,
  short / gibberish / non-English text, PII in input, oversized body, rate limit, feedback
  for an unknown request).
- ``--docker-image IMAGE``: scenarios that need a different container environment, each in
  a fresh container on a free local port: model missing (load-time chain ends in 503),
  injected inference failure, injected 3 s delay (timeout), unwritable request log (store
  down), and a scan of the container logs for PII and text after a PII request. Uses the
  test hooks in ``serving/runtime.py``, which only exist when
  ``COMPLAINTIQ_ENABLE_TEST_HOOKS=1``.

All texts are synthetic. Nothing prints or stores complaint text; the log scan only reports
whether a planted string was found.

Usage::

    python scripts/failure_tests.py --url http://127.0.0.1:8000 \
        --docker-image complaintiq-serve:local
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "reports" / "m5" / "results" / "failure_tests.json"
REPORT = REPO / "reports" / "m5" / "failure_tests.md"

LONG_EN = ("A debt collector keeps calling me about a debt I do not owe. I asked them to send "
           "written proof of the debt and they never did, but the calls continue every day at "
           "work and at home.")
SHORT_EN = "My bank charged me the same fee twice this month."
GIBBERISH = "asdf qwer zxcv sdfghjkl asdf qwer zxcv lkjh mnbv asdf qwer zxcv poiu"
SPANISH = ("Me están cobrando una deuda que no debo y llaman todos los días a mi trabajo, ya les "
           "dije que no es mía y siguen llamando sin parar por favor ayuda")
PII = ["jane.doe@example.com", "(555) 010-4477", "078-05-1120", "4111 1111 1111 1111"]
PII_TEXT = LONG_EN + " You can reach me at " + ", ".join(PII) + "."
PLANTED = "calls continue every day at work and at home"  # must never appear in logs


@dataclass
class Resp:
    status: int
    body: Any
    text: str
    elapsed_ms: float


@dataclass
class Row:
    c8: str
    scenario: str
    expected: str
    status: int | None
    route: str | None
    reason: str | None
    observed: str
    passed: bool


class HttpClient:
    """Minimal sync client (httpx2) returning :class:`Resp`."""

    def __init__(self, base: str, timeout: float = 30.0) -> None:
        import httpx2

        self.base = base.rstrip("/")
        self._c = httpx2.Client(timeout=timeout)

    def request(self, method: str, path: str, **kw: Any) -> Resp:
        t0 = time.perf_counter()
        r = self._c.request(method, self.base + path, **kw)
        ms = (time.perf_counter() - t0) * 1000
        try:
            body = r.json()
        except ValueError:
            body = None
        return Resp(r.status_code, body, r.text, ms)

    def close(self) -> None:
        self._c.close()


Requester = Callable[..., Resp]


def metric_sum(req: Requester, name: str) -> float:
    total = 0.0
    for line in req("GET", "/metrics").text.splitlines():
        if line.startswith(name + " ") or line.startswith(name + "{"):
            total += float(line.rsplit(" ", 1)[1])
    return total


def _triage(req: Requester, text: str, **kw: Any) -> Resp:
    return req("POST", "/v1/triage", json={"text": text}, **kw)


def _row(c8: str, scenario: str, expected: str, r: Resp, ok: bool, note: str = "") -> Row:
    body = r.body if isinstance(r.body, dict) else {}
    observed = f"{r.status}" + (f" {body.get('route')}" if body.get("route") else "")
    observed += f" reason={body['reason']}" if body.get("reason") else ""
    observed += f"; {note}" if note else ""
    return Row(c8, scenario, expected, r.status, body.get("route"), body.get("reason"),
               observed, ok)


def http_scenarios(req: Requester, rate_limit: bool = True, burst_max: int = 40) -> list[Row]:
    """Scenarios that need only HTTP access to a running API."""
    rows: list[Row] = []
    for name, text in (("empty text", ""), ("9 characters", "too short"),
                       ("10,001 characters", "x" * 10_001)):
        r = _triage(req, text)
        rows.append(_row("Empty/short text (FR1)", name, "400", r, r.status == 400))
    r = req("POST", "/v1/triage", json={})
    rows.append(_row("Schema error (C7)", "missing text field", "422", r, r.status == 422))
    for c8, name, text, reason in (
        ("Short text", "11 words (< 20 trained minimum)", SHORT_EN, "short_text"),
        ("Gibberish text", "keyboard mashing", GIBBERISH, "low_quality_text"),
        ("Non-English text", "Spanish complaint", SPANISH, "non_english"),
    ):
        r = _triage(req, text)
        ok = r.status == 200 and r.body["route"] == "HUMAN_REVIEW" and r.body["reason"] == reason
        rows.append(_row(c8, name, f"200 HUMAN_REVIEW reason={reason}", r, ok))
    before = (metric_sum(req, "ciq_pii_redactions_total"),
              metric_sum(req, "ciq_pii_residual_total"))
    r = _triage(req, PII_TEXT)
    red = metric_sum(req, "ciq_pii_redactions_total") - before[0]
    res = metric_sum(req, "ciq_pii_residual_total") - before[1]
    echoed = any(p in r.text for p in PII)
    ok = r.status == 200 and red == len(PII) and res == 0 and not echoed
    rows.append(_row("PII detected (FR2, C8)", f"{len(PII)} synthetic PII strings",
                     f"200; {len(PII)} redactions, 0 residual, nothing echoed", r, ok,
                     f"redactions +{red:.0f}, residual +{res:.0f}, echoed={echoed}"))
    r = req("POST", "/v1/triage", content=b'{"text": "' + b"a" * 200_000 + b'"}',
            headers={"content-type": "application/json"})
    rows.append(_row("Input size limit (C10)", "200 KB body", "413", r, r.status == 413))
    r = req("POST", "/v1/feedback", json={"request_id": "never-issued-id", "product": "Mortgage"})
    rows.append(_row("Feedback for unknown request (US4)", "unknown request_id",
                     "200 accepted, stored and flagged", r,
                     r.status == 200 and r.body.get("status") == "accepted"))
    if rate_limit:
        codes = []
        last = None
        for _ in range(burst_max):
            last = req("POST", "/v1/feedback", json={"request_id": "rl", "team": "x"})
            codes.append(last.status)
            if last.status == 429:
                break
        rows.append(_row("Rate limiting (C10)", f"up to {burst_max} rapid feedback calls",
                         "429 with Retry-After", last, 429 in codes,
                         f"first 429 after {codes.index(429) + 1 if 429 in codes else '-'} "
                         "requests"))
    return rows


# --------------------------------------------------------------------------- docker mode


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Container:
    """A throwaway container of IMAGE with extra env, published on a free local port."""

    def __init__(self, image: str, env: dict[str, str], port: int = 7860) -> None:
        self.image, self.env, self.inner_port = image, env, port
        self.host_port = _free_port()
        self.cid = ""

    def __enter__(self) -> Container:
        cmd = ["docker", "run", "-d", "--rm", "-p", f"127.0.0.1:{self.host_port}:{self.inner_port}"]
        for k, v in self.env.items():
            cmd += ["-e", f"{k}={v}"]
        self.cid = subprocess.run([*cmd, self.image], capture_output=True, text=True,
                                  check=True).stdout.strip()
        client = HttpClient(f"http://127.0.0.1:{self.host_port}")
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if client.request("GET", "/health").status == 200:
                    break
            except Exception:  # not up yet
                pass
            time.sleep(1)
        client.close()
        return self

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"

    def logs(self) -> str:
        return subprocess.run(["docker", "logs", self.cid], capture_output=True,
                              text=True).stdout + \
            subprocess.run(["docker", "logs", self.cid], capture_output=True, text=True).stderr

    def __exit__(self, *exc: Any) -> None:
        subprocess.run(["docker", "stop", self.cid], capture_output=True)


HOOKS = {"COMPLAINTIQ_ENABLE_TEST_HOOKS": "1"}


def docker_scenarios(image: str) -> list[Row]:
    rows: list[Row] = []
    with Container(image, {"COMPLAINTIQ_ROOT": "/tmp/no-model-here"}) as c:
        cl = HttpClient(c.url)
        h = cl.request("GET", "/health")
        r = _triage(cl.request, LONG_EN)
        ok = h.body.get("status") == "degraded" and r.status == 503
        rows.append(_row("Model load error (C8)", "model directory missing",
                         "/health degraded, triage 503 (no stub in deployment)", r, ok,
                         f"health={h.body.get('status')}"))
        cl.close()
    with Container(image, {**HOOKS, "COMPLAINTIQ_TEST_FAIL_PRIMARY": "1"}) as c:
        cl = HttpClient(c.url)
        r = _triage(cl.request, LONG_EN)
        errs = metric_sum(cl.request, "ciq_model_errors_total")
        rows.append(_row("Inference error (C8)", "injected predictor failure",
                         "503 (no runtime fallback behind the baseline); error counted", r,
                         r.status == 503 and errs >= 1, f"ciq_model_errors_total={errs:.0f}"))
        cl.close()
    with Container(image, {**HOOKS, "COMPLAINTIQ_TEST_DELAY_S": "3"}) as c:
        cl = HttpClient(c.url)
        r = _triage(cl.request, LONG_EN)
        ok = (r.status == 200 and r.body["reason"] == "timeout"
              and r.body["route"] == "HUMAN_REVIEW" and r.elapsed_ms < 3000)
        rows.append(_row("Timeout > 2 s (C8)", "injected 3 s model delay",
                         "200 HUMAN_REVIEW reason=timeout within ~2 s", r, ok,
                         f"client {r.elapsed_ms:.0f} ms"))
        cl.close()
    with Container(image, {"COMPLAINTIQ_REQUEST_LOG": "/proc/ciq/requests.sqlite"}) as c:
        cl = HttpClient(c.url)
        r1, r2 = _triage(cl.request, LONG_EN), _triage(cl.request, LONG_EN)
        buf = metric_sum(cl.request, "ciq_request_log_buffer_rows")
        rows.append(_row("Log store down (C8)", "request log path not writable",
                         "200 responses; rows buffered and counted", r2,
                         r1.status == r2.status == 200 and buf >= 2,
                         f"ciq_request_log_buffer_rows={buf:.0f}"))
        cl.close()
    with Container(image, {}) as c:
        cl = HttpClient(c.url)
        r = _triage(cl.request, PII_TEXT)
        time.sleep(1)
        logs = c.logs()
        leaked = [p for p in PII if p in logs] + ([PLANTED] if PLANTED in logs else [])
        rows.append(_row("No raw text in logs (C10, US5)", "container logs after a PII request",
                         "no PII and no text in docker logs", r, r.status == 200 and not leaked,
                         f"planted strings found in logs: {len(leaked)}"))
        cl.close()
    return rows


# --------------------------------------------------------------------------- report


def render(data: dict[str, Any]) -> str:
    out = [
        "# M5 failure tests (SPEC C8, C10)",
        "",
        "Generated by `python scripts/failure_tests.py` (`make failure-tests`). Every text is "
        "synthetic; the log scan reports only whether planted strings were found. Raw results: "
        "`reports/m5/results/failure_tests.json`; runs logged in "
        "`reports/experiments/m5/failure_tests.csv`.",
        "",
    ]
    for mode, title in (("url", "Over HTTP"), ("docker", "Injected container failures")):
        block = data.get(mode) or {}
        rows = block.get("rows") or []
        out += [f"## {title}", ""]
        if not rows:
            out += ["TODO: not run yet (`make failure-tests URL=http://127.0.0.1:8000 "
                    "IMAGE=complaintiq-serve:local`).", ""]
            continue
        out += [f"Target: `{block.get('target')}`; model_version `{block.get('model_version')}`; "
                f"run at {block.get('timestamp_utc')}.", "",
                "| C8 / spec row | scenario | expected | observed | pass |",
                "|---|---|---|---|---|"]
        out += [f"| {r['c8']} | {r['scenario']} | {r['expected']} | {r['observed']} | "
                f"{'yes' if r['passed'] else 'NO'} |" for r in rows]
        n_ok = sum(r["passed"] for r in rows)
        out += ["", f"{n_ok} of {len(rows)} passed.", ""]
    out += [
        "Not covered here: non-English detection is a stopword heuristic (src/complaintiq/"
        "serving/input_quality.py), so it can miss languages close to English; the runtime "
        "fallback to the baseline only exists behind a transformer, which is not deployed "
        "(the transformer and ONNX path stayed TODO in M4).",
        "",
    ]
    return "\n".join(out)


def _model_version(req: Requester) -> str:
    try:
        return str(req("GET", "/v1/model").body.get("model_version"))
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="C8 failure tests")
    ap.add_argument("--url", help="running API, e.g. http://127.0.0.1:8000")
    ap.add_argument("--docker-image", help="serve image, e.g. complaintiq-serve:local")
    ap.add_argument("--no-rate-limit", action="store_true", help="skip the 429 scenario")
    ap.add_argument("--no-log", action="store_true")
    args = ap.parse_args(argv)
    if not args.url and not args.docker_image:
        ap.error("give --url and/or --docker-image")
    data = json.loads(RESULTS.read_text()) if RESULTS.is_file() else {}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if args.url:
        cl = HttpClient(args.url)
        rows = http_scenarios(cl.request, rate_limit=not args.no_rate_limit)
        data["url"] = {"target": args.url, "model_version": _model_version(cl.request),
                       "timestamp_utc": stamp, "rows": [asdict(r) for r in rows]}
        cl.close()
    if args.docker_image:
        rows = docker_scenarios(args.docker_image)
        data["docker"] = {"target": args.docker_image, "model_version": "see /v1/model",
                          "timestamp_utc": stamp, "rows": [asdict(r) for r in rows]}
    if not args.no_log:
        sys.path.insert(0, str(REPO / "src"))
        from complaintiq.eval.tracking import log_run

        for mode in ("url", "docker"):
            if (args.url if mode == "url" else args.docker_image) and data.get(mode):
                rows = data[mode]["rows"]
                data[mode]["run_id"] = log_run(
                    "failure_tests", experiments_dir=REPO / "reports" / "experiments" / "m5",
                    model=data[mode]["model_version"], task=f"failure_tests_{mode}",
                    owner="team-m5-session",
                    notes=f"failure tests {mode}; passed {sum(r['passed'] for r in rows)}/"
                          f"{len(rows)}; target {data[mode]['target']}")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    REPORT.write_text(render(data))
    failed = [r for m in ("url", "docker") for r in (data.get(m) or {}).get("rows", [])
              if not r["passed"]]
    print(f"failure tests written to {REPORT.relative_to(REPO)}; failed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
