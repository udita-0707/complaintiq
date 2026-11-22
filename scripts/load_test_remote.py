"""Concurrent load test of POST /v1/triage against a running API (M5, SPEC C11, C13 M5).

Closed loop: at each concurrency level, that many workers send requests back to back until
``n`` requests are done. Request bodies are SYNTHETIC complaints built from fixed templates
(no real narratives). Records client-side p50/p95/p99 latency, the server's ``latency_ms``,
throughput, status codes and error rate, writes ``reports/m5/results/load_test_<label>.json``,
re-renders ``reports/m5/load_test.md`` from every label present, and logs one run per level
in ``reports/experiments/m5/load_test.csv``.

The API's per-IP rate limit would turn a load test into a 429 test. Set ``CIQ_LOADTEST_TOKEN``
to the value of the API's ``COMPLAINTIQ_LOADTEST_TOKEN`` (a Space secret / compose env) to
skip it; 429s are counted either way.

Usage::

    python scripts/load_test_remote.py http://127.0.0.1:8000 --label local
    python scripts/load_test_remote.py https://<user>-complaintiq.hf.space --label public
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx2 as httpx

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "reports" / "m5" / "results"
REPORT = REPO / "reports" / "m5" / "load_test.md"
LABELS = ("local", "public")
TOKEN_ENV = "CIQ_LOADTEST_TOKEN"
TOKEN_HEADER = "x-ciq-loadtest-token"
TARGET_P95_MS = 300.0  # SPEC A5 / B7

OPENINGS = [
    "I am writing about my credit report.",
    "A debt collector keeps contacting me.",
    "My mortgage servicer has not responded.",
    "There is a charge on my credit card that I did not make.",
    "My checking account was closed without notice.",
    "I sent money through an app and it never arrived.",
    "My student loan servicer applied my payment incorrectly.",
]
DETAILS = [
    "I called customer service several times and was told someone would call me back.",
    "The account listed on my report does not belong to me and I have disputed it twice.",
    "They say I owe a balance that I already paid in full last year.",
    "I was charged late fees even though my payment was on time.",
    "I asked for written verification and never received it.",
    "The company keeps transferring me between departments without an answer.",
    "This has affected my ability to get a loan for a car.",
    "I have documents showing the payment was made on the due date.",
]
CLOSINGS = [
    "Please help me resolve this issue.",
    "I want the error corrected and the fees refunded.",
    "I would like the account removed from my report.",
    "I am asking the company to stop contacting me.",
]


def synthetic_texts(n: int, seed: int = 42) -> list[str]:
    """``n`` deterministic synthetic complaints (about 60-160 words each)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        parts = [rng.choice(OPENINGS), *rng.sample(DETAILS, rng.randint(3, 7)),
                 rng.choice(CLOSINGS)]
        out.append(" ".join(parts))
    return out


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (``q`` in 0-100); NaN-free inputs only."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(lat_ms: list[float], server_ms: list[float], statuses: list[int],
              routes: list[str], wall_s: float) -> dict[str, Any]:
    ok = [lat for lat, s in zip(lat_ms, statuses, strict=True) if s == 200]
    n = len(statuses)
    return {
        "n": n,
        "wall_s": wall_s,
        "throughput_rps": n / wall_s if wall_s > 0 else float("nan"),
        "status_counts": dict(Counter(statuses)),
        "error_rate": sum(1 for s in statuses if s != 200) / n if n else float("nan"),
        "client_ms": {"p50": percentile(ok, 50), "p95": percentile(ok, 95),
                      "p99": percentile(ok, 99), "mean": sum(ok) / len(ok) if ok else None,
                      "max": max(ok) if ok else None},
        "server_ms": {"p50": percentile(server_ms, 50), "p95": percentile(server_ms, 95),
                      "p99": percentile(server_ms, 99)},
        "routes": dict(Counter(routes)),
    }


