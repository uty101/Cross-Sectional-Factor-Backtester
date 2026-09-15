"""FIX_PLAN_3 H1: the pipeline's cap at the float date against the 10-K's
public float, and the 12-month exclusion a bad ratio earns."""

from datetime import date

import polars as pl

from backtester import fundamentals as fx
from backtester import identity

FLOAT_DATE = date(2013, 6, 30)


def _floats() -> pl.DataFrame:
    # Three filers, one float each. HAR's is the real one ($5bn) against a
    # $2trn cap; U's share count is in thousands ($30m cap, $30bn float).
    rows = [
        (1, "a-13", FLOAT_DATE, date(2014, 2, 20), "10-K", 50e9, 2013),
        (2, "h-13", FLOAT_DATE, date(2014, 2, 25), "10-K", 5e9, 2013),
        (3, "u-13", FLOAT_DATE, date(2014, 2, 27), "10-K", 30e9, 2013),
        # A 10-K/A that restates HAR's float must not win (first filed).
        (2, "h-13a", FLOAT_DATE, date(2014, 6, 1), "10-K/A", 2e12, 2013),
        # A float with no cap at that month: null ratio, no flag.
        (4, "n-13", FLOAT_DATE, date(2014, 2, 27), "10-K", 1e9, 2013),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "cik": pl.Int64,
            "adsh": pl.Utf8,
            "ddate": pl.Date,
            "filed": pl.Date,
            "form": pl.Utf8,
            "value": pl.Float64,
            "fy": pl.Int32,
        },
        orient="row",
    )


def _ciks() -> pl.DataFrame:
    return pl.DataFrame(
        {"ticker": ["A", "HAR", "U", "N"], "cik": [1, 2, 3, 4]},
        schema={"ticker": pl.Utf8, "cik": pl.Int64},
    )


def _caps_and_px() -> tuple[pl.DataFrame, pl.DataFrame]:
    m = FLOAT_DATE
    px = pl.DataFrame(
        {
            "month": [m] * 3,
            "ticker": ["A", "HAR", "U"],
            "px_me_raw": [100.0, 25_814.10, 30.0],
        },
        schema={"month": pl.Date, "ticker": pl.Utf8, "px_me_raw": pl.Float64},
    )
    caps = pl.DataFrame(
        {
            "month": [m] * 3,
            "ticker": ["A", "HAR", "U"],
            "cap": [70e9, 25_814.10 * 68e6, 30e6],  # 1.4x, 351x, 0.001x
            "shares_source": ["cover"] * 3,
        },
        schema={
            "month": pl.Date,
            "ticker": pl.Utf8,
            "cap": pl.Float64,
            "shares_source": pl.Utf8,
        },
    )
    return caps, px


def test_public_float_flags_a_reused_symbol_and_a_units_filing() -> None:
    caps, px = _caps_and_px()
    got = fx.public_float_check(_floats(), _ciks(), caps, px, 0.5, 20).sort("ticker")
    by = {r["ticker"]: r for r in got.to_dicts()}
    assert by["A"]["flag"] == "" and abs(by["A"]["ratio"] - 1.4) < 1e-9
    assert by["HAR"]["flag"] == "high" and by["HAR"]["ratio"] > 300
    assert by["HAR"]["reason"] == "over_100x"
    assert by["HAR"]["public_float"] == 5e9  # the 10-K, not the 10-K/A
    assert abs(by["HAR"]["shares"] - 68e6) < 1e-3
    assert by["U"]["flag"] == "low" and abs(by["U"]["ratio"] - 0.001) < 1e-12
    assert by["U"]["reason"] == "near_1000"
    # A float with no cap is not a flag: a missing number never excludes.
    assert by["N"]["ratio"] is None and by["N"]["flag"] == ""
    assert got["fy"].to_list() == [2013] * 4


