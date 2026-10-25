"""Build data/raw/complaints.csv from a CFPB export and record its provenance.

Usage:
    python scripts/prepare_raw_data.py [ZIP_PATH]                 # official CSV zip
    python scripts/prepare_raw_data.py PARQUET_DIR_OR_FILES...    # archived Parquet mirror
    make raw-data INPUT="..."

Input is either one zip containing a single CSV, or Parquet files (or a directory of
them) with the same columns; Parquet is streamed to CSV with polars. Stats are then
computed by streaming the CSV in chunks, reading only the columns they need, and
written to docs/data_provenance.md. Never prints complaint text.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import polars as pl

from complaintiq.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RawStats:
    """Summary statistics of the raw CSV."""

    total_rows: int
    columns: list[str]
    narrative_rows: int
    date_min: str
    date_max: str
    unparsed_dates: int
    n_products: int
    n_issues: int


def fail(msg: str) -> None:
    """Print an error and exit non-zero."""
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def extract_csv(zip_path: Path, out_csv: Path) -> None:
    """Stream the single CSV inside ``zip_path`` to ``out_csv``."""
    if not zip_path.is_file():
        fail(f"zip not found: {zip_path} (download it from the CFPB site or pass a path)")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        fail(f"not a valid zip file: {zip_path}")
    with zf:
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv") and not n.endswith("/")]
        if not csvs:
            fail(f"no .csv file inside {zip_path}")
        if len(csvs) > 1:
            fail(f"expected one .csv inside {zip_path}, found {len(csvs)}: {csvs}")
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_csv.with_suffix(".csv.part")
        with zf.open(csvs[0]) as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1 << 20)
        tmp.replace(out_csv)


def parquet_inputs(paths: list[Path]) -> list[Path]:
    """Expand directories and return the sorted list of Parquet files."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("*.parquet")))
        elif p.is_file() and p.suffix == ".parquet":
            files.append(p)
        else:
            fail(f"not a .parquet file or directory: {p}")
    if not files:
        fail(f"no .parquet files found in {[str(p) for p in paths]}")
    return sorted(files)


def parquet_to_csv(files: list[Path], out_csv: Path) -> None:
    """Stream Parquet ``files`` (same schema) into a single CSV at ``out_csv``."""
    schemas = {f.name: tuple(pl.read_parquet_schema(f)) for f in files}
    if len(set(schemas.values())) > 1:
        fail(f"Parquet files have different columns: {schemas}")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_csv.with_suffix(".csv.part")
    pl.scan_parquet(files).sink_csv(tmp, date_format="%Y-%m-%d")
    tmp.replace(out_csv)


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in 1 MB blocks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def compute_stats(csv_path: Path, cols: dict[str, str], chunksize: int) -> RawStats:
    """Stream ``csv_path`` in chunks and compute summary stats."""
    columns = list(pd.read_csv(csv_path, nrows=0).columns)
    missing = [c for c in cols.values() if c not in columns]
    if missing:
        fail(f"expected columns missing from {csv_path.name}: {missing}")

    total = narrative = unparsed = 0
    date_min: pd.Timestamp | None = None
    date_max: pd.Timestamp | None = None
    products: set[str] = set()
    issues: set[str] = set()

    reader = pd.read_csv(csv_path, usecols=list(cols.values()), dtype=str, chunksize=chunksize)
    for chunk in reader:
        total += len(chunk)
        narrative += int(chunk[cols["narrative"]].fillna("").str.strip().ne("").sum())
        dates = pd.to_datetime(chunk[cols["date_received"]], errors="coerce", format="ISO8601")
        unparsed += int(dates.isna().sum() - chunk[cols["date_received"]].isna().sum())
        if dates.notna().any():
            lo, hi = dates.min(), dates.max()
            date_min = lo if date_min is None else min(date_min, lo)
            date_max = hi if date_max is None else max(date_max, hi)
        products.update(chunk[cols["product"]].dropna().unique())
        issues.update(chunk[cols["issue"]].dropna().unique())

    return RawStats(
        total_rows=total,
        columns=columns,
        narrative_rows=narrative,
        date_min=date_min.date().isoformat() if date_min is not None else "n/a",
        date_max=date_max.date().isoformat() if date_max is not None else "n/a",
        unparsed_dates=unparsed,
        n_products=len(products),
        n_issues=len(issues),
    )


def render_markdown(
    stats: RawStats,
    sha256: str,
    csv_rel: str,
    inputs: dict[str, str],
    source_url: str,
    retrieved_from: str | None,
) -> str:
    """Render the provenance document. ``inputs`` maps input file name to SHA-256."""
    pct = 100 * stats.narrative_rows / stats.total_rows if stats.total_rows else 0.0
    cols = "\n".join(f"{i}. {c}" for i, c in enumerate(stats.columns, 1))
    input_rows = "\n".join(f"| `{name}` | `{digest}` |" for name, digest in inputs.items())
    mirror = f"| Retrieved from | {retrieved_from} |\n" if retrieved_from else ""
    return f"""# Data provenance: CFPB Consumer Complaint Database

Generated by `scripts/prepare_raw_data.py` (`make raw-data`). The CSV itself is not committed.

| Field | Value |
|---|---|
| Source | {source_url} |
{mirror}| Prepared on | {date.today().isoformat()} |
| Local file | `{csv_rel}` |
| SHA-256 (local CSV) | `{sha256}` |
| Total rows | {stats.total_rows:,} |
| Rows with non-empty narrative | {stats.narrative_rows:,} ({pct:.1f}%) |
| Date received (min) | {stats.date_min} |
| Date received (max) | {stats.date_max} |
| Unparseable dates | {stats.unparsed_dates:,} |
| Distinct Product values | {stats.n_products:,} |
| Distinct Issue values | {stats.n_issues:,} |

## Input files

| File | SHA-256 |
|---|---|
{input_rows}

## Columns ({len(stats.columns)})

{cols}
"""


def main() -> None:
    """CLI entry point."""
    cfg = load_config("data")
    raw = cfg["raw"]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "inputs",
        nargs="*",
        default=[raw["default_zip"]],
        help=f"a CSV zip, or Parquet files/directory (default: {raw['default_zip']})",
    )
    args = parser.parse_args()

    inputs = [Path(p).expanduser().resolve() for p in args.inputs]
    csv_path = REPO_ROOT / cfg["raw_path"]
    doc_path = REPO_ROOT / raw["provenance_doc"]
    csv_rel = csv_path.relative_to(REPO_ROOT)

    if len(inputs) == 1 and inputs[0].suffix == ".zip":
        input_files = inputs
        print(f"Extracting {inputs[0]} -> {csv_rel}")
        extract_csv(inputs[0], csv_path)
    else:
        input_files = parquet_inputs(inputs)
        print(f"Converting {len(input_files)} Parquet file(s) -> {csv_rel}")
        parquet_to_csv(input_files, csv_path)
    if not csv_path.is_file():
        fail(f"CSV not found after extraction: {csv_path}")

    print("Hashing...")
    input_hashes = {f.name: sha256_file(f) for f in input_files}
    digest = sha256_file(csv_path)
    print("Computing stats (streaming)...")
    stats = compute_stats(csv_path, raw["columns"], int(raw["chunksize"]))

    md = render_markdown(
        stats,
        digest,
        str(csv_rel),
        input_hashes,
        raw["source_url"],
        raw.get("retrieved_from"),
    )
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(md, encoding="utf-8")
    print()
    print(md)
    print(f"Wrote {doc_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
