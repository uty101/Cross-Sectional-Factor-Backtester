"""Invariant 4: a signal at month-end t is traded at the close of t + lag_days
and earns nothing before then."""

from datetime import date, timedelta

import polars as pl

from backtester import prices


def _daily(ticker: str, start: date, n: int, step: float = 1.0) -> pl.DataFrame:
    """Weekdays only, price = 100 + step * i, so every move is identifiable."""
    rows = []
    d, i = start, 0
    while len(rows) < n:
        if d.weekday() < 5:
            rows.append(
                {
                    "date": d,
                    "ticker": ticker,
                    "close": 100.0 + step * i,
                    "adj_close": 100.0 + step * i,
                    "volume": 1.0,
                }
            )
            i += 1
        d += timedelta(days=1)
    return pl.DataFrame(rows, schema=prices.PRICE_SCHEMA)


def test_execution_lag_skips_first_day() -> None:
    daily = _daily("X", date(2020, 1, 1), 70)
    m = prices.monthly_returns(
        daily, lag_days=1, start=date(2020, 1, 31), end=date(2020, 2, 29)
    )
    jan = m.filter(pl.col("month") == date(2020, 1, 31)).row(0, named=True)
    assert jan["t"] == date(2020, 1, 31)
    assert jan["t_exec"] == date(2020, 2, 3)  # next trading day, over a weekend
    px = dict(zip(daily["date"], daily["adj_close"], strict=True))
    # Position formed at the Jan 31 signal is bought at the Feb 3 close and
    # sold at the close of the trading day after Feb 28.
    assert jan["px_exec"] == px[date(2020, 2, 3)]
    assert (
        abs(jan["ret_fwd"] - (px[date(2020, 3, 2)] / px[date(2020, 2, 3)] - 1)) < 1e-12
    )
    # The Jan 31 -> Feb 3 move is not part of it.
    assert jan["ret_fwd"] != px[date(2020, 3, 2)] / px[date(2020, 1, 31)] - 1
    assert (
        abs(jan["ret_cal"] - (px[date(2020, 2, 28)] / px[date(2020, 1, 31)] - 1))
        < 1e-12
    )


def test_zero_lag_trades_at_the_signal_close() -> None:
    daily = _daily("X", date(2020, 1, 1), 70)
    m = prices.monthly_returns(
        daily, lag_days=0, start=date(2020, 1, 31), end=date(2020, 2, 29)
    )
    jan = m.filter(pl.col("month") == date(2020, 1, 31)).row(0, named=True)
    assert jan["t_exec"] == jan["t"] == date(2020, 1, 31)
    assert jan["ret_fwd"] == jan["ret_cal"]


def test_name_that_stops_trading_is_closed_at_its_last_price() -> None:
    # Acquired mid-February: last print 2020-02-14.
    daily = _daily("X", date(2020, 1, 1), 33)
    assert daily["date"].max() == date(2020, 2, 14)
    cal = _daily("CAL", date(2020, 1, 1), 70)  # something else keeps the calendar going
    m = prices.monthly_returns(
        pl.concat([daily, cal]),
        lag_days=1,
        start=date(2020, 1, 31),
        end=date(2020, 3, 31),
    )
    x = m.filter(pl.col("ticker") == "X").sort("month")
    jan = x.row(0, named=True)
    px = dict(zip(daily["date"], daily["adj_close"], strict=True))
    assert jan["partial"] is True
    assert (
        abs(jan["ret_fwd"] - (px[date(2020, 2, 14)] / px[date(2020, 2, 3)] - 1)) < 1e-12
    )
    assert x.filter(pl.col("month") == date(2020, 2, 29)).height == 0


def test_gap_in_history_is_a_null_not_a_bridged_return() -> None:
    a = _daily("X", date(2020, 1, 1), 25)  # through 2020-02-04
    b = _daily("X", date(2020, 4, 1), 60)  # back in April, through June
    cal = _daily("CAL", date(2020, 1, 1), 120)
    m = prices.monthly_returns(
        pl.concat([a, b, cal]),
        lag_days=1,
        start=date(2020, 1, 31),
        end=date(2020, 5, 31),
    )
    x = m.filter(pl.col("ticker") == "X").sort("month")
    jan = x.filter(pl.col("month") == date(2020, 1, 31)).row(0, named=True)
    # Jan's forward return closes at the last print in early Feb; nothing
    # bridges to April.
    assert jan["partial"] is True
    px = dict(zip(a["date"], a["adj_close"], strict=True))
    assert (
        abs(jan["ret_fwd"] - (px[date(2020, 2, 4)] / px[date(2020, 2, 3)] - 1)) < 1e-12
    )
    assert x.filter(pl.col("month") == date(2020, 2, 29)).height == 0
    assert x.filter(pl.col("month") == date(2020, 3, 31)).height == 0
    apr = x.filter(pl.col("month") == date(2020, 4, 30)).row(0, named=True)
    assert apr["partial"] is False and apr["ret_fwd"] is not None


def test_parse_yahoo_csv_keeps_positive_adjusted_closes() -> None:
    text = (
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2020-01-02,1,1,1,10,9.5,100\n"
        "2020-01-03,1,1,1,11,,100\n"
        "2020-01-06,1,1,1,12,11.4,100\n"
    )
    df = prices.parse_yahoo_csv(text, "X")
    assert df["date"].to_list() == [date(2020, 1, 2), date(2020, 1, 6)]
    assert df["adj_close"].to_list() == [9.5, 11.4]


def test_to_yahoo_ticker_form() -> None:
    assert prices.to_yahoo("BRK.B") == "BRK-B"
    assert prices.to_yahoo("AAPL") == "AAPL"


def test_clean_daily_applies_the_three_rules() -> None:
    mem = pl.DataFrame(
        {
            "ticker": ["GOOD", "REUSED", "GLITCH", "CORRUPT"],
            "start": [date(2009, 1, 1)] * 4,
            "end": [None, date(2012, 6, 30), date(2015, 1, 1), date(2015, 1, 1)],
        },
        schema={"ticker": pl.Utf8, "start": pl.Date, "end": pl.Date},
    )
    good = _daily("GOOD", date(2010, 1, 1), 30)
    reused = _daily("REUSED", date(2018, 1, 1), 30)  # first print years after removal
    glitch = _daily("GLITCH", date(2010, 1, 1), 30)
    glitch = glitch.with_columns(
        pl.when(pl.col("date") == glitch["date"][10])
        .then(pl.col("adj_close") * 500)
        .otherwise(pl.col("adj_close"))
        .alias("adj_close")
    )
    corrupt = _daily("CORRUPT", date(2010, 1, 1), 30)
    corrupt = corrupt.with_columns(
        pl.when(pl.col("date") >= corrupt["date"][10])
        .then(pl.col("adj_close") * 0.001)
        .otherwise(pl.col("adj_close"))
        .alias("adj_close")
    )
    cleaned, log = prices.clean_daily(pl.concat([good, reused, glitch, corrupt]), mem)
    assert sorted(cleaned["ticker"].unique()) == ["GLITCH", "GOOD"]
    assert cleaned.filter(pl.col("ticker") == "GLITCH").height == 29
    rules = dict(zip(log["ticker"], log["rule"], strict=True))
    assert rules["REUSED"].startswith("no history")
    assert rules["GLITCH"].startswith("bad print")
    assert rules["CORRUPT"].startswith("corrupt")
