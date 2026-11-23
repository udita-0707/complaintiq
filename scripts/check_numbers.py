"""Check that every number in the M6 documents traces back to a source file (M6 plan).

Sources (where results live): ``reports/**`` (Markdown, JSON, CSV, including the generated
``reports/m6/derived_numbers.md``), ``docs/data_provenance.md``, ``docs/data_card.md`` (M4,
itself copied from the M2 reports), ``configs/*.yaml`` (frozen
thresholds and settings) and ``docs/SPEC.md`` (targets and spec constants such as the
20-10,000 character limit). The assembled report itself and the section drafts are not
sources.

A number in a checked document passes when some source number rounds to it at the same
number of decimals (``0.782`` matches ``0.7819``), or, for a percentage, when ``72.6%`` matches
``0.7261`` or ``72.6``. Skipped: integers below 100 (counts like "3 seeds"), years
1990-2039, numbers glued to letters, hyphens, slashes or dots (``p95``, ``m4``, dates,
versions, ranges, run IDs), HTTP status codes, and every line containing ``[assumption]`` or
``[target]``.

Limit: a match proves that some source contains the number, not that it is the right one
(three-decimal values can match an unrelated JSON field by chance). Reviewers still check that
each number is quoted from the source the text cites.

Usage::

    python scripts/check_numbers.py [FILES...]       # default: the M6 documents
    python scripts/check_numbers.py --report reports/m6/number_check.md

Exit code 1 when any number is unmatched.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DEFAULT_TARGETS = [
    "reports/m6/technical_report.md",
    "README.md",
    "docs/m6/viva_prep.md",
    "docs/m6/resume_bullets.md",
    "docs/m6/deck_outline.md",
    "docs/m6/business_case.md",
    "docs/m6/viva/data.md",
    "docs/m6/viva/experiments.md",
    "docs/m6/viva/modeling.md",
    "docs/m6/viva/deployment.md",
]
SOURCE_GLOBS = ["reports/**/*.md", "reports/**/*.json", "reports/**/*.csv",
                "docs/data_provenance.md", "docs/data_card.md", "configs/*.yaml", "docs/SPEC.md"]
# M6 outputs are never sources, except the derived numbers computed from source files.
M6_DIR, DERIVED = "reports/m6/", "reports/m6/derived_numbers.md"
SKIP_LINE = re.compile(r"\[(assumption|target)\]", re.IGNORECASE)
NUMBER = re.compile(
    r"(?<![\w.\-/@#])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(%?)(?![\w\-/@]|\.\d)"
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str
    number: str


def numbers_in(text: str) -> Iterable[tuple[str, str]]:
    """``(number, percent_sign)`` pairs found in ``text``."""
    for m in NUMBER.finditer(text):
        yield m.group(1), m.group(2)


def _value(raw: str) -> float:
    return float(raw.replace(",", ""))


def _decimals(raw: str) -> int:
    return len(raw.split(".")[1]) if "." in raw else 0


def source_values(paths: Iterable[Path]) -> set[float]:
    vals: set[float] = set()
    for p in paths:
        for raw, pct in numbers_in(p.read_text(encoding="utf-8", errors="replace")):
            v = _value(raw)
            vals.add(v)
            if pct:
                vals.add(v / 100)
    return vals


def collect_sources(root: Path = REPO) -> list[Path]:
    out: list[Path] = []
    for g in SOURCE_GLOBS:
        for p in root.glob(g):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and (not rel.startswith(M6_DIR) or rel == DERIVED):
                out.append(p)
    return sorted(set(out))


def index(values: set[float], max_decimals: int = 8) -> dict[int, set[float]]:
    """Source values rounded to every number of decimals, for constant-time lookups."""
    return {d: {round(v, d) for v in values} for d in range(max_decimals + 1)}


def matches(raw: str, pct: str, idx: dict[int, set[float]]) -> bool:
    v, d = _value(raw), _decimals(raw)
    if round(v, d) in idx[min(d, 8)]:
        return True
    if pct:  # 72.6% may be stored as 0.726 / 0.7261
        dd = min(d + 2, 8)
        return round(v / 100, dd) in idx[dd]
    return False


HTTP_STATUS = {200, 400, 404, 413, 422, 429, 500, 503}  # protocol constants, not results


def skip(raw: str) -> bool:
    v = _value(raw)
    if raw.isdigit() and int(raw) in HTTP_STATUS:
        return True
    if "." not in raw and "," not in raw and v < 100:
        return True
    return "." not in raw and "," not in raw and 1990 <= v <= 2039


def check(targets: Iterable[Path], values: set[float], root: Path = REPO) -> list[Hit]:
    idx = index(values)
    misses: list[Hit] = []
    for p in targets:
        if not p.is_file():
            continue
        in_code = False
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code or SKIP_LINE.search(line):
                continue
            for raw, pct in numbers_in(line):
                if not skip(raw) and not matches(raw, pct, idx):
                    misses.append(Hit(p.relative_to(root).as_posix(), i, line.strip()[:160],
                                      raw + pct))
    return misses


def render(misses: list[Hit], targets: list[Path], n_sources: int, root: Path = REPO) -> str:
    lines = [
        "# M6 number check",
        "",
        "Generated by `python scripts/check_numbers.py` (`make check-numbers`). Every number in "
        "the documents below must appear in a source file (reports/, docs/data_provenance.md, "
        "configs/, docs/SPEC.md); lines marked [assumption] or [target] are exempt.",
        "",
        "- Documents checked: "
        + ", ".join(p.relative_to(root).as_posix() for p in targets if p.is_file()),
        f"- Source files read: {n_sources}",
        f"- Unmatched numbers: **{len(misses)}**",
        "",
        "A match proves that some source contains the number, not that it is the right one; "
        "reviewers still check each number against the source the text cites.",
        "",
    ]
    if misses:
        lines += ["| file | line | number | context |", "|---|---|---|---|"]
        lines += [f"| {h.path} | {h.line} | {h.number} | {h.text.replace('|', '/')} |"
                  for h in misses]
    else:
        lines.append("Every number traces to a source file.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check M6 numbers against source files")
    ap.add_argument("files", nargs="*", help="documents to check (default: the M6 documents)")
    ap.add_argument("--report", help="write the Markdown result here")
    args = ap.parse_args(argv)
    targets = [REPO / f for f in (args.files or DEFAULT_TARGETS)]
    sources = collect_sources()
    misses = check(targets, source_values(sources))
    if args.report:
        Path(args.report).write_text(render(misses, targets, len(sources)))
    for h in misses:
        print(f"{h.path}:{h.line}: {h.number} not found in sources")
    print(f"unmatched numbers: {len(misses)}")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
