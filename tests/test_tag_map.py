"""FIX_PLAN F3: the tag map only grows, every tag is real, and bank revenue
is derived rather than taken from gross interest income."""

import importlib.util
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from backtester import fundamentals as fx

REPO = Path(__file__).resolve().parents[1]
NUM = REPO / "data" / "interim" / "sec_num.parquet"
F3_TAGS = {
    "assets": ["AssetsNet"],
    "revenue": [
        "SalesRevenueServicesNet",
        "RegulatedAndUnregulatedOperatingRevenue",
        "RealEstateRevenueNet",
        "OilAndGasRevenue",
    ],
    "cogs": ["CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization"],
    "net_interest_income": ["InterestIncomeExpenseNet"],
    "noninterest_income": ["NoninterestIncome"],
}


def test_costs_and_expenses_are_not_cogs() -> None:
    tags = fx.load_tag_map()["cogs"]["tags"]
    assert "CostsAndExpenses" not in tags
    assert "OperatingCostsAndExpenses" not in tags
    # Gross interest income is not revenue either; banks are derived.
    assert (
        "InterestAndDividendIncomeOperating" not in fx.load_tag_map()["revenue"]["tags"]
    )


def test_the_f3_tags_are_in_the_map() -> None:
    tag_map = fx.load_tag_map()
    for concept, tags in F3_TAGS.items():
        for t in tags:
            assert t in tag_map[concept]["tags"], (concept, t)


@pytest.mark.skipif(not NUM.exists(), reason="needs data/interim/sec_num.parquet")
def test_every_new_tag_has_at_least_one_row_in_num() -> None:
    num = pl.read_parquet(NUM, columns=["concept", "tag"]).unique()
    have = set(zip(num["concept"], num["tag"], strict=True))
    for concept, tags in F3_TAGS.items():
        for t in tags:
            assert (concept, t) in have, f"{concept}: {t} was never ingested"


def test_check_tag_map_accepts_additions_and_refuses_removals(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location(
        "check_tag_map", REPO / "scripts" / "check_tag_map.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = tmp_path / "base.toml"
    base.write_text('[concept.cogs]\nkind = "flow"\ntags = ["A", "B"]\n')
    good = tmp_path / "good.toml"
    good.write_text('[concept.cogs]\nkind = "flow"\ntags = ["A", "B", "C"]\n')
    bad = tmp_path / "bad.toml"
    bad.write_text('[concept.cogs]\nkind = "flow"\ntags = ["B", "A", "C"]\n')
    assert mod.main(str(base), str(good)) == 0
    assert mod.main(str(base), str(bad)) == 1


def _panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "month": [date(2020, 6, 30)] * 3,
            "ticker": ["BANK", "MFR", "BANK2"],
            "sector": ["Financials", "Industrials", "Financials"],
            "assets": [1000.0, 500.0, 800.0],
            "revenue": [None, None, 90.0],
            "revenue_ttm": [None, None, 95.0],
            "cogs": [None, 30.0, None],
            "gross_profit": [None, None, None],
            "net_interest_income": [40.0, 40.0, 50.0],
            "noninterest_income": [20.0, 20.0, 10.0],
            "net_interest_income_ttm": [41.0, 41.0, 51.0],
            "noninterest_income_ttm": [21.0, 21.0, 11.0],
        }
    )


def test_bank_revenue_is_derived_for_financials_only() -> None:
    out = fx.bank_revenue(_panel())
    got = {r["ticker"]: r for r in out.iter_rows(named=True)}
    assert got["BANK"]["revenue"] == 60.0 and got["BANK"]["revenue_ttm"] == 62.0
    assert got["BANK"]["revenue_source"] == "derived_bank"
    # A manufacturer with a missing revenue stays missing.
    assert got["MFR"]["revenue"] is None and got["MFR"]["revenue_source"] is None
    # A bank that reports a revenue tag keeps it.
    assert got["BANK2"]["revenue"] == 90.0 and got["BANK2"]["revenue_source"] == "tag"


def test_gross_profitability_excludes_financials() -> None:
    panel = fx.bank_revenue(_panel()).with_columns(
        pl.lit(100.0).alias("revenue"), pl.lit(30.0).alias("cogs")
    )
    out = fx.signal("gross_profitability", panel, None, None)
    assert out["ticker"].to_list() == ["MFR"]
    assert out["value"][0] == pytest.approx(70.0 / 500.0)
