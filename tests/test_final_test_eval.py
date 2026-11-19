"""Guards of scripts/final_test_eval.py. Never reads data: the test split stays closed."""

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("final_test_eval",
                                               REPO / "scripts" / "final_test_eval.py")
fte = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fte)  # type: ignore[union-attr]

TH = {"tau": 0.8, "temperature_product": 0.9, "temperature_issue": 0.8,
      "priority_threshold": 0.4}
FINAL = {"model_id": "baseline/x", "model_dir": "models/baseline/x", "model_version": "mv",
         "data_version": "dv", "run_ids": {"product": "a"}, "thresholds": dict(TH),
         "frozen_date": "2026-12-01", "frozen_by": "team"}
META = {"model_version": "mv", "data_version": "dv", "tasks": ["product", "issue", "priority"]}
ENV = {"CIQ_ALLOW_TEST": "1"}


def guards(tmp_path: Path, **over) -> list[str]:
    args = {"final": dict(FINAL), "thresholds": dict(TH), "report_path": tmp_path / "r.md",
            "confirmed": True, "env": dict(ENV), "git_dirty": False, "allow_dirty": False,
            "meta": dict(META)}
    args.update(over)
    return fte.check_guards(**args)


def test_all_guards_pass(tmp_path: Path) -> None:
    assert guards(tmp_path) == []


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"confirmed": False}, "--confirm-final-test-eval"),
        ({"final": None}, "final_model.yaml is missing"),
        ({"final": {**FINAL, "frozen_date": None}}, "frozen_date"),
        ({"final": {**FINAL, "frozen_date": "soon"}}, "YYYY-MM-DD"),
        ({"thresholds": {**TH, "tau": 0.7}}, "thresholds.tau differs"),
        ({"meta": {**META, "data_version": "other"}}, "data_version"),
        ({"meta": {**META, "tasks": ["product"]}}, "lacks tasks"),
        ({"meta": None}, "meta.json not found"),
        ({"git_dirty": True}, "dirty"),
        ({"env": {}}, "CIQ_ALLOW_TEST=1"),
    ],
)
def test_each_guard_refuses(tmp_path: Path, over: dict, needle: str) -> None:
    problems = guards(tmp_path, **over)
    assert any(needle in p for p in problems), problems


def test_existing_report_refuses(tmp_path: Path) -> None:
    (tmp_path / "r.md").write_text("done")
    assert any("already exists" in p for p in guards(tmp_path))


def test_dirty_tree_allowed_only_with_flag(tmp_path: Path) -> None:
    assert guards(tmp_path, git_dirty=True, allow_dirty=True) == []


def test_main_refuses_without_reading_test(monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture) -> None:
    import complaintiq.data.training_data as td

    def boom(*a, **k):
        raise AssertionError("test split must not be read")

    monkeypatch.setattr(td, "load_split", boom)
    monkeypatch.delenv("CIQ_ALLOW_TEST", raising=False)
    monkeypatch.setattr(fte, "evaluate", boom)
    assert fte.main([]) == 2
    out = capsys.readouterr()
    assert out.out.startswith("final_test_eval.py: ONE-SHOT")  # plan printed first
    assert "REFUSING" in out.err


def test_repo_final_model_matches_thresholds_and_is_not_frozen() -> None:
    final = yaml.safe_load((REPO / "configs" / "final_model.yaml").read_text())
    th = yaml.safe_load((REPO / "configs" / "thresholds.yaml").read_text())
    for k in fte.THRESHOLD_KEYS:
        assert float(final["thresholds"][k]) == pytest.approx(float(th[k]), abs=1e-6), k
    assert set(fte.REQUIRED) <= set(final)
