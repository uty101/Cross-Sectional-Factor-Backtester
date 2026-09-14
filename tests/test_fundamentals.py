"""Invariant 1: a fundamental used at month-end t was filed on or before
t - buffer. Invariant 2: the first-filed value wins over amendments."""

from datetime import date

import polars as pl

from backtester import fundamentals as fx
from backtester import sectors

M = [date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31), date(2020, 4, 30)]


def _values(*rows: tuple[int, date, date, float]) -> pl.DataFrame:
    """(cik, period_end, filed, value)."""
    return pl.DataFrame(
        [{"cik": c, "ddate": d, "filed": f, "value": v} for c, d, f, v in rows],
        schema={
            "cik": pl.Int64,
            "ddate": pl.Date,
            "filed": pl.Date,
            "value": pl.Float64,
        },
    )


def _panel(cik: int = 1) -> pl.DataFrame:
    return pl.DataFrame({"month": M, "cik": [cik] * len(M)})


def test_asof_join_excludes_filing_after_signal_date() -> None:
    # A 10-K for FY2019 filed on 2020-02-29 (the month-end itself) and a
    # 10-K for FY2018 filed a year earlier.
    v = _values(
        (1, date(2018, 12, 31), date(2019, 2, 20), 100.0),
        (1, date(2019, 12, 31), date(2020, 2, 29), 200.0),
    )
    out = fx.asof_join(_panel(), v, buffer_days=1).sort("month")
    got = dict(zip(out["month"], out["value"], strict=True))
    # January: only the FY2018 value exists.
    assert got[M[0]] == 100.0
    # February month-end equals the filing date: with a one-day buffer the
    # new value is NOT available yet.
    assert got[M[1]] == 100.0
    # March: filed 2020-02-29 + 1 day <= 2020-03-31 -> available.
    assert got[M[2]] == 200.0
    assert got[M[3]] == 200.0
    # And with no buffer, the same-day filing is used at the February month-end.
    out0 = fx.asof_join(_panel(), v, buffer_days=0).sort("month")
    assert dict(zip(out0["month"], out0["value"], strict=True))[M[1]] == 200.0


def test_asof_join_never_uses_a_filing_dated_after_the_month() -> None:
    # Filed two days after the month-end: excluded at that month-end even
    # with a zero buffer.
    v = _values((1, date(2019, 12, 31), date(2020, 2, 2), 200.0))
    out = fx.asof_join(_panel(), v, buffer_days=0).sort("month")
    got = dict(zip(out["month"], out["value"], strict=True))
    assert got[M[0]] is None
    assert got[M[1]] == 200.0


def test_asof_join_ignores_a_late_amendment_for_an_older_period() -> None:
    # FY2019 filed Feb 2020; then a 10-K/A for FY2018 filed Mar 2020 must
    # not become "the latest filing" and drag the value back to 2018.
    v = _values(
        (1, date(2018, 12, 31), date(2019, 2, 20), 100.0),
        (1, date(2019, 12, 31), date(2020, 2, 10), 200.0),
        (1, date(2018, 12, 31), date(2020, 3, 5), 150.0),
    )
    out = fx.asof_join(_panel(), v, buffer_days=1).sort("month")
    got = dict(zip(out["month"], out["value"], strict=True))
    assert got[M[2]] == 200.0 and got[M[3]] == 200.0
    assert out.filter(pl.col("month") == M[3])["period_end"][0] == date(2019, 12, 31)


def test_first_filed_value_beats_later_amendment() -> None:
    num = pl.DataFrame(
        {
            "adsh": ["a", "b", "c"],
            "cik": [1, 1, 1],
            "concept": ["net_income"] * 3,
            "ddate": [date(2019, 12, 31)] * 3,
            "qtrs": [4, 4, 4],
            "value": [200.0, 180.0, 190.0],
            "filed": [date(2020, 2, 10), date(2020, 6, 1), date(2021, 2, 12)],
            "form": ["10-K", "10-K/A", "10-K"],  # original, restatement, comparative
        }
    )
    ff = fx.first_filed(num)
    assert ff.height == 1
    assert ff["value"][0] == 200.0 and ff["adsh"][0] == "a"


def test_monthly_panel_uses_annual_flows_and_latest_stocks(tmp_path) -> None:
    from backtester import config

    cfg = config.load().with_(asof_buffer_days=1)
    num = pl.DataFrame(
        {
            "adsh": ["k19", "q1", "k20"],
            "cik": [1, 1, 1],
            "concept": ["net_income", "assets", "net_income"],
            "ddate": [date(2019, 12, 31), date(2020, 3, 31), date(2020, 12, 31)],
            "qtrs": [4, 0, 4],
            "value": [10.0, 500.0, 12.0],
            "filed": [date(2020, 2, 10), date(2020, 5, 5), date(2021, 2, 10)],
            "form": ["10-K", "10-Q", "10-K"],
        }
    )
    ciks = pl.DataFrame({"ticker": ["X"], "cik": [1]})
    months = M + [date(2020, 6, 30), date(2021, 3, 31)]
    panel = fx.monthly_panel(cfg, num, ciks, months).sort("month")
    ni = dict(zip(panel["month"], panel["net_income"], strict=True))
    assets = dict(zip(panel["month"], panel["assets"], strict=True))
    assert ni[date(2020, 1, 31)] is None and ni[date(2020, 3, 31)] == 10.0
    assert ni[date(2021, 3, 31)] == 12.0
    assert assets[date(2020, 4, 30)] is None and assets[date(2020, 6, 30)] == 500.0


