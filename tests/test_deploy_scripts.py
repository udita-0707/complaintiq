"""M5 deployment scripts and the UI client (synthetic only; no Docker, no network).

The HTTP failure scenarios run in-process against the wired app with a fake predictor; the
Docker scenarios and the real load test run on a machine with Docker (docs/deployment.md).
"""

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_space  # noqa: E402
import ciq_client  # noqa: E402
import deployment_report  # noqa: E402
import failure_tests  # noqa: E402
import load_test_remote as lt  # noqa: E402

from complaintiq.serving.app import app  # noqa: E402
from complaintiq.serving.security import TokenBucketLimiter  # noqa: E402
from test_api_runtime import SpyPredictor, services  # noqa: E402

# ------------------------------------------------------------------ build_space


def test_synthetic_api_staging_layout(tmp_path: Path) -> None:
    out = tmp_path / "space"
    info = build_space.stage_api(out, None, synthetic=True)
    rel = build_space._yaml("final_model")["model_dir"]
    for f in ("Dockerfile", "README.md", ".gitattributes", "pyproject.toml",
              "configs/thresholds.yaml", "src/complaintiq/serving/app.py"):
        assert (out / f).is_file(), f
    for f in build_space.TASK_FILES:
        assert (out / rel / f).is_file()
    assert not list(out.rglob("__pycache__"))
    assert "lfs" in (out / ".gitattributes").read_text()
    assert info["manifest"].startswith("skipped")
    build_space.stage_api(out, None, synthetic=True)  # re-staging its own dir is fine


def test_refuses_foreign_output_dir(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("mine")
    with pytest.raises(build_space.BuildError):
        build_space._fresh_dir(tmp_path)


def _fake_frozen_model(d: Path, version: str) -> Path:
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"model_version": version, "tasks": []}))
    for f in build_space.TASK_FILES[1:]:
        (d / f).write_bytes(b"stand-in " + f.encode())
    return d


def test_frozen_checks_and_manifest(tmp_path: Path) -> None:
    final = build_space._yaml("final_model")
    with pytest.raises(build_space.BuildError, match="lacks"):
        build_space.check_frozen(tmp_path / "missing")
    bad = _fake_frozen_model(tmp_path / "bad", "some-other-version")
    with pytest.raises(build_space.BuildError, match="model_version"):
        build_space.check_frozen(bad)
    good = _fake_frozen_model(tmp_path / "good", final["model_version"])
    found = build_space.check_frozen(good)
    assert found["model_version"] == final["model_version"] and len(found["files"]) == 5
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"status": "TODO", "files": {}}))
    assert build_space.check_manifest(found, manifest) == "written"
    assert build_space.check_manifest(found, manifest) == "verified"
    (good / "issue.joblib").write_bytes(b"tampered")
    with pytest.raises(build_space.BuildError, match="issue.joblib"):
        build_space.check_manifest(build_space.check_frozen(good), manifest)


def test_repo_manifest_is_a_placeholder_or_complete() -> None:
    m = json.loads(build_space.MANIFEST.read_text())
    assert m.get("files") == {} or len(m["files"]) >= 5


def test_serve_requirements_are_pinned() -> None:
    reqs = build_space.serve_requirements()
    assert all("==" in r for r in reqs)
    assert any(r.startswith("scikit-learn==") for r in reqs)
    assert any(r.startswith("prometheus-client==") for r in reqs)


# ------------------------------------------------------------------ load test


def test_synthetic_texts_pass_the_quality_check() -> None:
    from complaintiq.config import load_config
    from complaintiq.serving.input_quality import assess

    texts = lt.synthetic_texts(20)
    assert texts == lt.synthetic_texts(20)
    cfg = load_config("safety")["input_quality"]
    assert all(assess(t, cfg).ok for t in texts)


def test_percentile_summary_and_render() -> None:
    assert lt.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    s = lt.summarize([10.0, 20.0, 30.0], [5.0, 6.0], [200, 200, 429], ["AUTO", "AUTO"], 1.5)
    assert s["error_rate"] == pytest.approx(1 / 3) and s["status_counts"] == {200: 2, 429: 1}
    assert s["client_ms"]["max"] == 20.0  # only successful requests count for latency
    md = lt.render({})
    assert md.count("TODO: not run yet") == 2
    res = {"model_version": "v", "predictor": "baseline", "n_per_level": 3, "warmup": 0,
           "bypass_token_used": True, "healthy_after_s": 0.1, "timestamp_utc": "t",
           "levels": [{"concurrency": 1, **s}]}
    md = lt.render({"local": res})
    assert "| 1 |" in md and "meets" in md and md.count("TODO: not run yet") == 1


