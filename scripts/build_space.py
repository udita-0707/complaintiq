"""Stage the Hugging Face Space directories (M5, SPEC C2 deployment, C13 M5).

``api``: copies ``pyproject.toml``, ``src/``, ``configs/`` and the FROZEN model into
``build/hf_space`` with ``deploy/hf_space/{Dockerfile,README.md}`` and a ``.gitattributes``
that stores ``*.joblib`` with git-lfs. Before copying it checks that

- ``configs/final_model.yaml`` is frozen and its thresholds equal ``configs/thresholds.yaml``;
- ``configs/model.yaml: predictor`` is ``baseline`` and ``configs/serving.yaml`` points at
  the frozen ``model_dir``;
- the model directory has every task file and its ``meta.json`` model_version matches;
- the files match ``reports/m5/results/model_manifest.json`` (SHA-256 per file). If the
  manifest is still the placeholder, it is written now (commit it): later builds, e.g. on
  Aman's machine with a copy of the model, must match it exactly.

``ui``: copies ``ui/app.py``, ``ui/ciq_client.py`` and ``ui/.streamlit/`` into
``build/hf_ui_space`` with ``deploy/hf_ui_space/{Dockerfile,README.md}``.

``requirements``: prints the core + serve pins (for ``pip-audit -r``).

``--synthetic-model`` (CI only) fits a tiny model on made-up text instead of copying the
frozen one, so CI can build and smoke-test the real Space image without any model files.

Usage::

    python scripts/build_space.py api [--model-dir DIR] [--out build/hf_space]
    python scripts/build_space.py api --synthetic-model        # CI
    python scripts/build_space.py ui [--out build/hf_ui_space]
    python scripts/build_space.py requirements
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "reports" / "m5" / "results" / "model_manifest.json"
MARKER = ".ciq_space_staging"
TASK_FILES = ("meta.json", "vectorizer.joblib", "product.joblib", "issue.joblib",
              "priority.joblib")
THRESHOLD_KEYS = ("tau", "temperature_product", "temperature_issue", "priority_threshold")
GITATTRIBUTES = "*.joblib filter=lfs diff=lfs merge=lfs -text\n"


class BuildError(RuntimeError):
    """A check failed; nothing is deployed."""


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO / "configs" / f"{name}.yaml").read_text()) or {}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_files(model_dir: Path) -> dict[str, str]:
    """``{relative name: sha256}`` of every file in the model directory (sorted)."""
    return {p.relative_to(model_dir).as_posix(): sha256(p)
            for p in sorted(model_dir.rglob("*")) if p.is_file()}


def check_frozen(model_dir: Path) -> dict[str, Any]:
    """Every pre-deployment check on configs and the model; returns the manifest content."""
    final, th = _yaml("final_model"), _yaml("thresholds")
    serving, model = _yaml("serving"), _yaml("model")
    if not final.get("frozen_date") or not final.get("frozen_by"):
        raise BuildError("configs/final_model.yaml is not frozen (frozen_date/frozen_by)")
    for k in THRESHOLD_KEYS:
        if abs(float(final["thresholds"][k]) - float(th[k])) > 1e-9:
            raise BuildError(f"threshold {k}: final_model.yaml != thresholds.yaml")
    if model.get("predictor") != "baseline":
        raise BuildError("configs/model.yaml: predictor must be 'baseline' for the Space")
    if serving["baseline"]["model_dir"] != final["model_dir"]:
        raise BuildError("configs/serving.yaml baseline.model_dir != final_model.yaml model_dir")
    missing = [f for f in TASK_FILES if not (model_dir / f).is_file()]
    if missing:
        raise BuildError(f"model directory {model_dir} lacks {missing}")
    meta = json.loads((model_dir / "meta.json").read_text())
    if meta.get("model_version") != final["model_version"]:
        raise BuildError(f"meta.json model_version {meta.get('model_version')!r} != "
                         f"final_model.yaml {final['model_version']!r}")
    return {"model_id": final["model_id"], "model_version": final["model_version"],
            "model_dir": final["model_dir"], "data_version": final["data_version"],
            "frozen_date": str(final["frozen_date"]), "files": model_files(model_dir)}


def check_manifest(found: dict[str, Any], path: Path = MANIFEST) -> str:
    """Compare with the committed manifest; write it if it is still the placeholder."""
    current = json.loads(path.read_text()) if path.is_file() else {}
    if not current.get("files"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(found, indent=2, sort_keys=True) + "\n")
        return "written"
    if current["files"] != found["files"]:
        diff = sorted(set(current["files"].items()) ^ set(found["files"].items()))
        raise BuildError(f"model files differ from {path.name}: {[d[0] for d in diff]}")
    return "verified"


def _fresh_dir(out: Path) -> None:
    if out.exists():
        if not (out / MARKER).is_file():
            raise BuildError(f"{out} exists and was not created by this script; remove it")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("created by scripts/build_space.py; safe to delete\n")


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.endswith((".egg-info", ".pyc"))}


def synthetic_model(dest: Path) -> None:
    """Tiny baseline (product, issue, priority) fitted on made-up text: CI smoke only."""
    sys.path.insert(0, str(REPO / "src"))
    from complaintiq.models import baseline

    rows = [("collector keeps calling about a debt i do not owe", "Debt collection",
             "Attempts to collect debt not owed", "HIGH"),
            ("servicer denied my mortgage modification request", "Mortgage",
             "Struggling to pay mortgage", "NORMAL"),
            ("wrong account appears on my credit report", "Credit reporting or credit repair",
             "Incorrect information on your report", "NORMAL")]
    texts, labels = [], {"product": [], "issue": [], "priority": []}
    for text, prod, issue, prio in rows:
        for i in range(20):
            texts.append(f"{text} and nobody answered my letters number {i}")
            labels["product"].append(prod)
            labels["issue"].append(issue)
            labels["priority"].append(prio)
    cfg = baseline.load_baseline_config()
    params = baseline.variant_params(cfg, cfg["default_variant"])
    params["features"].update(min_df=1, max_df=1.0)
    model = baseline.fit_model(texts, labels, params)
    model.meta["model_version"] = "ci-synthetic"
    model.save(dest)


def stage_api(out: Path, model_dir: Path | None, synthetic: bool) -> dict[str, Any]:
    final = _yaml("final_model")
    rel = Path(final["model_dir"])
    src_model = model_dir if model_dir is not None else REPO / rel
    info: dict[str, Any] = {"out": str(out), "model_dir": rel.as_posix()}
    if synthetic:
        info["manifest"] = "skipped (synthetic CI model)"
    else:
        found = check_frozen(src_model)
        info["manifest"] = check_manifest(found)
        info["model_version"] = found["model_version"]
    _fresh_dir(out)
    shutil.copy2(REPO / "pyproject.toml", out / "pyproject.toml")
    shutil.copytree(REPO / "src", out / "src", ignore=_ignore)
    shutil.copytree(REPO / "configs", out / "configs")
    shutil.copy2(REPO / "deploy" / "hf_space" / "Dockerfile", out / "Dockerfile")
    shutil.copy2(REPO / "deploy" / "hf_space" / "README.md", out / "README.md")
    (out / ".gitattributes").write_text(GITATTRIBUTES)
    if synthetic:
        synthetic_model(out / rel)
    else:
        shutil.copytree(src_model, out / rel)
    return info


def stage_ui(out: Path) -> dict[str, Any]:
    _fresh_dir(out)
    for name in ("app.py", "ciq_client.py"):
        shutil.copy2(REPO / "ui" / name, out / name)
    shutil.copytree(REPO / "ui" / ".streamlit", out / ".streamlit")
    shutil.copy2(REPO / "deploy" / "hf_ui_space" / "Dockerfile", out / "Dockerfile")
    shutil.copy2(REPO / "deploy" / "hf_ui_space" / "README.md", out / "README.md")
    return {"out": str(out)}


def serve_requirements() -> list[str]:
    """Core + serve pins from pyproject.toml."""
    proj = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    return [*proj["dependencies"], *proj["optional-dependencies"]["serve"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage the Hugging Face Space directories")
    ap.add_argument("target", choices=["api", "ui", "requirements"])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--model-dir", type=Path, default=None,
                    help="frozen model directory (default: model_dir in final_model.yaml)")
    ap.add_argument("--synthetic-model", action="store_true", help="CI smoke build only")
    args = ap.parse_args(argv)
    if args.target == "requirements":
        print("\n".join(serve_requirements()))
        return 0
    try:
        if args.target == "api":
            info = stage_api(args.out or REPO / "build" / "hf_space", args.model_dir,
                             args.synthetic_model)
        else:
            info = stage_ui(args.out or REPO / "build" / "hf_ui_space")
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2))
    print(f"Staged {args.target} Space in {info['out']}. See docs/deployment.md for the push "
          "commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
