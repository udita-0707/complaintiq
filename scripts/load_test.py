"""Sequential load test of POST /v1/triage against a locally started API (M4, SPEC C11).

Starts uvicorn on 127.0.0.1 with a temporary copy of ``configs/`` in which
``model.yaml: predictor`` is ``baseline`` (the repo's configs are not changed), waits for
``/health``, sends ``n_requests`` sequential requests with SYNTHETIC complaint texts
(templates below, no real narratives), and writes p50/p95 latency to
``reports/m4/api_latency.md``. Only aggregates are printed.

Usage::

    python scripts/load_test.py [--n 200] [--predictor baseline]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]

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


def synthetic_texts(n: int, seed: int) -> list[str]:
    """``n`` deterministic synthetic complaints of roughly 60-160 words."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        parts = [OPENINGS[rng.integers(len(OPENINGS))]]
        parts += [DETAILS[i] for i in rng.choice(len(DETAILS), size=rng.integers(3, 8))]
        parts.append(CLOSINGS[rng.integers(len(CLOSINGS))])
        out.append(" ".join(parts))
    return out


def percentiles(ms: list[float]) -> dict[str, float]:
    """p50/p95/p99/mean/max in milliseconds."""
    a = np.asarray(ms)
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "mean": float(a.mean()), "max": float(a.max())}


def _config_dir(predictor: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="ciq_loadtest_"))
    for f in (REPO / "configs").glob("*.yaml"):
        shutil.copy(f, d / f.name)
    model = yaml.safe_load((d / "model.yaml").read_text())
    model["predictor"] = predictor
    (d / "model.yaml").write_text(yaml.safe_dump(model, sort_keys=False))
    return d


def run(n: int, predictor: str) -> dict[str, Any]:
    """Start the API, send ``n`` sequential requests, stop the API, return aggregates."""
    sys.path.insert(0, str(REPO / "src"))
    from complaintiq.config import load_config

    lcfg = load_config("eval")["load_test"]
    host, port = lcfg["host"], int(lcfg["port"])
    cfg_dir = _config_dir(predictor)
    env = {**os.environ, "COMPLAINTIQ_CONFIG_DIR": str(cfg_dir),
           "PYTHONPATH": str(REPO / "src")}
    cmd = [sys.executable, "-m", "uvicorn", "complaintiq.serving.app:app", "--host", host,
           "--port", str(port), "--log-level", "warning"]
    server = subprocess.Popen(cmd, cwd=REPO, env=env)
    base = f"http://{host}:{port}"
    try:
        t0 = time.perf_counter()
        with httpx.Client(timeout=30) as client:
            while True:
                try:
                    if client.get(f"{base}/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if server.poll() is not None or time.perf_counter() - t0 > 120:
                    raise RuntimeError("API did not start")
                time.sleep(0.25)
            startup_s = time.perf_counter() - t0
            info = client.get(f"{base}/v1/model").json()
            texts = synthetic_texts(n + 10, seed=int(load_config("eval")["seed"]))
            for t in texts[:10]:  # warm-up, not timed
                client.post(f"{base}/v1/triage", json={"text": t})
            client_ms, server_ms, routes, codes = [], [], {}, {}
            for t in texts[10:]:
                s = time.perf_counter()
                r = client.post(f"{base}/v1/triage", json={"text": t})
                client_ms.append((time.perf_counter() - s) * 1000)
                codes[r.status_code] = codes.get(r.status_code, 0) + 1
                if r.status_code == 200:
                    body = r.json()
                    server_ms.append(float(body["latency_ms"]))
                    routes[body["route"]] = routes.get(body["route"], 0) + 1
    finally:
        server.terminate()
        server.wait(timeout=30)
        shutil.rmtree(cfg_dir, ignore_errors=True)
    return {"n": n, "predictor_requested": predictor, "model": info, "startup_s": startup_s,
            "client_ms": percentiles(client_ms), "server_ms": percentiles(server_ms),
            "status_codes": codes, "routes": routes, "host": host, "port": port}


def write_report(res: dict[str, Any], path: Path) -> None:
    """Markdown report for the load test."""
    c, s, m = res["client_ms"], res["server_ms"], res["model"]
    out = [
        "# M4 API latency (local load test)",
        "",
        "Generated by `python scripts/load_test.py` (`make load-test`). Raw numbers:"
        " `reports/m4/results/api_latency.json`.",
        "",
        f"- {res['n']} **sequential** POST /v1/triage requests (after 10 untimed warm-up"
        f" requests) against uvicorn on {res['host']}, one worker, same machine as the client.",
        "- Request bodies are **synthetic** complaint texts generated from fixed templates"
        " (seeded); no real narratives.",
        f"- Predictor in use: `{m['predictor']}`, model_version `{m['model_version']}`;"
        f" thresholds {json.dumps(m['thresholds'])}.",
        f"- Status codes: {res['status_codes']}; routes: {res['routes']}. The route mix on"
        " template text is NOT a coverage estimate (coverage on val-B is in"
        " `reports/m4/calibration_report.md`); it only shows both gate paths were exercised.",
        f"- API startup (process start to healthy /health, includes model load):"
        f" {res['startup_s']:.1f} s.",
        "",
        "| measured at | p50 ms | p95 ms | p99 ms | mean ms | max ms |",
        "|---|---|---|---|---|---|",
        f"| client (HTTP round trip) | {c['p50']:.1f} | {c['p95']:.1f} | {c['p99']:.1f} |"
        f" {c['mean']:.1f} | {c['max']:.1f} |",
        f"| server (`latency_ms` field, integer ms) | {s['p50']:.1f} | {s['p95']:.1f} |"
        f" {s['p99']:.1f} | {s['mean']:.1f} | {s['max']:.1f} |",
        "",
        f"SPEC B7 target p95 <= 300 ms on CPU: client p95 {c['p95']:.1f} ms"
        f" ({'meets' if c['p95'] <= 300 else 'misses'}). Sequential requests measure latency,"
        " not capacity under concurrency (TODO for M5: concurrent load with locust or hey on"
        " the deployed URL).",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")


def main() -> None:
    """Command-line entry point."""
    sys.path.insert(0, str(REPO / "src"))
    from complaintiq.config import load_config

    lcfg = load_config("eval")["load_test"]
    ap = argparse.ArgumentParser(prog="scripts/load_test.py")
    ap.add_argument("--n", type=int, default=lcfg["n_requests"])
    ap.add_argument("--predictor", default="baseline", choices=["baseline", "stub"])
    args = ap.parse_args()
    res = run(args.n, args.predictor)
    out = REPO / "reports" / "m4" / "results" / "api_latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True))
    write_report(res, REPO / lcfg["report_path"])
    print(json.dumps({"client_ms": res["client_ms"], "status_codes": res["status_codes"]},
                     indent=2))


if __name__ == "__main__":
    main()
