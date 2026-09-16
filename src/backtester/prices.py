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
import json
import re
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
    from backtester import sources

    stored += sources.fetch_tiingo(cfg, as_of) + sources.fetch_delistings(cfg, as_of)
    stored.append(fetch_info(cfg, as_of))
    return stored


# Fewer daily rows than this for a name that was a member for years is a
# stub, not a history: yfinance keeps a few weeks for a recent delisting.
STUB_ROWS = 250


def refetch(cfg: Config, tickers: list[str], as_of: date) -> list[Path]:
    """One more pull of ``tickers`` under a fresh as-of date (FIX_PLAN_4
    J1: AVB and EA came back as 27- and 6-row stubs). A full history is
    stored under prices/yfinance/ and becomes the latest file; a stub is
    stored under prices/yfinance_stubs/ so the answer is on record and
    the manifest has it, without displacing the file the build reads,
    and is logged to price_fetch_missing.csv with its row count."""
    import yfinance as yf

    root = cfg.data / "raw"
    checks = cfg.data / "checks"
    log = checks / "price_fetch_missing.csv"
    missing = (
        pl.read_csv(
            log,
            schema_overrides={"ticker": pl.Utf8, "yahoo": pl.Utf8, "reason": pl.Utf8},
        )
        if log.exists()
        else pl.DataFrame(
            schema={"ticker": pl.Utf8, "yahoo": pl.Utf8, "reason": pl.Utf8}
        )
    )
    stored: list[Path] = []
    rows = []
    for t in tickers:
        y = to_yahoo(t)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sub = yf.download(
                y,
                start=HISTORY_START.isoformat(),
                end=as_of.isoformat(),
                auto_adjust=False,
                actions=False,
                progress=False,
            )
        sub = sub.dropna(how="all") if sub is not None else sub
        n = 0 if sub is None or sub.empty else len(sub)
        buf = io.StringIO()
        if n:
            sub.to_csv(buf)
        stub = n < STUB_ROWS
        folder = "yfinance_stubs" if stub else "yfinance"
        rel = f"prices/{folder}/{_raw_name(t)}_{as_of}.csv"
        try:
            stored.append(
                raw.store_raw(root, rel, buf.getvalue().encode(), f"yfinance:{y}")
            )
        except FileExistsError:
            stored.append(root / rel)
        if stub:
            span = (
                f"{sub.index.min().date()} to {sub.index.max().date()}"
                if n
                else "no data"
            )
            rows.append(
                {
                    "ticker": t,
                    "yahoo": y,
                    "reason": f"stub: {n} rows ({span}) on refetch {as_of}; in the gap",
                }
            )
    if rows:
        checks.mkdir(parents=True, exist_ok=True)
        keep = missing.filter(~pl.col("ticker").is_in([r["ticker"] for r in rows]))
        pl.concat([keep, pl.DataFrame(rows, schema=missing.schema)]).write_csv(log)
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


# --- symbol identity (FIX_PLAN_3 H2) ------------------------------------

# yfinance keys history by symbol and a symbol outlives its company: HAR
# resolves today to a "YHD" fund quoted at $5,000-$34,000, EP to Empire
# Petroleum on NYSE American, COL to nothing. The cleaning rule above
# catches a reused symbol whose new series starts after the name left the
# index; this check asks yfinance what the symbol *is* and compares.
INFO_FIELDS = (
    "longName",
    "shortName",
    "exchange",
    "fullExchangeName",
    "quoteType",
    "currency",
    "firstTradeDateMilliseconds",
)
# yfinance exchange codes for NYSE, Nasdaq (GS, GM, CM), NYSE American,
# NYSE Arca and Cboe BZX: the venues an S&P 500 member trades on.
US_EXCHANGES = frozenset({"NYQ", "NMS", "NGM", "NCM", "ASE", "PCX", "BTS", "NYS"})
NAME_STOP = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "companies",
        "ltd",
        "limited",
        "plc",
        "holdings",
        "holding",
        "group",
        "the",
        "and",
        "of",
        "llc",
        "lp",
        "nv",
        "sa",
        "ag",
        "class",
        "common",
        "stock",
    }
)
IDENTITY_OVERLAP = 0.5
IDENTITY_LATE_MONTHS = 24
# A float date needs a cover count within this many days to give a level.
LEVEL_MAX_GAP_DAYS = 200
# Yahoo's own codes for a symbol it no longer quotes: every delisted name
# is filed as exchange YHD, quote type MUTUALFUND, with a number for a
# short name, or as quote type NONE with nothing else. The history kept
# under such a symbol is usually the company's (Aetna, Time Warner,
# Express Scripts read 0.9-1.1 on the level test) and sometimes not
# (HAR, GR); the code itself says nothing about which.
PLACEHOLDER_EXCHANGES = frozenset({"YHD"})
PLACEHOLDER_TYPES = frozenset({"MUTUALFUND", "NONE"})
IDENTITY_SCHEMA = {
    "ticker": pl.Utf8,
    "wiki_name": pl.Utf8,
    "sec_name": pl.Utf8,
    "yf_name": pl.Utf8,
    "overlap": pl.Float64,
    "exchange": pl.Utf8,
    "currency": pl.Utf8,
    "quote_type": pl.Utf8,
    "first_price": pl.Date,
    "member_start": pl.Date,
    "member_end": pl.Date,
    "level": pl.Float64,
    "n_levels": pl.Int64,
    "flag": pl.Boolean,
    "reason": pl.Utf8,
}
LEVEL_SCHEMA = {
    "ticker": pl.Utf8,
    "level": pl.Float64,
    "level_min": pl.Float64,
    "level_max": pl.Float64,
    "n_levels": pl.Int64,
}