def test_sic_map_covers_the_obvious_cases() -> None:
    assert sectors.sic_to_sector(2834) == "Health Care"  # pharma, not chemicals
    assert sectors.sic_to_sector(2800) == "Materials"
    assert sectors.sic_to_sector(7372) == "Information Technology"
    assert sectors.sic_to_sector(6798) == "Real Estate"
    assert sectors.sic_to_sector(6021) == "Financials"
    assert sectors.sic_to_sector(6324) == "Health Care"  # UnitedHealth
    assert sectors.sic_to_sector(5331) == "Consumer Staples"  # Walmart
    assert sectors.sic_to_sector(4911) == "Utilities"
    assert sectors.sic_to_sector(3711) == "Consumer Discretionary"
    assert sectors.sic_to_sector(4813) == "Communication Services"
    assert sectors.sic_to_sector(None) == "Other"
    assert sectors.sic_to_sector(9999) == "Other"


def test_cik_match_by_name_records_its_method() -> None:
    membership = pl.DataFrame(
        {
            "ticker": ["AAPL", "OLDCO", "GONE"],
            "security": ["Apple Inc.", "Widget Makers Corp", "Nowhere Ltd"],
        }
    )
    constituents = pl.DataFrame({"ticker": ["AAPL"], "cik": ["0000320193"]})
    num = pl.DataFrame(
        {
            "cik": [320193, 555, 555],
            "name": ["APPLE INC", "WIDGET MAKERS CO", "WIDGET MAKERS CORP"],
            "filed": [date(2020, 1, 1)] * 3,
        }
    )
    ciks, log = sectors.cik_map(membership, constituents, num)
    got = dict(zip(log["ticker"], log["method"], strict=True))
    assert got == {"AAPL": "constituents", "OLDCO": "name exact", "GONE": "unmatched"}
    assert dict(zip(ciks["ticker"], ciks["cik"], strict=True)) == {
        "AAPL": 320193,
        "OLDCO": 555,
    }


def _ff(*rows: tuple[date, int, float, date, str]) -> pl.DataFrame:
    """(ddate, qtrs, value, filed, form) for one cik and one concept."""
    return pl.DataFrame(
        [
            {
                "adsh": f"a{i}",
                "cik": 1,
                "concept": "net_income",
                "tag": "NetIncomeLoss",
                "ddate": d,
                "qtrs": q,
                "value": v,
                "filed": f,
                "form": fm,
                "fy": d.year,
                "fp": "FY" if q == 4 else f"Q{q}",
                "sic": 1,
                "name": "X",
            }
            for i, (d, q, v, f, fm) in enumerate(rows)
        ],
        schema=fx.NUM_SCHEMA,
    )


def test_ttm_against_hand_computed_quarters() -> None:
    # FY2019 annual 100. 2019 YTD: Q1 20, H1 45. 2020 YTD: Q1 30, H1 65.
    # TTM at Q1 2020 = 30 + 100 - 20 = 110; at H1 2020 = 65 + 100 - 45 = 120.
    ff = _ff(
        (date(2019, 3, 31), 1, 20.0, date(2019, 5, 1), "10-Q"),
        (date(2019, 6, 30), 2, 45.0, date(2019, 8, 1), "10-Q"),
        (date(2019, 12, 31), 4, 100.0, date(2020, 2, 20), "10-K"),
        (date(2020, 3, 31), 1, 30.0, date(2020, 5, 5), "10-Q"),
        (date(2020, 6, 30), 2, 65.0, date(2020, 8, 5), "10-Q"),
    )
    t = fx.ttm(ff)
    got = {(r["ddate"], r["qtrs"]): r for r in t.iter_rows(named=True)}
    assert got[(date(2020, 3, 31), 1)]["value"] == 110.0
    assert got[(date(2020, 6, 30), 2)]["value"] == 120.0
    assert got[(date(2019, 12, 31), 4)]["value"] == 100.0
    # 2019's quarters have no prior-year YTD or annual: no partial sums.
    assert (date(2019, 3, 31), 1) not in got and (date(2019, 6, 30), 2) not in got
    # Stamped with the latest input filing, which is the 10-Q itself here.
    assert got[(date(2020, 6, 30), 2)]["filed"] == date(2020, 8, 5)


def test_ttm_is_available_only_when_every_input_was_filed() -> None:
    # The prior-year YTD is first filed late, in an amendment after the
    # 10-Q: the TTM row carries that later date, not the 10-Q's.
    ff = _ff(
        (date(2019, 3, 31), 1, 20.0, date(2020, 6, 1), "10-Q/A"),
        (date(2019, 12, 31), 4, 100.0, date(2020, 2, 20), "10-K"),
        (date(2020, 3, 31), 1, 30.0, date(2020, 5, 5), "10-Q"),
    )
    t = fx.ttm(ff)
    row = t.filter(pl.col("qtrs") == 1).row(0, named=True)
    assert row["value"] == 110.0 and row["filed"] == date(2020, 6, 1)
