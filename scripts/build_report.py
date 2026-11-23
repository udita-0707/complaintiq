"""Assemble the M6 technical report (M6 plan, step 6).

1. Writes ``reports/m6/derived_numbers.md``: the few numbers the report computes rather than
   copies (business-case hours, test macro-F1 without the unseen class, error-category sums,
   duplicate rows removed ...). Each one is computed here from a source file, with its formula,
   so ``check_numbers.py`` can trace it.
2. Concatenates ``reports/m6/sections/*.md`` (in file-name order) into
   ``reports/m6/technical_report.md`` with a title block and a contents list.
3. Runs the number check and writes ``reports/m6/number_check.md``.
4. ``--pdf``: also converts the report with pandoc if pandoc (and a PDF engine) is installed.

No model, data split or test file is read: only saved reports and configs.

Usage::

    python scripts/build_report.py [--pdf]          # make report
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
M6 = REPO / "reports" / "m6"
SECTIONS = M6 / "sections"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_numbers  # noqa: E402

VOLUMES = (2000, 5000, 10000)  # complaints per day [assumption]
MINUTES = (1.0, 1.5, 2.0)  # minutes saved per manual triage [assumption]


def _json(rel: str) -> dict[str, Any]:
    return json.loads((REPO / rel).read_text())


def _md_table_value(rel: str, pattern: str) -> str:
    m = re.search(pattern, (REPO / rel).read_text(), re.MULTILINE)
    if not m:
        raise SystemExit(f"{rel}: pattern not found: {pattern}")
    return m.group(1)


def error_shares() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    text = (REPO / "reports/m4/error_analysis.md").read_text()
    for task, cat, share in re.findall(r"^\| (issue|product) \| ([a-z \-]+) \| \d+ \| ([0-9.]+) \|",
                                       text, re.MULTILINE):
        out.setdefault(task, {})[cat.strip()] = float(share)
    return out


def derived() -> list[tuple[str, str, str, str]]:
    """``(name, value, formula, source)`` rows."""
    test = _json("reports/m4/results/test_results.json")
    cal = _json("reports/m4/results/calibration.json")
    cov_t, prec_t = test["product"]["gate"]["coverage"], test["product"]["gate"]["precision"]
    cov_b = cal["product"]["at_tau_b"]["coverage"]
    prec_b = cal["product"]["at_tau_b"]["precision"]
    cal_json = "reports/m4/results/calibration.json"
    test_json = "reports/m4/results/test_results.json"
    pc = [r for r in test["product"]["per_class"] if r["label"] != "OTHER"]
    rows = [
        ("Test product macro-F1 without the unseen OTHER class",
         f"{sum(r['f1'] for r in pc) / len(pc):.3f}",
         f"mean F1 of the {len(pc)} product classes other than OTHER",
         "reports/m4/results/test_results.json"),
        ("Share of auto-routed test complaints sent to the wrong team", f"{1 - prec_t:.3f}",
         f"1 - test auto-route precision {prec_t:.4f}", "reports/m4/results/test_results.json"),
        ("Gap between val-B auto-route precision and the 0.95 target",
         f"{0.95 - prec_b:.4f}", f"0.95 - {prec_b:.4f}", cal_json),
        ("Human-review share at tau, val-B", f"{1 - cov_b:.3f}", f"1 - coverage {cov_b:.4f}",
         "reports/m4/results/calibration.json"),
        ("Human-review share at tau, test", f"{1 - cov_t:.3f}", f"1 - coverage {cov_t:.4f}",
         "reports/m4/results/test_results.json"),
    ]
    sh = error_shares()
    for task in ("issue", "product"):
        s = sh[task]["label ambiguity"] + sh[task]["taxonomy mismatch"]
        rows.append((f"Label ambiguity + taxonomy mismatch, share of sampled {task} errors",
                     f"{s:.3f}", "sum of the two category shares", "reports/m4/error_analysis.md"))
    stats = "reports/m2_data_stats.md"
    before_s = _md_table_value(stats, r"^\| after duplicate Complaint ID drop \| ([\d,]+) \|")
    after_s = _md_table_value(stats, r"^\| after duplicate normalized-narrative drop"
                              r".*\| ([\d,]+) \|")
    before, after = int(before_s.replace(",", "")), int(after_s.replace(",", ""))
    rows.append(("Duplicate narrative rows removed", f"{before - after:,}",
                 f"{before:,} - {after:,}", "reports/m2_data_stats.md section 1"))
    cmp = (REPO / "reports/m3/model_comparison.md").read_text()

    def f1(variant: str, run: str) -> float:
        row = rf"\| {re.escape(variant)} \| [^|]*`{run}` \| ([0-9.]+) \|"
        return float(re.search(row, cmp).group(1))

    sgd, unw = "baseline/tfidf_sgd", "baseline/tfidf_sgd_unweighted"

    rows += [
        ("Product macro-F1 gain from class weights (val)",
         f"{f1(sgd, '34154a2c4760') - f1(unw, 'e0d027aa61f9'):.3f}",
         "balanced SGD minus unweighted SGD", "reports/m3/model_comparison.md"),
        ("Issue macro-F1 gain from class weights (val)",
         f"{f1(sgd, 'b750ea63ac63') - f1(unw, '86b0b0cdcfd3'):.3f}",
         "balanced SGD minus unweighted SGD", "reports/m3/model_comparison.md"),
    ]
    for v in VOLUMES:
        for m in MINUTES:
            rows.append((f"Agent-hours a day, {v:,} complaints x test coverage x {m} min",
                         f"{v * cov_t * m / 60:.1f}", f"{v:,} x {cov_t:.4f} x {m} / 60 "
                         "(volume and minutes are [assumption] inputs)",
                         "reports/m4/results/test_results.json"))
    rows.append(("Agent-minutes a day, 5,000 complaints x test coverage x 1.5 min",
                 f"{5000 * cov_t * 1.5:,.0f}", f"5,000 x {cov_t:.4f} x 1.5", test_json))
    return rows


def write_derived() -> Path:
    rows = derived()
    out = M6 / "derived_numbers.md"
    lines = ["# M6 derived numbers", "",
             "Generated by `python scripts/build_report.py`. Computed from the source files "
             "listed; "
             "nothing here is a new measurement. Volume and minutes in the business case are "
             "assumptions (SPEC A5).", "",
             "| quantity | value | formula | source |", "|---|---|---|---|"]
    lines += [f"| {n} | {v} | {f} | {s} |" for n, v, f, s in rows]
    out.write_text("\n".join(lines) + "\n")
    return out


def assemble() -> Path:
    parts = sorted(SECTIONS.glob("*.md"))
    if not parts:
        raise SystemExit("no sections in reports/m6/sections/")
    titles = [p.read_text().splitlines()[0].lstrip("# ").strip() for p in parts]
    head = [
        "# ComplaintIQ: technical report",
        "",
        "Financial complaint triage on CFPB consumer complaints. NLP Industry Track, team of four: "
        "Kalash (data), Dally (baseline and experiments), Udita (modeling and evaluation), Aman "
        "(deployment). Assembled by `python scripts/build_report.py` from "
        "`reports/m6/sections/`; every number is checked against the source files "
        "(`reports/m6/number_check.md`).",
        "",
        "Number labels: **val** (validation, also used to choose the model), **val-B** (held-out "
        "half of val), **test** (read once after the freeze), **[target]** and **[assumption]** "
        "(not results).",
        "",
        "## Contents",
        "",
        *[f"{i}. {t}" for i, t in enumerate(titles, 1)],
        "",
    ]
    body = []
    for p in parts:
        text = p.read_text().rstrip() + "\n"
        # demote every heading one level: section "# X" becomes "## X" in the report
        body.append(re.sub(r"^(#+) ", lambda m: "#" + m.group(1) + " ", text, flags=re.MULTILINE))
    out = M6 / "technical_report.md"
    out.write_text("\n".join(head) + "\n" + "\n".join(body))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the M6 technical report")
    ap.add_argument("--pdf", action="store_true", help="also build a PDF with pandoc if available")
    args = ap.parse_args(argv)
    write_derived()
    report = assemble()
    rc = check_numbers.main(["--report", str(M6 / "number_check.md")])
    if args.pdf:
        if shutil.which("pandoc"):
            res = subprocess.run(["pandoc", str(report), "-o", str(M6 / "technical_report.pdf")],
                                 capture_output=True, text=True)
            status = "written" if res.returncode == 0 else f"failed ({res.stderr.strip()[:200]})"
            print("pdf:", status)
        else:
            print("pdf: pandoc not installed; Markdown report only")
    print(f"report: {report.relative_to(REPO)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