def fetch_info(cfg: Config, as_of: date, tickers: list[str] | None = None) -> Path:
    """yfinance ``info`` (INFO_FIELDS only) for every ticker that ever left
    the index, one JSON keyed by ticker under data/raw/yf_info_<date>.json,
    never overwritten; a symbol yfinance does not know is stored as an
    empty object so the answer is on record."""
    import yfinance as yf

    root = cfg.data / "raw"
    rel = f"yf_info_{as_of.isoformat()}.json"
    if (root / rel).exists():
        return root / rel
    if tickers is None:
        membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
        tickers = sorted(
            set(membership.filter(pl.col("end").is_not_null())["ticker"].to_list())
        )
    out: dict[str, dict] = {}
    for t in tickers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                info = yf.Ticker(to_yahoo(t)).info or {}
        except Exception:  # noqa: BLE001 - a 404 or a parse error is "no info"
            info = {}
        out[t] = {k: info.get(k) for k in INFO_FIELDS if info.get(k) is not None}
    body = json.dumps(out, indent=1, sort_keys=True).encode()
    return raw.store_raw(root, rel, body, "yfinance:Ticker.info")


def load_info(cfg: Config) -> dict[str, dict] | None:
    """The latest yf_info_*.json, or None before ``fetch --step prices``
    has stored one."""
    try:
        p = raw.latest(cfg.data / "raw", "yf_info_*.json")
    except FileNotFoundError:
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def name_tokens(name: str | None) -> set[str]:
    """Lower-case word tokens of a company name without the corporate
    suffixes (Inc, Corp, Co, Ltd, plc, Holdings, Group, The, ...)."""
    if not name:
        return set()
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    return {w for w in words if w not in NAME_STOP}


def name_overlap(a: str | None, b: str | None) -> float | None:
    """Overlap coefficient of the two names' tokens: shared over the
    smaller set, so "Harman International" against "Harman International
    Industries" is 1.0. None when either side has no tokens."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return None
    return len(ta & tb) / min(len(ta), len(tb))


def is_real_name(name: str | None) -> bool:
    """Yahoo's delisted placeholders carry a number for a name (906601)."""
    return bool(name) and bool(re.search(r"[a-z]", name.lower()))


