"""Load YAML config files from the configs/ directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


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
