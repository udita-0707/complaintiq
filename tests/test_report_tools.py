"""M6 report tooling: number parsing, matching, exemptions, derived numbers (no data, no models)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_report  # noqa: E402
import check_numbers as cn  # noqa: E402


def test_parser_skips_ids_dates_versions_and_ranges() -> None:
    line = ("p95 12.3 ms, 2022-09-12, v2.14.1, 72.6% coverage, run a1236f9e6d99, 877,895 rows, "
            "0.697-0.706")
    assert list(cn.numbers_in(line)) == [("12.3", ""), ("72.6", "%"), ("877,895", "")]


def test_matching_rounds_and_handles_percentages() -> None:
    idx = cn.index({0.7819, 0.7261, 877895.0})
    assert cn.matches("0.782", "", idx) and cn.matches("72.6", "%", idx)
    assert cn.matches("877,895", "", idx)
    assert not cn.matches("0.783", "", idx) and not cn.matches("877,896", "", idx)


def test_exemptions() -> None:
    assert cn.skip("34") and cn.skip("2023") and cn.skip("429")
    assert not cn.skip("1,000") and not cn.skip("0.5")


def test_check_flags_invented_numbers_but_not_assumptions(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("real 0.7819 and invented 123,457\nassumed 7,777 a day [assumption]\n"
                   "```\ncode 999,999\n```\n")
    misses = cn.check([doc], {0.7819}, root=tmp_path)
    assert [m.number for m in misses] == ["123,457"]


def test_m6_drafts_are_not_sources() -> None:
    rels = {p.relative_to(REPO).as_posix() for p in cn.collect_sources()}
    assert "reports/m4/test_results.md" in rels
    assert not any(r.startswith("reports/m6/sections/") for r in rels)
    assert "reports/m6/technical_report.md" not in rels


def test_derived_numbers_come_from_source_files() -> None:
    rows = {name: value for name, value, _f, _s in build_report.derived()}
    assert rows["Duplicate narrative rows removed"] == "355,499"
    assert rows["Test product macro-F1 without the unseen OTHER class"] == "0.773"
    assert rows["Agent-hours a day, 5,000 complaints x test coverage x 1.5 min"] == "90.8"
