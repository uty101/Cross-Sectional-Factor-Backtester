"""No number in the README is typed from memory: its results table is the
one in reports/results.md, which report.py writes (BUILD_PLAN ruling 4).
The caveats sit next to the numbers (FIX_PLAN_2 G3)."""

import re
from pathlib import Path

import polars as pl
import pytest

from backtester import config, report

HEADER = "| Factor | Gross ann. |"


def _table(text: str, header: str = HEADER) -> list[str]:
    """The table rows that follow ``header``, minus-signs normalised."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(re.sub(r"(?<=\s)-(?=\d)", "−", line.strip()))
    return rows


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip("|").split("|")]


def test_readme_results_table_matches_results_md(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    results = (repo_root / "reports" / "results.md").read_text(encoding="utf-8")
    assert _table(readme) == _table(results)


def test_results_table_has_a_coverage_column_and_the_quality_footnote(
    repo_root: Path,
) -> None:
    for name in ("README.md", "reports/results.md"):
        text = (repo_root / name).read_text(encoding="utf-8")
        head = next(line for line in text.splitlines() if line.startswith(HEADER))
        assert _cells(head)[-1] == "Coverage"
        rows = {_cells(r)[0]: _cells(r) for r in _table(text)}
        quality = rows["Quality (GP/A, accruals)"][-1]
        assert re.fullmatch(r"\d+% of non-fin\.¹", quality), quality
        for factor, cells in rows.items():
            if factor != "Quality (GP/A, accruals)":
                assert re.fullmatch(r"\d+%", cells[-1]), (factor, cells[-1])
        foot = [line for line in text.splitlines() if line.startswith("¹ Quality")]
        assert foot, f"{name}: no coverage footnote"
        assert quality.split("%")[0] + "%" in foot[0]
        assert "cost-of-goods" in foot[0]


def test_no_half_life_where_the_ic_t_stat_is_under_1_96(repo_root: Path) -> None:
    text = (repo_root / "reports" / "results.md").read_text(encoding="utf-8")
    head = _cells(next(x for x in text.splitlines() if x.startswith(HEADER)))
    t_col = head.index("IC t-stat")
    ic_t = {
        _cells(r)[0]: float(_cells(r)[t_col].replace("−", "-")) for r in _table(text)
    }
    decay = {_cells(r)[0]: _cells(r)[-1] for r in _table(text, "| Factor | IC h=1 |")}
    assert decay, "no IC decay table"
    for factor, cell in decay.items():
        if abs(ic_t[factor]) < report.IC_T_MIN:
            assert cell == "n/a", (factor, cell)
        else:
            assert cell != "n/a", (factor, cell)
    # the quality footnote mark is on the attribution row too
    att = _table(text, "| Factor | Alpha (ann.) |")
    assert any(r.startswith("| Quality (GP/A, accruals)¹ |") for r in att)


def test_every_number_in_the_answer_is_in_a_table(repo_root: Path) -> None:
    """FIX_PLAN_2 G4: the answer paragraph is at most 120 words and every
    number in it is in reports/results.md or in a table on the README."""
    answer = (repo_root / "reports" / "answer.md").read_text(encoding="utf-8")
    assert len(answer.split()) <= 120
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    assert answer.strip() in readme, "README does not carry the answer verbatim"
    results = (repo_root / "reports" / "results.md").read_text(encoding="utf-8")
    tables = "\n".join(x for x in readme.splitlines() if x.startswith("|"))
    backed = (results + tables).replace("−", "-")
    for n in set(re.findall(r"\d+(?:\.\d+)?", answer)):
        assert re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", backed), n


def test_coverage_figures_in_the_readme_and_answer_are_the_checks(
    repo_root: Path,
) -> None:
    """J3a: the price-coverage figures in the README's prose and the answer
    paragraph sit in ``<!--cov:key-->`` placeholders that ``report.build``
    fills from data/checks; each must already carry the value the checks
    give, and every key the prose uses must be one the report computes.
    The six that were typed (14.7% twice, 85.3%, 128 twice, and the
    answer's 14.7%) drifted once (review/j2c.md)."""
    cfg = config.load(repo_root / "config.toml")
    values = report.coverage_figures(cfg)
    seen: dict[str, int] = {}
    for rel in report.PLACEHOLDER_FILES:
        text = (repo_root / rel).read_text(encoding="utf-8")
        found = report.PLACEHOLDER.findall(text)
        assert found, f"{rel}: no placeholders"
        for key, value in found:
            assert key in values, (rel, key)
            assert value == values[key], (rel, key, value, values[key])
            seen[key] = seen.get(key, 0) + 1
        assert report.fill_placeholders(text, values) == text
    # the six typed figures, and the month the count starts from
    assert seen == {
        "gap_pct": 3,
        "covered_pct": 1,
        "good_months": 2,
        "first_good_month": 2,
    }, seen
    # the same figures the report prints
    summary = pl.read_csv(
        repo_root / cfg.data / "checks" / "price_coverage_summary.csv"
    )
    gap = float(summary.filter(pl.col("metric") == "gap_pct")["value"][0])
    assert values["gap_pct"] == f"{gap:.1f}%"
    assert values["covered_pct"] == f"{100 - gap:.1f}%"
    results = (repo_root / "reports" / "results.md").read_text(encoding="utf-8")
    assert f"Price history covers {values['covered_pct']} of member-months" in results
    assert f"(from {values['first_good_month']}-31) |" in results, (
        "the coverage-split header does not start where the placeholder says"
    )


def test_placeholders_are_filled_in_place_and_stripped_for_the_page() -> None:
    text = "gap <!--cov:gap_pct-->1.0%<!--/cov--> on <!--cov:good_months-->3<!--/cov-->"
    filled = report.fill_placeholders(text, {"gap_pct": "14.7%", "good_months": "128"})
    assert filled == (
        "gap <!--cov:gap_pct-->14.7%<!--/cov--> on <!--cov:good_months-->128<!--/cov-->"
    )
    assert report.strip_placeholders(filled) == "gap 14.7% on 128"
    with pytest.raises(KeyError):
        report.fill_placeholders("<!--cov:made_up-->9<!--/cov-->", {})