# ------------------------------------------------------------------ failure tests


def test_http_failure_scenarios_all_pass_in_process() -> None:
    app.state.services = services(SpyPredictor(),
                                  limiter=TokenBucketLimiter(requests_per_minute=1, burst=30))
    try:
        with TestClient(app) as c:
            def req(method: str, path: str, **kw):
                r = c.request(method, path, **kw)
                try:
                    body = r.json()
                except ValueError:
                    body = None
                return failure_tests.Resp(r.status_code, body, r.text, 0.0)

            rows = failure_tests.http_scenarios(req)
    finally:
        del app.state.services
    failed = [r.scenario for r in rows if not r.passed]
    assert not failed, failed
    assert len(rows) == 11
    md = failure_tests.render({"url": {"target": "in-process", "model_version": "spy-1",
                                       "timestamp_utc": "t",
                                       "rows": [r.__dict__ for r in rows]}})
    assert "11 of 11 passed" in md and "TODO" in md  # docker block still TODO


# ------------------------------------------------------------------ deployment report


def test_deployment_render_todo_and_filled() -> None:
    md = deployment_report.render({})
    assert "Public API URL: TODO" in md
    filled = deployment_report.render({"public": {
        "url": "https://u-complaintiq.hf.space", "ui_url": "https://u-complaintiq-ui.hf.space",
        "git_commit": "abc", "model_version": "m-cal", "thresholds": {"tau": 0.8},
        "cold_start_s": 31.2, "rss_mb": 240.0}})
    assert "https://u-complaintiq.hf.space" in filled and "| public | abc |" in filled


# ------------------------------------------------------------------ UI client

RESULT = {"request_id": "r1", "product": {"label": "Mortgage", "confidence": 0.9},
          "issue_top3": [{"label": "Struggling to pay mortgage", "p": 0.7}],
          "priority": {"label": "NORMAL", "score": 0.1}, "team": "Lending Servicing",
          "route": "AUTO", "reason": None}


def test_feedback_payload_sends_only_changes() -> None:
    p = ciq_client.feedback_payload(RESULT, product="Debt collection",
                                    issue="Struggling to pay mortgage", priority="NORMAL",
                                    team="Lending Servicing")
    assert p == {"request_id": "r1", "product": "Debt collection"}
    with pytest.raises(ValueError):
        ciq_client.feedback_payload(RESULT, "Mortgage", "", "NORMAL", "")


def test_explanations_and_error_messages() -> None:
    assert "automatically" in ciq_client.explain(RESULT)
    assert "English" in ciq_client.explain({**RESULT, "reason": "non_english"})
    assert "sleeps" in ciq_client.error_message(ciq_client.ApiError(0, "x"))
    assert "Wait a minute" in ciq_client.error_message(ciq_client.ApiError(429, "x"))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_client_calls_and_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_ok(req, timeout):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        return _Resp(json.dumps({"route": "AUTO"}).encode())

    monkeypatch.setenv(ciq_client.API_URL_ENV, "https://api.example/")
    monkeypatch.setattr(ciq_client.urllib.request, "urlopen", fake_ok)
    assert ciq_client.triage("some text") == {"route": "AUTO"}
    assert seen == {"url": "https://api.example/v1/triage", "body": {"text": "some text"}}

    def fake_err(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"detail": "text must be 20-10000"}'))

    monkeypatch.setattr(ciq_client.urllib.request, "urlopen", fake_err)
    with pytest.raises(ciq_client.ApiError) as e:
        ciq_client.triage("x")
    assert e.value.status == 400 and "20-10000" in e.value.detail

    def fake_down(req, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(ciq_client.urllib.request, "urlopen", fake_down)
    with pytest.raises(ciq_client.ApiError) as e:
        ciq_client.model_info()
    assert e.value.status == 0
