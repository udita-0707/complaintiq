"""Experiment log (SPEC C5): one CSV row per run in ``reports/experiments/<name>.csv``."""

from __future__ import annotations

import csv
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from complaintiq.data.load import REPO_ROOT

COLUMNS: tuple[str, ...] = (
    "run_id",
    "timestamp_utc",
    "git_commit",
    "data_version",
    "model",
    "task",
    "hyperparams_json",
    "seed",
    "n_train",
    "val_macro_f1",  # macro over classes with val support (fixed label set)
    "val_macro_f1_all_labels",  # macro over true and predicted labels (older definition)
    "val_weighted_f1",
    "val_top3",
    "val_pr_auc",
    "train_seconds",
    "owner",
    "notes",
)
EXPERIMENTS_DIR = REPO_ROOT / "reports" / "experiments"


def git_commit() -> str:
    """Short HEAD hash, suffixed ``-dirty`` when the working tree has changes."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}-dirty" if dirty else head


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _migrate_header(path: Path) -> None:
    """Rewrite ``path`` with the current ``COLUMNS`` if its header is older.

    Existing values are kept unchanged; columns added later are blank in old rows.
    Fails if the file has columns that ``COLUMNS`` does not know.
    """
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    if header == list(COLUMNS):
        return
    unknown = set(header) - set(COLUMNS)
    if unknown:
        raise ValueError(f"{path} has unknown columns {sorted(unknown)}")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({c: r.get(c, "") for c in COLUMNS} for r in rows)


def log_run(name: str, experiments_dir: str | Path | None = None, **fields: Any) -> str:
    """Append one run to ``<experiments_dir>/<name>.csv`` and return its ``run_id``.

    ``fields`` must be a subset of ``COLUMNS``. ``run_id``, ``timestamp_utc`` and
    ``git_commit`` are filled in when absent; ``hyperparams`` (a dict) may be passed
    instead of ``hyperparams_json``. Missing metrics are written as empty cells.
    """
    if "hyperparams" in fields:
        fields["hyperparams_json"] = json.dumps(fields.pop("hyperparams"), sort_keys=True)
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown experiment-log fields: {sorted(unknown)}")
    row = {c: fields.get(c) for c in COLUMNS}
    row["run_id"] = row["run_id"] or uuid.uuid4().hex[:12]
    row["timestamp_utc"] = row["timestamp_utc"] or datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row["git_commit"] = row["git_commit"] or git_commit()

    out_dir = Path(experiments_dir) if experiments_dir is not None else EXPERIMENTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.csv"
    new = not path.exists()
    if not new:
        _migrate_header(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow({k: _fmt(v) for k, v in row.items()})
    return str(row["run_id"])


def read_runs(experiments_dir: str | Path | None = None) -> list[dict[str, str]]:
    """All rows of every ``*.csv`` in the experiments directory, with a ``log`` column."""
    out_dir = Path(experiments_dir) if experiments_dir is not None else EXPERIMENTS_DIR
    rows: list[dict[str, str]] = []
    for path in sorted(out_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            rows.extend({**r, "log": path.stem} for r in csv.DictReader(f))
    return rows