def price_levels(
    floats: pl.DataFrame,
    cover: pl.DataFrame,
    splits: pl.DataFrame | None,
    ciks: pl.DataFrame,
    daily: pl.DataFrame,
    intervals: pl.DataFrame,
    max_gap_days: int = LEVEL_MAX_GAP_DAYS,
) -> pl.DataFrame:
    """LEVEL_SCHEMA rows: for every removed name, the median over the
    float dates inside its membership of

        close x cover count (in the price basis) / EntityPublicFloat

    the H1 ratio with the count taken straight from the cover page: no
    share override, no plausibility guard, so a name whose count was
    marked unresolved *because* its price was wrong (COL, EP, GR) is
    measured rather than skipped. ``floats`` and ``cover`` are the
    first-filed tables (shares.FLOAT_SCHEMA, COVER_SCHEMA); the count is
    the one dated nearest the float date within ``max_gap_days``, scaled
    by the splits after its filing date (shares.split_factor); the close
    is the last on or before the float date, within 40 days."""
    from backtester import shares
    from backtester.fundamentals import first_filed
    from backtester.sectors import cik_at

    if not floats.height or not cover.height:
        return pl.DataFrame(schema=LEVEL_SCHEMA)
    removed = (
        intervals.filter(pl.col("end").is_not_null())
        .group_by("ticker")
        .agg(pl.col("start").min().alias("_ms"), pl.col("end").max().alias("_me"))
    )
    stamp = [pl.lit("x").alias("concept"), pl.lit(0, dtype=pl.Int32).alias("qtrs")]
    ff = first_filed(floats.with_columns(stamp)).select(
        "cik", pl.col("ddate").alias("float_date"), pl.col("value").alias("float")
    )
    cv = first_filed(cover.with_columns(stamp)).select(
        "cik",
        pl.col("ddate").alias("_cd"),
        pl.col("filed").alias("cover_filed"),
        pl.col("value").alias("count"),
    )
    j = (
        ff.join(cv, on="cik", how="inner")
        .with_columns(
            (pl.col("_cd") - pl.col("float_date")).dt.total_days().abs().alias("_gap")
        )
        .filter(pl.col("_gap") <= max_gap_days)
        .sort("_gap", "_cd")
        .unique(subset=["cik", "float_date"], keep="first", maintain_order=True)
        .with_columns(pl.col("float_date").dt.month_end().alias("month"))
    )
    if not j.height:
        return pl.DataFrame(schema=LEVEL_SCHEMA)
    who = cik_at(ciks, sorted(j.get_column("month").unique().to_list()))
    j = (
        j.join(who, on=["month", "cik"], how="inner")
        .join(removed, on="ticker", how="inner")
        .filter(
            (pl.col("float_date") >= pl.col("_ms"))
            & (pl.col("float_date") <= pl.col("_me"))
        )
    )
    j = shares.split_factor(j, splits, basis_col="cover_filed")
    px = (
        daily.select("date", "ticker", "close")
        .join(j.select("ticker", "float_date").unique(), on="ticker", how="inner")
        .filter(pl.col("date") <= pl.col("float_date"))
        .sort("date")
        .group_by("ticker", "float_date")
        .agg(pl.col("close").last(), pl.col("date").last().alias("_pxd"))
    )
    j = (
        j.join(px, on=["ticker", "float_date"], how="inner")
        .filter(pl.col("_pxd") >= pl.col("float_date").dt.offset_by("-40d"))
        .with_columns(
            (
                pl.col("close")
                * pl.col("count")
                * pl.col("split_factor")
                / pl.col("float")
            ).alias("_level")
        )
    )
    return (
        j.group_by("ticker")
        .agg(
            pl.col("_level").median().alias("level"),
            pl.col("_level").min().alias("level_min"),
            pl.col("_level").max().alias("level_max"),
            pl.len().cast(pl.Int64).alias("n_levels"),
        )
        .select(list(LEVEL_SCHEMA))
        .sort("ticker")
    )