async def run_level(client: httpx.AsyncClient, url: str, texts: list[str],
                    concurrency: int, headers: dict[str, str]) -> dict[str, Any]:
    queue: asyncio.Queue[str] = asyncio.Queue()
    for t in texts:
        queue.put_nowait(t)
    lat_ms: list[float] = []
    server_ms: list[float] = []
    statuses: list[int] = []
    routes: list[str] = []

    async def worker() -> None:
        while True:
            try:
                text = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            t0 = time.perf_counter()
            try:
                r = await client.post(f"{url}/v1/triage", json={"text": text}, headers=headers)
                status = r.status_code
            except httpx.HTTPError:
                status, r = 0, None
            lat_ms.append((time.perf_counter() - t0) * 1000)
            statuses.append(status)
            if status == 200 and r is not None:
                body = r.json()
                server_ms.append(float(body["latency_ms"]))
                routes.append(body["route"])

    start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return {"concurrency": concurrency, **summarize(lat_ms, server_ms, statuses, routes,
                                                    time.perf_counter() - start)}


async def wait_healthy(client: httpx.AsyncClient, url: str, wait_s: float) -> float:
    """Seconds until /health reports a loaded model (raises after ``wait_s``)."""
    start = time.perf_counter()
    while True:
        try:
            r = await client.get(f"{url}/health")
            if r.status_code == 200 and r.json().get("model_loaded"):
                return time.perf_counter() - start
        except httpx.HTTPError:
            pass
        if time.perf_counter() - start > wait_s:
            raise SystemExit(f"{url}/health not healthy after {wait_s:.0f} s")
        await asyncio.sleep(2.0)


