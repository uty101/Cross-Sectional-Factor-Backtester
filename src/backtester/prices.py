"""Daily adjusted prices for every ticker that ever appeared in the universe.

yfinance is the only source that answers: Stooq sits behind a JavaScript
challenge page as of 2026-09 and returns no data to a script. yfinance
has no history for names that were delisted more than a few weeks ago,
so every removed name that was acquired or went bankrupt is missing and
the gap is reported as a share of universe-months (brief, section 10).

Raw pulls are never overwritten (invariant 7). A signal at month-end t is
traded at the close of t + lag_days trading days and earns nothing before
then (invariant 4): ``ret_fwd`` for month t is the return from that
execution close to the next month's execution close.
"""

from __future__ import annotations

import io
import warnings
from datetime import date
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config

BATCH = 100
HISTORY_START = date(2008, 1, 1)  # 12 months of momentum before the window
MARKET = "^GSPC"

PRICE_SCHEMA = {
    "date": pl.Date,
    "ticker": pl.Utf8,
    "close": pl.Float64,
    "adj_close": pl.Float64,
    "volume": pl.Float64,
}


def to_yahoo(ticker: str) -> str:
    """Wikipedia writes share classes ``BRK.B``; Yahoo writes ``BRK-B``."""
    return ticker.replace(".", "-")


def _raw_name(ticker: str) -> str:
    return ticker.replace("^", "").replace(".", "-")


# --- fetch --------------------------------------------------------------


def fetch(cfg: Config, as_of: date) -> list[Path]:
    """Download every universe ticker plus the market index from yfinance.

    One CSV per ticker under ``data/raw/prices/yfinance``. Tickers that
    return nothing are listed in ``data/checks/price_fetch_missing.csv``.
    """
    import yfinance as yf

    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    tickers = sorted(set(membership["ticker"].to_list())) + [MARKET]
    root = cfg.data / "raw"
    stored: list[Path] = []
    missing: list[dict] = []

    for i in range(0, len(tickers), BATCH):
        batch = tickers[i : i + BATCH]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = yf.download(
                [to_yahoo(t) for t in batch],
                start=HISTORY_START.isoformat(),
                end=(as_of).isoformat(),
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
        for t in batch:
            y = to_yahoo(t)
            try:
                sub = frame[y].dropna(how="all")
            except KeyError:
                sub = None
            if sub is None or sub.empty:
                missing.append({"ticker": t, "yahoo": y, "reason": "no data"})
                continue
            buf = io.StringIO()
            sub.to_csv(buf)
            rel = f"prices/yfinance/{_raw_name(t)}_{as_of}.csv"
            try:
                stored.append(
                    raw.store_raw(root, rel, buf.getvalue().encode(), f"yfinance:{y}")
                )
            except FileExistsError:
                stored.append(root / rel)

    checks = cfg.data / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        missing, schema={"ticker": pl.Utf8, "yahoo": pl.Utf8, "reason": pl.Utf8}
    ).write_csv(checks / "price_fetch_missing.csv")
    return stored


# --- parse --------------------------------------------------------------


def parse_yahoo_csv(text: str, ticker: str) -> pl.DataFrame:
    """A per-ticker CSV as saved by ``fetch`` -> PRICE_SCHEMA rows."""
    df = pl.read_csv(io.StringIO(text), try_parse_dates=True)
    cols = {c.lower().replace(" ", "_"): c for c in df.columns}
    date_col = cols.get("date") or df.columns[0]
    out = df.select(
        pl.col(date_col).cast(pl.Date).alias("date"),
        pl.lit(ticker).alias("ticker"),
        pl.col(cols["close"]).cast(pl.Float64).alias("close"),
        pl.col(cols["adj_close"]).cast(pl.Float64).alias("adj_close"),
        pl.col(cols["volume"]).cast(pl.Float64).alias("volume"),
    )
    return out.filter(pl.col("adj_close").is_not_null() & (pl.col("adj_close") > 0))


