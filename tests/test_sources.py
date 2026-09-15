"""FIX_PLAN F6: two price sources reconcile month by month, and a removed
name is classed by its delisting record before the terminal rule."""

from datetime import date, timedelta

import polars as pl

from backtester import sources
from backtester.universe import month_ends


def _daily(
    ticker: str, closes: list[float], start: date = date(2020, 1, 2)
) -> pl.DataFrame:
    dates = [start + timedelta(days=i) for i in range(len(closes))]
    return pl.DataFrame(
        {
            "date": dates,
            "ticker": [ticker] * len(closes),
            "close": closes,
            "adj_close": closes,
            "volume": [1.0] * len(closes),
        },
        schema=sources.TIINGO_SCHEMA,
    )


def test_reconcile_flags_exactly_one_deliberate_five_percent_disagreement() -> None:
    # Four months of daily prices, identical in both sources except March,
    # where Tiingo's last close is 5% higher.
    closes = [100.0 + i * 0.1 for i in range(120)]
    yf = _daily("A", closes)
    ti_closes = list(closes)
    march_last = max(i for i, d in enumerate(yf["date"]) if d.month == 3)
    ti_closes[march_last] *= 1.05
    ti = _daily("A", ti_closes)
    rec = sources.reconcile(yf, ti, threshold=0.01)
    conflicts = rec.filter(pl.col("conflict"))
    # March's return differs by ~5%, and April's by the same amount the
    # other way (the base moved), so the deliberate disagreement shows on
    # the month it happened and the one after; nothing else.
    assert conflicts["month"].to_list() == [date(2020, 3, 31), date(2020, 4, 30)]
    assert abs(conflicts["diff"][0] - 0.05) < 0.01


def test_merge_prefers_yfinance_and_keeps_a_tiingo_only_name_with_its_source() -> None:
    closes = [100.0 + i for i in range(70)]
    yf = _daily("A", closes)
    ti = pl.concat([_daily("A", closes), _daily("GONE", [10.0 + i for i in range(70)])])
    merged, conflicts = sources.merge(yf, ti, threshold=0.01)
    assert conflicts.height == 0
    by = {t: g for (t,), g in merged.group_by("ticker")}
    assert by["A"]["source"].unique().to_list() == ["yfinance"]
    assert by["GONE"]["source"].unique().to_list() == ["tiingo"]
    assert by["GONE"].height == 70
    # Without a second source nothing changes but a source column.
    alone, c0 = sources.merge(yf, None, 0.01)
    assert alone["source"].unique().to_list() == ["yfinance"] and c0.height == 0


def test_a_conflicting_month_comes_from_tiingo() -> None:
    closes = [100.0] * 70
    yf = _daily("A", closes)
    ti_closes = list(closes)
    ti_closes[40:] = [110.0] * 30  # from day 40 Tiingo is 10% higher
    ti = _daily("A", ti_closes)
    merged, conflicts = sources.merge(yf, ti, threshold=0.01)
    assert conflicts.height >= 1
    month = conflicts["month"][0]
    rows = merged.filter(pl.col("date").dt.month_end() == month)
    assert rows["source"].unique().to_list() == ["tiingo"]


def test_removed_names_are_classed_acquired_failed_or_unknown() -> None:
    m = month_ends(date(2020, 1, 31), date(2020, 6, 30))
    membership = pl.DataFrame(
        {
            "ticker": ["ACQ", "FAIL", "UNK", "STAY"],
            "security": ["a", "b", "c", "d"],
            "start": [date(2010, 1, 1)] * 4,
            "end": [date(2020, 3, 15), date(2020, 3, 15), date(2020, 3, 15), None],
        }
    )
    # Every name prints daily through 2020-03-13; ACQ holds its price, FAIL
    # falls 60% in March, UNK holds too but has no delisting record.
    days = [date(2020, 1, 2) + timedelta(days=i) for i in range(72)]
    frames = []
    for t, last in (("ACQ", 100.0), ("FAIL", 40.0), ("UNK", 100.0), ("STAY", 100.0)):
        closes = [100.0] * len(days)
        closes[-1] = last
        frames.append(_daily(t, closes))
    daily = pl.concat(frames)
    delist = pl.DataFrame(
        {
            "ticker": ["ACQ", "FAIL"],
            "name": ["a", "b"],
            "exchange": ["NYSE", "NYSE"],
            "delisting_date": [date(2020, 3, 16), date(2020, 3, 16)],
        },
        schema=sources.DELISTING_SCHEMA,
    )
    out = sources.classify_removed(membership, daily, delist)
    got = dict(zip(out["ticker"], out["class"], strict=True))
    assert got == {"ACQ": "acquired", "FAIL": "failed", "UNK": "unknown"}
    assert len(m) == 6