def identity_check(
    intervals: pl.DataFrame,
    info: dict[str, dict],
    first_prices: pl.DataFrame,
    sec_names: pl.DataFrame | None = None,
    levels: pl.DataFrame | None = None,
    band: tuple[float, float] = (0.5, 20.0),
    history_start: date = HISTORY_START,
) -> pl.DataFrame:
    """IDENTITY_SCHEMA rows, one per ticker that ever left the index.

    ``intervals`` is the membership table (ticker, security, start, end);
    a removed name is one with an end. ``info`` is ``load_info`` output;
    ``first_prices`` is Frame[ticker, first_price] from the daily series.
    ``sec_names`` (ticker, sec_name: the registrant's names in its own
    filings, "|"-joined) is a second reference for the name test, so a
    company that renamed itself is not a mismatch; the overlap kept is
    the larger. ``levels`` is ``price_levels`` output and ``band`` the
    public-float band from config.

    Flagged, with the reason naming which:
      name    yfinance carries a real name and its overlap with every
              reference is under IDENTITY_OVERLAP
      quote   a live quote (not a placeholder) in a currency other than
              USD, of a type other than EQUITY (an ETF now holds the
              symbol), or on an exchange outside US_EXCHANGES when the
              name does not confirm the company (a name that matches
              and now trades over the counter is the company, delisted)
      level   the median price level over the membership is outside
              ``band``: the series is not at that filer's price
      late    the first price is more than IDENTITY_LATE_MONTHS after
              the later of the membership start and the history start,
              and inside the membership, and no level inside the band
              says the short series is merely truncated (HOT, SCG)
    A symbol yfinance has no ``info`` for is ``no_info``, recorded and
    not flagged on that account; the level and late tests still apply.
    A placeholder quote (PLACEHOLDER_EXCHANGES / PLACEHOLDER_TYPES) is
    treated the same way for the quote test.
    """
    lo, hi = band
    removed = (
        intervals.filter(pl.col("end").is_not_null())
        .group_by("ticker")
        .agg(
            pl.col("security")
            .unique(maintain_order=True)
            .str.join("|")
            .alias("wiki_name"),
            pl.col("start").min().alias("member_start"),
            pl.col("end").max().alias("member_end"),
        )
        .join(first_prices.select("ticker", "first_price"), on="ticker", how="left")
        .sort("ticker")
    )
    if levels is not None and levels.height:
        removed = removed.join(
            levels.select("ticker", "level", "n_levels"), on="ticker", how="left"
        )
    else:
        removed = removed.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("level"),
            pl.lit(None, dtype=pl.Int64).alias("n_levels"),
        )
    sec = {}
    if sec_names is not None and sec_names.height:
        sec = dict(zip(sec_names["ticker"], sec_names["sec_name"], strict=True))
    rows = []
    for r in removed.to_dicts():
        t = r["ticker"]
        i = info.get(t) or {}
        yf_name = i.get("longName") or i.get("shortName")
        candidates = r["wiki_name"].split("|") + (sec.get(t) or "").split("|")
        overlaps = [name_overlap(c, yf_name) for c in candidates if c]
        overlaps = [o for o in overlaps if o is not None]
        overlap = max(overlaps) if overlaps and is_real_name(yf_name) else None
        placeholder = (
            i.get("exchange") in PLACEHOLDER_EXCHANGES
            or i.get("quoteType") in PLACEHOLDER_TYPES
        )
        level = r["level"]
        in_band = level is not None and lo <= level <= hi
        name_ok = overlap is not None and overlap >= IDENTITY_OVERLAP
        reasons = []
        if not i:
            reasons.append("no_info")
        else:
            if overlap is not None and not name_ok:
                reasons.append(f"name overlap {overlap:.2f}")
            if not placeholder:
                if i.get("currency") and i["currency"] != "USD":
                    reasons.append(f"currency {i['currency']}")
                # Where the symbol trades now says whose it is only when
                # the name does not: Signature Bank's matches and it is
                # quoted on the pink sheets since it failed.
                if (
                    i.get("exchange")
                    and i["exchange"] not in US_EXCHANGES
                    and not name_ok
                ):
                    reasons.append(f"exchange {i['exchange']}")
                if i.get("quoteType") and i["quoteType"] != "EQUITY":
                    reasons.append(f"quote type {i['quoteType']}")
        if level is not None and not in_band:
            reasons.append(f"price level {level:.4g} outside [{lo:g}, {hi:g}]")
        since = max(r["member_start"], history_start)
        late = pl.Series([since]).dt.offset_by(f"{IDENTITY_LATE_MONTHS}mo").item()
        fp = r["first_price"]
        if fp is not None and late < fp <= r["member_end"] and not in_band:
            reasons.append(
                f"first price {fp} is over {IDENTITY_LATE_MONTHS} months after "
                f"membership start {since}"
            )
        flag = any(x != "no_info" for x in reasons)
        rows.append(
            {
                "ticker": t,
                "wiki_name": r["wiki_name"],
                "sec_name": sec.get(t),
                "yf_name": yf_name,
                "overlap": overlap,
                "exchange": i.get("exchange"),
                "currency": i.get("currency"),
                "quote_type": i.get("quoteType"),
                "first_price": fp,
                "member_start": r["member_start"],
                "member_end": r["member_end"],
                "level": level,
                "n_levels": r["n_levels"],
                "flag": flag,
                "reason": "; ".join(reasons),
            }
        )
    return pl.DataFrame(rows, schema=IDENTITY_SCHEMA)