def test_flagged_ticker_years_are_excluded_for_twelve_months() -> None:
    caps, px = _caps_and_px()
    check = fx.public_float_check(_floats(), _ciks(), caps, px, 0.5, 20)
    windows = identity.float_windows(check)
    assert windows["ticker"].to_list() == ["HAR", "U"]
    assert windows["start"].to_list() == [FLOAT_DATE] * 2
    assert windows["end"].to_list() == [date(2014, 6, 30)] * 2
    assert windows["source_check"].to_list() == ["public_float"] * 2
    months = [
        date(2013, 5, 31),
        date(2013, 6, 30),
        date(2014, 6, 30),
        date(2014, 7, 31),
    ]
    dropped = identity.excluded_months(windows, months)
    assert dropped.filter(pl.col("ticker") == "HAR")["month"].to_list() == [
        date(2013, 6, 30),
        date(2014, 6, 30),
    ]
    frame = pl.DataFrame(
        {"month": months * 2, "ticker": ["HAR"] * 4 + ["A"] * 4},
        schema={"month": pl.Date, "ticker": pl.Utf8},
    )
    kept = identity.apply(frame, windows)
    assert kept.filter(pl.col("ticker") == "A").height == 4
    assert kept.filter(pl.col("ticker") == "HAR")["month"].to_list() == [
        date(2013, 5, 31),
        date(2014, 7, 31),
    ]


def test_a_ratio_near_a_split_factor_is_named_as_one() -> None:
    caps, px = _caps_and_px()
    # HAR's cap 4x its float, with a 4-for-1 split after the float date.
    caps = caps.with_columns(
        pl.when(pl.col("ticker") == "HAR")
        .then(20e9)
        .otherwise(pl.col("cap"))
        .alias("cap")
    )
    splits = pl.DataFrame(
        {"ticker": ["HAR"], "date": [date(2014, 1, 15)], "ratio": [4.0]},
        schema={"ticker": pl.Utf8, "date": pl.Date, "ratio": pl.Float64},
    )
    got = fx.public_float_check(_floats(), _ciks(), caps, px, 0.5, 2.0, splits)
    har = got.filter(pl.col("ticker") == "HAR").row(0, named=True)
    assert har["flag"] == "high" and har["reason"] == "near_split"


def test_float_thresholds_come_from_config(repo_root) -> None:
    from backtester import config

    lo, hi = fx.float_thresholds(config.load(repo_root / "config.toml"))
    assert (lo, hi) == (0.5, 20.0)


def test_a_float_filed_in_thousands_is_the_filers_error_not_an_exclusion() -> None:
    # G's FY2012 float is filed as $150m (thousands) and FY2013's as $150bn;
    # the cap is $200bn both years. FY2012 is flagged high, named
    # float_scale, and earns no exclusion window.
    floats = pl.DataFrame(
        [
            (5, "g-12", date(2012, 6, 30), date(2013, 2, 1), "10-K", 150e6, 2012),
            (5, "g-13", date(2013, 6, 30), date(2014, 2, 1), "10-K", 150e9, 2013),
            # FY2014: a real 60x (the count is stale), not a scale error,
            # although the FY2013 float would put the cap in band.
            (5, "g-14", date(2014, 6, 30), date(2015, 2, 1), "10-K", 3e9, 2014),
        ],
        schema={
            "cik": pl.Int64,
            "adsh": pl.Utf8,
            "ddate": pl.Date,
            "filed": pl.Date,
            "form": pl.Utf8,
            "value": pl.Float64,
            "fy": pl.Int32,
        },
        orient="row",
    )
    ciks = pl.DataFrame(
        {"ticker": ["G"], "cik": [5]}, schema={"ticker": pl.Utf8, "cik": pl.Int64}
    )
    months = [date(2012, 6, 30), date(2013, 6, 30), date(2014, 6, 30)]
    px = pl.DataFrame(
        {"month": months, "ticker": ["G"] * 3, "px_me_raw": [20.0, 20.0, 20.0]},
        schema={"month": pl.Date, "ticker": pl.Utf8, "px_me_raw": pl.Float64},
    )
    caps = pl.DataFrame(
        {
            "month": months,
            "ticker": ["G"] * 3,
            "cap": [200e9, 200e9, 200e9],
            "shares_source": ["cover"] * 3,
        },
        schema={
            "month": pl.Date,
            "ticker": pl.Utf8,
            "cap": pl.Float64,
            "shares_source": pl.Utf8,
        },
    )
    got = fx.public_float_check(floats, ciks, caps, px, 0.5, 20).sort("fy")
    assert got["flag"].to_list() == ["high", "", "high"]
    assert got["reason"].to_list() == ["float_scale", "", "other"]
    assert identity.float_windows(got)["start"].to_list() == [date(2014, 6, 30)]
