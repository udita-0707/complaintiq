"""Load YAML config files from the configs/ directory, and resolve project paths.

Environment overrides (M5, for the Docker image where the package is installed into
site-packages and the repo layout lives under ``/app``):

- ``COMPLAINTIQ_CONFIG_DIR``: the configs directory;
- ``COMPLAINTIQ_ROOT``: the base for relative paths in configs (``models/...``,
  ``runtime/...``). Defaults to the repository root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_DIR = _REPO_ROOT / "configs"


def project_root() -> Path:
    """Base directory for relative config paths (``COMPLAINTIQ_ROOT`` or the repo root)."""
    return Path(os.environ.get("COMPLAINTIQ_ROOT", _REPO_ROOT)).expanduser()


def resolve_path(path: str | Path) -> Path:
    """Absolute paths unchanged; relative ones are taken from :func:`project_root`."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else project_root() / p


def config_dir() -> Path:
    """Return the config directory, overridable with the COMPLAINTIQ_CONFIG_DIR env var."""
    return Path(os.environ.get("COMPLAINTIQ_CONFIG_DIR", _DEFAULT_CONFIG_DIR))


def load_config(name: str) -> dict[str, Any]:
    """Load ``configs/<name>.yaml`` and return it as a dict."""
    path = config_dir() / f"{name}.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return data
