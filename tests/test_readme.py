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


def _placeholders(repo_root: Path, values: dict[str, str]) -> dict[str, int]:
    """Key -> count over the placeholder files, asserting every placeholder
    carries the value the report computes and a fill is a no-op."""
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
    return seen


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
    values = report.prose_figures(cfg)
    seen = _placeholders(repo_root, values)
    # the six typed figures, and the month the count starts from
    assert {k: seen[k] for k in report.coverage_figures(cfg)} == {
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


# The prose figures J3b put in placeholders: the momentum, value, low
# volatility and text attribution sentences, momentum's turnover and
# break-even, the value before/after table's after column, the Data
# row's first and last price gap, and the cap-weighted shares.
PROSE_KEYS = {
    "beta_umd_momentum",
    "t_umd_momentum",
    "r2_momentum",
    "turnover_momentum",
    "breakeven_momentum",
    "beta_hml_value",
    "t_hml_value",
    "r2_value",
    "alpha_value",
    "alpha_t_value",
    "corr_value_hml",
    "sharpe_net_value",
    "beta_mkt_rf_low_vol",
    "t_mkt_rf_low_vol",
    "beta_rmw_low_vol",
    "t_rmw_low_vol",
    "alpha_low_vol",
    "alpha_t_low_vol",
    "gross_ann_text_change",
    "net_ann_text_change",
    "alpha_text_change",
    "alpha_t_text_change",
    "r2_text_change",
    "gap_first",
    "gap_last",
    "cap_share_2010",
    "cap_share_2023",
}


def test_prose_figures_in_the_readme_are_the_reports(repo_root: Path) -> None:
    """J3b: the turnovers, loadings, cap-weighted shares and the Data row's
    gaps in the README's prose are placeholders filled from results.csv,
    validation.csv and data/checks, and carry those values now. Before
    this the cap-weighted shares read 39% and 86% from 11 September (61%
    and 95% after F2) and the text bullet quoted a run three fixes old."""
    cfg = config.load(repo_root / "config.toml")
    values = report.prose_figures(cfg)
    seen = _placeholders(repo_root, values)
    missing = PROSE_KEYS - set(seen)
    assert not missing, missing
    # The loadings are the attribution table's cells, to the same digits.
    results = (repo_root / "reports" / "results.md").read_text(encoding="utf-8")
    att = {
        _cells(r)[0]: [c.replace("-", "−") for c in _cells(r)]
        for r in _table(results, "| Factor | Alpha (ann.) |")
    }
    mom = att["Momentum 12-1"]
    assert mom[5] == f"{values['beta_umd_momentum']} ({values['t_umd_momentum']})"
    assert mom[7] == values["r2_momentum"]
    lv = att["Low volatility"]
    assert lv[3] == f"{values['beta_mkt_rf_low_vol']} ({values['t_mkt_rf_low_vol']})"
    assert lv[6] == f"{values['beta_rmw_low_vol']} ({values['t_rmw_low_vol']})"
    assert (lv[1], lv[2]) == (values["alpha_low_vol"], values["alpha_t_low_vol"])
    # and the cap-weighted shares are the sentence results.md prints
    a, b = values["cap_share_2010"], values["cap_share_2023"]
    assert f"({a} of members in 2010, {b} in 2023)" in results
    # the same as the fundamentals coverage check, by hand
    cov = pl.read_csv(
        repo_root / cfg.data / "checks" / "fundamentals_coverage.csv",
        try_parse_dates=True,
    ).filter(pl.col("month").dt.year() == 2010)
    assert (
        values["cap_share_2010"]
        == f"{100 * (cov['market_cap'] / cov['n_members']).mean():.0f}%"
    )
    # results.csv carries the t-stats and the appendix row the prose quotes
    res = pl.read_csv(repo_root / cfg.reports / "results.csv")
    assert {"t_mkt_rf", "t_hml", "t_umd", "t_rmw"} <= set(res.columns)
    assert "text_change" in res["key"].to_list()


def test_prose_figures_are_formatted_like_the_tables(tmp_path: Path, repo_root) -> None:
    cfg = config.load(repo_root / "config.toml").with_(
        data=repo_root / "data", reports=tmp_path
    )
    pl.DataFrame(
        {
            "key": ["x"],
            "gross_ann": [-0.0213],
            "net_ann": [0.0049],
            "turnover": [0.6249],
            "breakeven_bps": [-73.4],
            "sharpe_net": [-0.1899],
            "alpha_ann": [-0.0186],
            "alpha_t": [-0.94],
            "r2": [0.5249],
            "beta_mkt_rf": [-0.671],
            "beta_hml": [0.4199],
            "beta_umd": [0.9],
            "beta_rmw": [0.0],
            "t_mkt_rf": [-11.26],
            "t_hml": [7.74],
            "t_umd": [15.9],
            "t_rmw": [0.04],
        }
    ).write_csv(tmp_path / "results.csv")
    pl.DataFrame(
        {"series": ["x"], "benchmark": ["hml"], "correlation": [0.5542]}
    ).write_csv(tmp_path / "validation.csv")
    v = report.prose_figures(cfg)
    assert v["gross_ann_x"] == "−2.1%" and v["net_ann_x"] == "0.5%"
    assert v["turnover_x"] == "0.62" and v["breakeven_x"] == "none (loses gross)"
    assert v["sharpe_net_x"] == "−0.19"
    assert v["alpha_x"] == "−1.9%" and v["alpha_t_x"] == "−0.9"
    assert v["beta_mkt_rf_x"] == "−0.67" and v["t_mkt_rf_x"] == "−11.3"
    assert v["beta_hml_x"] == "0.42" and v["t_hml_x"] == "7.7"
    assert v["r2_x"] == "0.52" and v["corr_x_hml"] == "0.55"
    assert "-" not in "".join(v[k] for k in v if k.endswith("_x"))  # U+2212 only
