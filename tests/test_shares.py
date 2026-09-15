"""FIX_PLAN F2: which share count is used, in what basis, and the cross-check."""

from datetime import date

import polars as pl

from backtester import shares

M = date(2020, 6, 30)


def _panel(cover, bs, wavg) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "month": [M],
            "ticker": ["X"],
            "shares_cover": [cover],
            "shares_cover_filed": [date(2020, 4, 30)],
            "shares": [bs],
            "shares_filed": [date(2020, 3, 31)],
            "shares_wavg": [wavg],
            "shares_wavg_filed": [date(2020, 2, 28)],
        },
        schema={
            "month": pl.Date,
            "ticker": pl.Utf8,
            "shares_cover": pl.Float64,
            "shares_cover_filed": pl.Date,
            "shares": pl.Float64,
            "shares_filed": pl.Date,
            "shares_wavg": pl.Float64,
            "shares_wavg_filed": pl.Date,
        },
    )


def test_cover_count_wins_then_balance_sheet_then_weighted_average() -> None:
    got = shares.resolve(_panel(100.0, 90.0, 80.0)).row(0, named=True)
    assert (got["n_shares"], got["shares_source"]) == (100.0, "cover")
    assert got["shares_filed"] == date(2020, 4, 30)
    got = shares.resolve(_panel(None, 90.0, 80.0)).row(0, named=True)
    assert (got["n_shares"], got["shares_source"]) == (90.0, "balance_sheet")
    got = shares.resolve(_panel(None, None, 80.0)).row(0, named=True)
    assert (got["n_shares"], got["shares_source"]) == (80.0, "weighted_average")
    # A zero count is no count (Berkshire's cover page reports 0 one quarter).
    got = shares.resolve(_panel(0.0, 90.0, 80.0)).row(0, named=True)
    assert got["shares_source"] == "balance_sheet"


def test_override_pins_a_source_or_drops_the_ticker() -> None:
    pin = pl.DataFrame(
        {"ticker": ["X"], "source": ["weighted_average"], "reason": ["test"]}
    )
    got = shares.resolve(_panel(100.0, 90.0, 80.0), None, pin).row(0, named=True)
    assert (got["n_shares"], got["shares_source"]) == (80.0, "weighted_average")
    drop = pl.DataFrame({"ticker": ["X"], "source": ["unresolved"], "reason": ["t"]})
    assert shares.resolve(_panel(100.0, 90.0, 80.0), None, drop).height == 0


def test_a_split_after_the_filing_scales_the_count_into_the_price_basis() -> None:
    """A 50-for-1 split in 2024 makes yfinance's 2020 close 1/50th of what
    was printed; a count filed in 2020 must be multiplied by 50 to meet it.
    A split before the filing is already in the count and is not applied."""
    splits = pl.DataFrame(
        {
            "ticker": ["X", "X"],
            "date": [date(2019, 1, 1), date(2024, 6, 26)],
            "ratio": [2.0, 50.0],
        },
        schema=shares.SPLIT_SCHEMA,
    )
    got = shares.resolve(_panel(31e6, None, None), splits).row(0, named=True)
    assert got["split_factor"] == 50.0 and got["n_basis"] == 31e6 * 50
    assert shares.resolve(_panel(31e6, None, None), None)["split_factor"][0] == 1.0


def test_ratio_of_100_is_flagged_and_within_band_is_not() -> None:
    assert shares.flag_ratio(100.0)
    assert shares.flag_ratio(0.01)
    assert shares.flag_ratio(None)
    assert not shares.flag_ratio(1.0)
    assert not shares.flag_ratio(0.5) and not shares.flag_ratio(2.0)
    sec = pl.DataFrame(
        {
            "ticker": ["OK", "BAD"],
            "sec_shares": [1.0e9, 1.0e7],
            "sec_source": ["cover", "cover"],
            "sec_cap": [1.0e11, 1.0e9],
        }
    )
    yf = pl.DataFrame(
        {"ticker": ["OK", "BAD"], "yf_shares": [1.02e9, 1.0e9]}
    ).with_columns(pl.lit(1.0e11).alias("yf_cap"))
    out = shares.crosscheck(sec, yf)
    assert dict(zip(out["ticker"], out["flag"], strict=True)) == {
        "OK": False,
        "BAD": True,
    }
    assert abs(out.filter(pl.col("ticker") == "BAD")["ratio"][0] - 0.01) < 1e-12


def test_parse_cover_drops_zero_and_404_bodies() -> None:
    body = (
        '{"units": {"shares": [{"end": "2010-07-20", "val": 31107821, '
        '"accn": "0001-10", "fy": 2010, "fp": "Q2", "form": "10-Q", '
        '"filed": "2010-07-27"}, {"end": "2010-10-19", "val": 0, '
        '"accn": "0001-11", "fy": 2010, "fp": "Q3", "form": "10-Q", '
        '"filed": "2010-10-22"}]}}'
    )
    got = shares.parse_cover(body, 1058090)
    assert got.height == 1 and got["value"][0] == 31107821.0
    assert got["ddate"][0] == date(2010, 7, 20) and got["filed"][0] == date(2010, 7, 27)
    assert shares.parse_cover("Not Found", 1).height == 0