def build_daily(raw_root: Path, tickers: list[str]) -> pl.DataFrame:
    """Latest raw CSV per ticker -> one long frame."""
    frames = []
    for t in tickers:
        try:
            p = raw.latest(raw_root, f"prices/yfinance/{_raw_name(t)}_*.csv")
        except FileNotFoundError:
            continue
        frames.append(parse_yahoo_csv(p.read_text(encoding="utf-8"), t))
    if not frames:
        return pl.DataFrame(schema=PRICE_SCHEMA)
    return pl.concat(frames).sort("ticker", "date")


# --- cleaning -----------------------------------------------------------

BAD_PRINT = 2.0  # a day that doubles or halves the price and reverses next day
CORRUPT = 3.0  # a remaining tripling or thirding in a day is not a price
NO_HISTORY = (
    "no history inside membership: first print after removal "
    "(reused symbol or delisting stub)"
)


def _ratio(col: str = "adj_close") -> pl.Expr:
    """max(p/p_prev, p_prev/p): the size of a day's move, direction-free."""
    prev = pl.col(col).shift(1).over("ticker")
    return pl.max_horizontal(pl.col(col) / prev, prev / pl.col(col))


def clean_daily(
    daily: pl.DataFrame, membership: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Three rules against yfinance's handling of delisted symbols.

    yfinance keys history by symbol, and symbols are reused: BEAM is Beam
    Therapeutics now, not Beam Inc.; APC, BBBY, CSRA are other companies
    entirely. Delisted series also carry bad prints (TIE at 11,700 on a
    month-end in 2011, real price 19). So:

    1. no history    the first print is after the name's last membership
                     day: a reused symbol, or the few-row stub yfinance keeps
                     for a recent delisting -> the whole ticker is dropped
    2. bad print     a day that at least doubles or halves the price and
                     reverses by at least as much the next day -> that day
                     is dropped
    3. corrupt       a remaining day inside a membership interval that
                     triples or thirds the price -> the whole ticker is
                     dropped. Bounds are on the price ratio, not the signed
                     return, since a fall can never exceed -100%.

    Returns the cleaned frame and a log of every decision per ticker.
    """
    span = membership.group_by("ticker").agg(
        pl.col("start").min().alias("m_start"),
        pl.col("end").max().alias("m_end"),
        pl.col("end").is_null().any().alias("current"),
    )
    first = daily.group_by("ticker").agg(pl.col("date").min().alias("first_px"))
    wrong = (
        first.join(span, on="ticker", how="inner")
        .filter(~pl.col("current") & (pl.col("first_px") > pl.col("m_end")))
        .select(
            "ticker",
            pl.lit(NO_HISTORY).alias("rule"),
            pl.lit(0, dtype=pl.Int64).alias("days_dropped"),
        )
    )
    df = daily.join(wrong.select("ticker"), on="ticker", how="anti").sort(
        "ticker", "date"
    )

    up = pl.col("adj_close") > pl.col("adj_close").shift(1).over("ticker")
    up_next = pl.col("adj_close").shift(-1).over("ticker") > pl.col("adj_close")
    nxt = pl.col("adj_close").shift(-1).over("ticker")
    ratio_next = pl.max_horizontal(nxt / pl.col("adj_close"), pl.col("adj_close") / nxt)
    df = df.with_columns(
        _ratio().alias("_ratio"),
        ratio_next.alias("_ratio_next"),
        (up != up_next).alias("_reverses"),
    )
    bad = (
        (pl.col("_ratio") >= BAD_PRINT)
        & (pl.col("_ratio_next") >= BAD_PRINT)
        & pl.col("_reverses")
    )
    df = df.with_columns(bad.fill_null(False).alias("_bad"))
    bad_log = (
        df.filter(pl.col("_bad"))
        .group_by("ticker")
        .agg(pl.len().alias("days_dropped"))
        .with_columns(
            pl.lit("bad print: doubled or halved and reversed next day").alias("rule")
        )
        .select("ticker", "rule", "days_dropped")
    )
    df = df.filter(~pl.col("_bad")).drop("_ratio", "_ratio_next", "_reverses", "_bad")

    df = df.with_columns(_ratio().alias("_r")).join(span, on="ticker", how="left")
    in_member = (pl.col("date") >= pl.col("m_start")) & (
        pl.col("current") | (pl.col("date") <= pl.col("m_end"))
    )
    corrupt = (
        df.filter(in_member & (pl.col("_r") >= CORRUPT))
        .group_by("ticker")
        .agg(pl.len().alias("days_dropped"))
        .with_columns(
            pl.lit("corrupt: tripled or thirded in a day inside membership").alias(
                "rule"
            )
        )
        .select("ticker", "rule", "days_dropped")
    )
    df = df.join(corrupt.select("ticker"), on="ticker", how="anti").drop(
        "_r", "m_start", "m_end", "current"
    )
    log = pl.concat(
        [
            x.with_columns(pl.col("days_dropped").cast(pl.Int64))
            for x in (wrong, bad_log, corrupt)
        ]
    ).sort("ticker")
    return df.select(list(PRICE_SCHEMA)).sort("ticker", "date"), log


# --- calendar and monthly panel -----------------------------------------


def trading_days(daily: pl.DataFrame) -> pl.Series:
    """Union of dates with a price, sorted. Used as the trading calendar."""
    return daily.get_column("date").unique().sort()


def month_end_trading_days(calendar: pl.Series, start: date, end: date) -> pl.DataFrame:
    """For each calendar month in [start, end]: month (calendar month-end),
    ``t`` (last trading day in the month), and ``t_exec`` (``lag_days`` later
    on the calendar) is added by ``monthly_prices``."""
    cal = pl.DataFrame({"t": calendar})
    return (
        cal.with_columns(pl.col("t").dt.month_end().alias("month"))
        .group_by("month")
        .agg(pl.col("t").max())
        .filter((pl.col("month") >= start) & (pl.col("month") <= end))
        .sort("month")
    )


def shift_on_calendar(calendar: pl.Series, dates: pl.Series, n: int) -> pl.Series:
    """Each date moved ``n`` trading days forward on ``calendar``; null past the end."""
    idx = calendar.search_sorted(dates, side="left")  # exact matches expected
    shifted = idx + n
    out = pl.Series(
        [calendar[i] if 0 <= i < len(calendar) else None for i in shifted.to_list()],
        dtype=pl.Date,
    )
    return out


def rebalance_dates(
    calendar: pl.Series, lag_days: int, start: date, end: date
) -> pl.DataFrame:
    """month, t (last trading day of the month), t_exec (t + lag_days)."""
    me = month_end_trading_days(calendar, start, end)
    return me.with_columns(
        shift_on_calendar(calendar, me["t"], lag_days).alias("t_exec")
    )


def monthly_prices(
    daily: pl.DataFrame, lag_days: int, start: date, end: date
) -> pl.DataFrame:
    """Month-end and execution prices per ticker.

    Columns: month, ticker, t, t_exec, px_me (adj close at t),
    px_exec (adj close at t_exec).
    """
    me = rebalance_dates(trading_days(daily), lag_days, start, end)
    px = daily.select("date", "ticker", "adj_close")
    at_t = me.join(px, left_on="t", right_on="date", how="inner").rename(
        {"adj_close": "px_me"}
    )
    at_exec = (
        me.select("month", "t_exec")
        .join(px, left_on="t_exec", right_on="date", how="inner")
        .rename({"adj_close": "px_exec"})
    )
    return (
        at_t.join(at_exec, on=["month", "ticker"], how="full", coalesce=True)
        .join(me.select("month", "t", "t_exec"), on="month", how="left", suffix="_me")
        .select(
            "month",
            "ticker",
            pl.coalesce("t", "t_me").alias("t"),
            pl.coalesce("t_exec", "t_exec_me").alias("t_exec"),
            "px_me",
            "px_exec",
        )
        .sort("ticker", "month")
    )


def monthly_returns(
    daily: pl.DataFrame, lag_days: int, start: date, end: date
) -> pl.DataFrame:
    """Per (month, ticker): the return a position formed at month-end earns.

    ret_cal   px_me next month / px_me - 1          calendar month return
    ret_fwd   px_exec next month / px_exec - 1      what the portfolio earns
              (invariant 4: nothing between t and t_exec is counted)
    partial   ret_fwd was closed at the last print before the next
              execution date because the name stopped trading in between
    """
    mp = monthly_prices(daily, lag_days, start, end)
    me = rebalance_dates(trading_days(daily), lag_days, start, end)
    # A full month x ticker grid so that shift(-1) is always the very next
    # month, and a gap in a name's history is a null, not a bridged return.
    grid = me.select("month", "t", "t_exec").join(
        mp.select("ticker").unique(), how="cross"
    )
    shifted = (
        grid.join(
            mp.select("month", "ticker", "px_me", "px_exec"),
            on=["month", "ticker"],
            how="left",
        )
        .sort("ticker", "month")
        .with_columns(
            pl.col("px_me").shift(-1).over("ticker").alias("px_me_next"),
            pl.col("px_exec").shift(-1).over("ticker").alias("px_exec_next"),
            pl.col("t_exec").shift(-1).over("ticker").alias("t_exec_next"),
        )
    )
    # The last print on or before the next execution date, per position. If
    # the name stopped trading in between, the position is closed there.
    last_print = (
        daily.select("ticker", "date", "adj_close")
        .rename({"date": "date_last", "adj_close": "px_last"})
        .sort("date_last")
    )
    has_next = shifted.filter(pl.col("t_exec_next").is_not_null()).sort("t_exec_next")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # polars cannot check sortedness with `by`
        has_next = has_next.join_asof(
            last_print,
            left_on="t_exec_next",
            right_on="date_last",
            by="ticker",
            strategy="backward",
        )
    no_next = shifted.filter(pl.col("t_exec_next").is_null()).with_columns(
        pl.lit(None, dtype=pl.Date).alias("date_last"),
        pl.lit(None, dtype=pl.Float64).alias("px_last"),
    )
    return (
        pl.concat([has_next, no_next], how="diagonal")
        .with_columns(
            (pl.col("px_me_next") / pl.col("px_me") - 1).alias("ret_cal"),
            pl.when(pl.col("px_exec_next").is_not_null())
            .then(pl.col("px_exec_next") / pl.col("px_exec") - 1)
            .when(
                pl.col("px_exec").is_not_null()
                & (pl.col("date_last") > pl.col("t_exec"))
            )
            .then(pl.col("px_last") / pl.col("px_exec") - 1)
            .otherwise(None)
            .alias("ret_fwd"),
        )
        .with_columns(
            (pl.col("ret_fwd").is_not_null() & pl.col("px_exec_next").is_null()).alias(
                "partial"
            )
        )
        # No month-end price means no signal and no position: drop the row.
        .filter(pl.col("px_me").is_not_null())
        .select(
            "month",
            "ticker",
            "t",
            "t_exec",
            "px_me",
            "px_exec",
            "ret_cal",
            "ret_fwd",
            "partial",
        )
        .sort("ticker", "month")
    )


def daily_returns(daily: pl.DataFrame) -> pl.DataFrame:
    """date, ticker, ret from adjusted closes. Gaps in a name's history are
    returns across the gap, which is what a holder would have earned."""
    return daily.sort("ticker", "date").select(
        "date",
        "ticker",
        (pl.col("adj_close") / pl.col("adj_close").shift(1).over("ticker") - 1).alias(
            "ret"
        ),
    )


# --- coverage -----------------------------------------------------------


def coverage_report(
    membership: pl.DataFrame, monthly: pl.DataFrame, start: date, end: date
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Per month: members, members with a month-end price, members with a
    forward return. Per ticker: universe-months lost to missing prices."""
    from backtester.universe import members_at, month_ends

    rows = []
    lost: dict[str, int] = {}
    priced = monthly.filter(pl.col("px_me").is_not_null())
    fwd = monthly.filter(pl.col("ret_fwd").is_not_null())
    by_month_px = {
        m: set(g["ticker"].to_list()) for (m,), g in priced.group_by("month")
    }
    by_month_fwd = {m: set(g["ticker"].to_list()) for (m,), g in fwd.group_by("month")}
    for me in month_ends(start, end):
        members = set(members_at(membership, me))
        have_px = members & by_month_px.get(me, set())
        have_fwd = members & by_month_fwd.get(me, set())
        for t in members - have_px:
            lost[t] = lost.get(t, 0) + 1
        rows.append(
            {
                "month": me,
                "n_members": len(members),
                "n_priced": len(have_px),
                "n_fwd_return": len(have_fwd),
                "gap_pct": round(100 * (1 - len(have_px) / len(members)), 2),
            }
        )
    per_month = pl.DataFrame(rows)
    per_ticker = pl.DataFrame(
        [{"ticker": t, "months_missing": n} for t, n in lost.items()],
        schema={"ticker": pl.Utf8, "months_missing": pl.Int64},
    ).sort("months_missing", "ticker", descending=[True, False])
    return per_month, per_ticker


# --- pipeline entry -----------------------------------------------------


def build(cfg: Config) -> pl.DataFrame:
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    tickers = sorted(set(membership["ticker"].to_list())) + [MARKET]
    daily = build_daily(cfg.data / "raw", tickers)
    as_of = daily["date"].max()
    market = daily.filter(pl.col("ticker") == MARKET)
    daily, clean_log = clean_daily(daily.filter(pl.col("ticker") != MARKET), membership)
    daily = pl.concat([daily, market]).sort("ticker", "date")
    checks = cfg.data / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    clean_log.write_csv(checks / "price_cleaning.csv")

    interim = cfg.data / "interim"
    processed = cfg.data / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    stamp = pl.lit(as_of).alias("as_of")
    daily.with_columns(stamp).write_parquet(interim / "prices_daily.parquet")

    stocks = daily.filter(pl.col("ticker") != MARKET)
    # The panel starts 13 months before the window so that a 12-1 momentum
    # signal exists at the first month-end; the coverage report is on the
    # window itself.
    panel_start = pl.Series([cfg.start]).dt.offset_by("-13mo").dt.month_end()[0]
    monthly = monthly_returns(stocks, cfg.lag_days, panel_start, cfg.end)
    monthly.with_columns(stamp).write_parquet(processed / "returns_monthly.parquet")
    daily_returns(daily).with_columns(stamp).write_parquet(
        processed / "returns_daily.parquet"
    )

    per_month, per_ticker = coverage_report(membership, monthly, cfg.start, cfg.end)
    per_month.write_csv(checks / "price_coverage_monthly.csv")
    per_ticker.write_csv(checks / "price_coverage_missing_tickers.csv")
    total = per_month["n_members"].sum()
    summary = {
        "as_of": as_of,
        "tickers_with_prices": stocks["ticker"].n_unique(),
        "tickers_in_universe": membership["ticker"].n_unique(),
        "universe_months": total,
        "priced_months": per_month["n_priced"].sum(),
        "gap_pct": round(100 * (1 - per_month["n_priced"].sum() / total), 2),
        "gap_pct_max_month": per_month["gap_pct"].max(),
        "gap_pct_min_month": per_month["gap_pct"].min(),
        "partial_returns": monthly["partial"].sum(),
        "tickers_dropped_no_history": clean_log.filter(
            pl.col("rule").str.starts_with("no history")
        ).height,
        "tickers_dropped_corrupt": clean_log.filter(
            pl.col("rule").str.starts_with("corrupt")
        ).height,
        "bad_prints_dropped": clean_log.filter(pl.col("rule").str.starts_with("bad"))[
            "days_dropped"
        ].sum(),
    }
    pl.DataFrame(
        {"metric": list(summary), "value": [str(v) for v in summary.values()]}
    ).write_csv(checks / "price_coverage_summary.csv")
    return monthly