def sec_names_by_ticker(cfg: Config) -> pl.DataFrame | None:
    """Frame[ticker, sec_name]: every name the ticker's registrant(s) filed
    under, "|"-joined, from the CIK map and the filer index."""
    from backtester import fundamentals

    sectors_p = cfg.data / "interim" / "sectors.parquet"
    if not sectors_p.exists():
        return None
    ciks = pl.read_parquet(sectors_p).select("ticker", "cik").unique()
    # load_sub ingests the filer index when the cache is absent, so a
    # fresh tree (the recompute) sees the same names as the incremental
    # one; without this the 2026-09-16 recompute flagged eight names
    # (AIV, ATI, BEAM, CNX, OI, PCG, Q, VFC) the EDGAR name had cleared.
    names = (
        fundamentals.load_sub(cfg)
        .select("cik", "name")
        .unique()
        .group_by("cik")
        .agg(pl.col("name").sort().str.join("|").alias("sec_name"))
    )
    return (
        ciks.join(names, on="cik", how="inner")
        .sort("ticker", "cik")
        .group_by("ticker", maintain_order=True)
        .agg(pl.col("sec_name").str.join("|"))
    )


# --- pipeline entry -----------------------------------------------------


def build(cfg: Config) -> pl.DataFrame:
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    tickers = sorted(set(membership["ticker"].to_list())) + [MARKET]
    daily = build_daily(cfg.data / "raw", tickers)
    as_of = daily["date"].max()
    market = daily.filter(pl.col("ticker") == MARKET)
    daily, clean_log = clean_daily(daily.filter(pl.col("ticker") != MARKET), membership)
    checks = cfg.data / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    clean_log.write_csv(checks / "price_cleaning.csv")
    # A second source, where fetched (FIX_PLAN F6): yfinance where the two
    # agree, Tiingo where they conflict or where only it has the name.
    from backtester import sources

    daily, conflicts = sources.merge(
        daily, sources.load_tiingo(cfg), cfg.price_conflict_threshold
    )
    conflicts.write_csv(checks / "price_conflicts.csv")
    daily = pl.concat(
        [daily, market.with_columns(pl.lit("yfinance").alias("source"))]
    ).sort("ticker", "date")

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
        "tickers_from_tiingo": stocks.filter(pl.col("source") == "tiingo")[
            "ticker"
        ].n_unique(),
        "conflict_months": conflicts.height,
        "conflict_pct_of_ticker_months": round(
            100 * conflicts.height / max(monthly.height, 1), 3
        ),
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


def terminal_returns(
    monthly: pl.DataFrame,
    membership: pl.DataFrame,
    daily: pl.DataFrame,
    shock: float,
    grace_days: int = 45,
    delistings: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The 'terminal' delisting convention (BUILD_PLAN 8.2).

    A name removed from the index whose last daily print is within
    ``grace_days`` of its removal has no price after it: the position
    cannot be closed at a later close. The base run closes it at the last
    print (its forward return that month is null and it drops out). Here
    the last priced month-end earns ``shock`` instead. Names that keep
    trading after removal, and names with no prices at all, are
    unchanged. Returns the modified frame and the list of names touched.

    With ``delistings`` (FIX_PLAN F6, data/checks/delistings.csv) each
    touched name is classed by sources.classify_removed: ``acquired``
    (a delisting date on record and a last close within 20% of the prior
    month-end) earns its last actual return, which is nothing further
    after the last print, so 0 rather than the shock; ``failed`` and
    ``unknown`` earn the shock. The class is in the returned log.
    """
    from backtester import sources

    last_px = daily.group_by("ticker").agg(pl.col("date").max().alias("last_px"))
    removed = (
        membership.filter(pl.col("end").is_not_null())
        .group_by("ticker")
        .agg(pl.col("end").max())
        .join(last_px, on="ticker", how="inner")
        .filter(pl.col("last_px") <= pl.col("end").dt.offset_by(f"{grace_days}d"))
    )
    last_month = (
        monthly.filter(pl.col("px_me").is_not_null())
        .group_by("ticker")
        .agg(pl.col("month").max())
        .join(removed.select("ticker", "end", "last_px"), on="ticker", how="inner")
    )
    classes = sources.classify_removed(membership, daily, delistings, grace_days)
    touched = (
        last_month.select("ticker", "end", "last_px", "month")
        .join(
            classes.select("ticker", "delisting_date", "class"), on="ticker", how="left"
        )
        .with_columns(pl.col("class").fill_null("unknown"))
        .sort("end")
    )
    out = monthly.join(
        touched.select("ticker", "month", pl.lit(True).alias("_terminal"), "class"),
        on=["ticker", "month"],
        how="left",
    ).with_columns(
        pl.when(pl.col("_terminal") & pl.col("ret_fwd").is_null())
        .then(pl.when(pl.col("class") == "acquired").then(0.0).otherwise(pl.lit(shock)))
        .otherwise(pl.col("ret_fwd"))
        .alias("ret_fwd")
    )
    return out.drop("_terminal", "class"), touched