async def run(url: str, label: str, levels: list[int], n: int, warmup: int,
              timeout_s: float, wait_s: float) -> dict[str, Any]:
    token = os.environ.get(TOKEN_ENV, "")
    headers = {TOKEN_HEADER: token} if token else {}
    limits = httpx.Limits(max_connections=max(levels), max_keepalive_connections=max(levels))
    async with httpx.AsyncClient(timeout=timeout_s, limits=limits) as client:
        healthy_after = await wait_healthy(client, url, wait_s)
        model = (await client.get(f"{url}/v1/model")).json()
        for t in synthetic_texts(warmup, seed=7):
            await client.post(f"{url}/v1/triage", json={"text": t}, headers=headers)
        results = [await run_level(client, url, synthetic_texts(n, seed=42 + c), c, headers)
                   for c in levels]
    return {"label": label, "url_kind": label, "n_per_level": n, "warmup": warmup,
            "bypass_token_used": bool(token), "healthy_after_s": healthy_after,
            "model_version": model.get("model_version"), "predictor": model.get("predictor"),
            "thresholds": model.get("thresholds"), "levels": results,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _fmt(v: Any, d: int = 1) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return f"{v:.{d}f}" if isinstance(v, float) else str(v)


def render(results: dict[str, dict[str, Any]]) -> str:
    """Markdown report from the per-label JSON results (TODO for labels not run yet)."""
    out = [
        "# M5 load test (POST /v1/triage, concurrent)",
        "",
        "Generated by `python scripts/load_test_remote.py` (`make load-test-remote`). Closed "
        "loop: at each concurrency level that many clients send requests back to back. Request "
        "bodies are synthetic template complaints (no real narratives); the route mix on them "
        "is not a coverage estimate (coverage is in reports/m4/calibration_report.md). Raw "
        "numbers: `reports/m5/results/load_test_<label>.json`; runs logged in "
        "`reports/experiments/m5/load_test.csv`.",
        "",
    ]
    for label in LABELS:
        res = results.get(label)
        title = "local container (docker compose, same machine)" if label == "local" else \
            "public URL (Hugging Face Space, free CPU)"
        out += [f"## {label}: {title}", ""]
        if not res or not res.get("levels"):
            cmd = ("make serve-up, then make load-test-remote URL=http://127.0.0.1:8000 "
                   "LABEL=local" if label == "local" else
                   "make load-test-remote URL=https://<user>-complaintiq.hf.space LABEL=public")
            out += [f"TODO: not run yet ({cmd}).", ""]
            continue
        out += [
            f"- model_version `{res['model_version']}` ({res['predictor']}); {res['n_per_level']} "
            f"requests per level after {res['warmup']} warm-up requests; rate-limit bypass token "
            f"{'used' if res['bypass_token_used'] else 'not used'}; healthy after "
            f"{_fmt(res['healthy_after_s'])} s; run at {res['timestamp_utc']}.",
            "",
            "| concurrency | client p50 ms | client p95 ms | client p99 ms | server p95 ms | "
            "throughput req/s | error rate | status counts | run_id |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for lv in res["levels"]:
            c = lv["client_ms"]
            out.append(
                f"| {lv['concurrency']} | {_fmt(c['p50'])} | {_fmt(c['p95'])} | "
                f"{_fmt(c['p99'])} | {_fmt(lv['server_ms']['p95'])} | "
                f"{_fmt(lv['throughput_rps'])} | {_fmt(lv['error_rate'], 4)} | "
                f"{lv['status_counts']} | {lv.get('run_id', '')} |")
        worst = max((lv["client_ms"]["p95"] or 0.0) for lv in res["levels"])
        verdict = "meets" if worst <= TARGET_P95_MS else "MISSES"
        out += ["", f"SPEC B7 target p95 <= {TARGET_P95_MS:.0f} ms: worst client p95 "
                f"{_fmt(worst)} ms across levels ({verdict}).", ""]
    return "\n".join(out)


def load_results() -> dict[str, dict[str, Any]]:
    out = {}
    for label in LABELS:
        p = RESULTS / f"load_test_{label}.json"
        if p.is_file():
            out[label] = json.loads(p.read_text())
    return out


def log_levels(res: dict[str, Any]) -> None:
    """One experiment-log row per level (needs the serve extra for complaintiq imports)."""
    sys.path.insert(0, str(REPO / "src"))
    from complaintiq.eval.tracking import log_run

    for lv in res["levels"]:
        lv["run_id"] = log_run(
            "load_test", experiments_dir=REPO / "reports" / "experiments" / "m5",
            model=res["model_version"], task=f"load_test_{res['label']}",
            hyperparams={"concurrency": lv["concurrency"], "n": lv["n"],
                         "warmup": res["warmup"], "bypass_token": res["bypass_token_used"]},
            owner="team-m5-session",
            notes=(f"load test {res['label']}; c={lv['concurrency']}; "
                   f"p95_ms={_fmt(lv['client_ms']['p95'])}; rps={_fmt(lv['throughput_rps'])}; "
                   f"error_rate={_fmt(lv['error_rate'], 4)}"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--label", choices=LABELS, required=True)
    ap.add_argument("--concurrency", default="1,5,10")
    ap.add_argument("--n", type=int, default=200, help="requests per concurrency level")
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--wait", type=float, default=300.0, help="max seconds to wait for /health")
    ap.add_argument("--no-log", action="store_true", help="do not append experiment-log rows")
    args = ap.parse_args(argv)
    levels = [int(x) for x in args.concurrency.split(",")]
    res = asyncio.run(run(args.url.rstrip("/"), args.label, levels, args.n, args.warmup,
                          args.timeout, args.wait))
    if not args.no_log:
        log_levels(res)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"load_test_{args.label}.json").write_text(
        json.dumps(res, indent=2, sort_keys=True) + "\n")
    REPORT.write_text(render(load_results()))
    for lv in res["levels"]:
        print(f"c={lv['concurrency']}: p95 {_fmt(lv['client_ms']['p95'])} ms, "
              f"{_fmt(lv['throughput_rps'])} req/s, errors {_fmt(lv['error_rate'], 4)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