def test_parse_fallback_gives_a_duration_fact_its_quarters() -> None:
    body = (
        '{"units": {"shares": [{"start": "2020-01-01", "end": "2020-06-30", '
        '"val": 1003000000, "accn": "a", "fy": 2020, "fp": "Q2", "form": "10-Q", '
        '"filed": "2020-08-09"}, {"end": "2020-06-30", "val": 900, "accn": "a", '
        '"fy": 2020, "fp": "Q2", "form": "10-Q", "filed": "2020-08-09"}]}}'
    )
    got = shares.parse_fallback(body, 1, "shares_wavg").sort("qtrs")
    assert got["qtrs"].to_list() == [0, 2]
    assert got["concept"].to_list() == ["shares_wavg", "shares_wavg"]


def _series(values: dict[str, list[float | None]]) -> pl.DataFrame:
    """A one-ticker panel over consecutive months from the per-source lists."""
    n = len(next(iter(values.values())))
    months = [date(2015 + i // 12, i % 12 + 1, 28) for i in range(n)]
    filed = [date(2015 + i // 12, i % 12 + 1, 1) for i in range(n)]
    return pl.DataFrame(
        {
            "month": months,
            "ticker": ["X"] * n,
            "shares_cover": values.get("cover", [None] * n),
            "shares_cover_filed": filed,
            "shares": values.get("bs", [None] * n),
            "shares_filed": filed,
            "shares_wavg": values.get("wavg", [None] * n),
            "shares_wavg_filed": filed,
        },
        schema={
            "month": pl.Date,
            "ticker": pl.Utf8,
            "shares_cover": pl.Float64,
            "shares_cover_filed": pl.Date,
            "shares": pl.Float64,
            "shares_filed": pl.Date,
            "shares_wavg": pl.Float64,
            "shares_wavg_filed": pl.Date,
        },
    )


def test_a_count_in_thousands_is_passed_over_or_dropped() -> None:
    """Garmin: the balance sheet in thousands one year while the weighted
    average is in units, then both in thousands. The month takes the
    source in units; when neither is, it is implausible."""
    bs = [1.9e8] * 6 + [1.9e5] * 3 + [1.9e5] * 3 + [1.9e8] * 6
    wavg = [1.9e8] * 6 + [1.9e8] * 3 + [1.9e5] * 3 + [1.9e8] * 6
    out = shares.resolve(_series({"bs": bs, "wavg": wavg})).sort("month")
    src = out["shares_source"].to_list()
    assert src[:6] == ["balance_sheet"] * 6
    assert src[6:9] == ["weighted_average"] * 3
    assert out["implausible"].to_list()[9:12] == [True] * 3
    assert out["implausible"].to_list()[:9] == [False] * 9


def test_a_recapitalisation_two_sources_agree_on_is_kept() -> None:
    """AIG 2011: the count went from 135m to 1.8bn in a quarter and the
    cover page and the weighted average both say so."""
    cover = [1.35e8] * 12 + [1.8e9] * 12
    wavg = [1.35e8] * 12 + [1.75e9] * 12
    out = shares.resolve(_series({"cover": cover, "wavg": wavg})).sort("month")
    assert not out["implausible"].any()
    assert out["n_basis"].to_list()[-1] == 1.8e9


def test_a_merger_shell_count_of_one_is_dropped_even_when_sources_agree() -> None:
    cover = [2.3e8] * 12 + [1.0] * 4 + [4.7e8] * 12
    bs = [2.3e8] * 12 + [1.0] * 4 + [4.7e8] * 12
    out = shares.resolve(_series({"cover": cover, "bs": bs})).sort("month")
    assert out["implausible"].to_list()[12:16] == [True] * 4
    assert not any(
        out["implausible"].to_list()[:12] + out["implausible"].to_list()[16:]
    )


def test_a_shell_count_with_no_neighbours_is_still_dropped() -> None:
    out = shares.resolve(_series({"bs": [100.0] * 12}))
    assert out["implausible"].all()


def test_a_majority_of_months_in_thousands_does_not_become_the_reference() -> None:
    """EchoStar: the weighted average is in thousands in every 10-Q and
    in units in every 10-K, so most months are wrong."""
    wavg = ([2.7e8] * 3 + [2.7e5] * 9) * 3
    panel = _series({"wavg": wavg})
    prices = panel.select("month", "ticker", pl.lit(100.0).alias("px_me_raw"))
    out = shares.resolve(panel, prices=prices).sort("month")
    flags = out["implausible"].to_list()
    assert flags == [v < 1e6 for v in wavg]


def test_a_count_a_million_times_too_large_does_not_anchor_the_reference() -> None:
    """AEP: nine months of one year carry a count a million times too
    large; the other months must not be judged against it."""
    cover = [4.8e8] * 20 + [4.8e14] * 9 + [4.8e8] * 20
    panel = _series({"cover": cover})
    prices = panel.select("month", "ticker", pl.lit(80.0).alias("px_me_raw"))
    out = shares.resolve(panel, prices=prices).sort("month")
    assert out["implausible"].to_list() == [v > 1e12 for v in cover]
