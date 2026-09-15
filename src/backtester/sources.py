"""A second daily price source and real delisting dates (FIX_PLAN F6).

    fetch_tiingo       daily adjusted closes per ticker from Tiingo, key
                       TIINGO_API_KEY; one parquet per fetch date, never
                       overwritten
    fetch_delistings   Alpha Vantage LISTING_STATUS state=delisted, key
                       ALPHAVANTAGE_API_KEY; the universe's rows to
                       data/checks/delistings.csv
    reconcile          monthly returns from both sources; a month where
                       they differ by more than the threshold is a conflict
    merge              yfinance where the two agree, Tiingo where they
                       conflict, Tiingo where only it has the name; the
                       source is recorded per row
    classify_removed   acquired / failed / unknown per removed name, from
                       the delisting date and the last print against the
                       prior month-end

yfinance stitches reused symbols (Rockwell Collins' COL is a penny stock
under the same symbol from 2012) and has no history for names delisted
more than a few weeks ago. A second source that keeps delisted names is
the only way to see either. Both fetches skip, and say so, when their key
is absent; every downstream table is then what yfinance alone gives, so
the pipeline never changes shape on a missing key.
"""

from __future__ import annotations

import io
import time
from datetime import date
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config, secret

TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
ALPHA_URL = "https://www.alphavantage.co/query"
TIINGO_SCHEMA = {
    "date": pl.Date,
    "ticker": pl.Utf8,
    "close": pl.Float64,
    "adj_close": pl.Float64,
    "volume": pl.Float64,
}
DELISTING_SCHEMA = {
    "ticker": pl.Utf8,
    "name": pl.Utf8,
    "exchange": pl.Utf8,
    "delisting_date": pl.Date,
}
ACQUIRED_BAND = 0.20  # last print within this of the prior month-end: acquired


# --- fetch --------------------------------------------------------------


def fetch_tiingo(
    cfg: Config,
    as_of: date,
    tickers: list[str] | None = None,
    start: date | None = None,
) -> list[Path]:
    """Daily prices for every universe ticker into
    data/raw/prices/tiingo_<as_of>.parquet. Backs off on the rate-limit
    headers Tiingo sends; a 404 (no such symbol) is recorded as no rows."""
    key = secret("TIINGO_API_KEY")
    if not key:
        print("TIINGO_API_KEY not set: Tiingo fetch skipped")
        return []
    import requests

    from backtester.prices import HISTORY_START, to_yahoo

    root = cfg.data / "raw"
    rel = f"prices/tiingo_{as_of.isoformat()}.parquet"
    if (root / rel).exists():
        return [root / rel]
    if tickers is None:
        membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
        tickers = sorted(set(membership["ticker"].to_list()))
    session = requests.Session()
    frames = []
    for i, t in enumerate(tickers, 1):
        params = {
            "startDate": (start or HISTORY_START).isoformat(),
            "endDate": as_of.isoformat(),
            "token": key,
            "format": "csv",
        }
        while True:
            r = session.get(
                TIINGO_URL.format(ticker=to_yahoo(t)), params=params, timeout=60
            )
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 60))
                print(f"Tiingo rate limit; waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            break
        if r.status_code == 404 or not r.text.strip() or r.text.startswith("Error"):
            continue
        r.raise_for_status()
        frames.append(parse_tiingo_csv(r.text, t))
        remaining = r.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) < 5:
            time.sleep(60)
        if i % 100 == 0:
            print(f"{i}/{len(tickers)} tickers", flush=True)
    out = pl.concat(frames) if frames else pl.DataFrame(schema=TIINGO_SCHEMA)
    buf = io.BytesIO()
    out.write_parquet(buf)
    return [raw.store_raw(root, rel, buf.getvalue(), TIINGO_URL.format(ticker="*"))]


def parse_tiingo_csv(text: str, ticker: str) -> pl.DataFrame:
    """Tiingo's daily CSV (date, close, ..., adjClose, ..., volume) -> TIINGO_SCHEMA."""
    df = pl.read_csv(io.StringIO(text), try_parse_dates=True)
    cols = {c.lower(): c for c in df.columns}
    return df.select(
        pl.col(cols["date"]).cast(pl.Date).alias("date"),
        pl.lit(ticker).alias("ticker"),
        pl.col(cols["close"]).cast(pl.Float64).alias("close"),
        pl.col(cols["adjclose"]).cast(pl.Float64).alias("adj_close"),
        pl.col(cols["volume"]).cast(pl.Float64).alias("volume"),
    ).filter(pl.col("adj_close") > 0)


def fetch_delistings(cfg: Config, as_of: date) -> list[Path]:
    """Alpha Vantage's delisted-symbol list into data/raw/delistings_<as_of>.csv,
    and the universe's rows into data/checks/delistings.csv."""
    key = secret("ALPHAVANTAGE_API_KEY")
    if not key:
        print("ALPHAVANTAGE_API_KEY not set: delisting fetch skipped")
        return []
    import requests

    root = cfg.data / "raw"
    rel = f"delistings_{as_of.isoformat()}.csv"
    if not (root / rel).exists():
        r = requests.get(
            ALPHA_URL,
            params={"function": "LISTING_STATUS", "state": "delisted", "apikey": key},
            timeout=120,
        )
        r.raise_for_status()
        raw.store_raw(root, rel, r.content, ALPHA_URL + "?function=LISTING_STATUS")
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    universe = set(membership["ticker"].to_list())
    delistings(root / rel, universe).write_csv(cfg.data / "checks" / "delistings.csv")
    return [root / rel]


def delistings(path: Path, universe: set[str]) -> pl.DataFrame:
    """DELISTING_SCHEMA rows for the tickers in ``universe`` from the raw
    LISTING_STATUS csv (symbol, name, exchange, assetType, ipoDate,
    delistingDate, status). Yahoo's dash for a share class becomes the
    universe's dot."""
    df = pl.read_csv(path, infer_schema_length=0)
    cols = {c.lower(): c for c in df.columns}
    out = df.select(
        pl.col(cols["symbol"]).str.replace("-", ".").alias("ticker"),
        pl.col(cols["name"]).alias("name"),
        pl.col(cols["exchange"]).alias("exchange"),
        pl.col(cols["delistingdate"])
        .str.strptime(pl.Date, "%Y-%m-%d", strict=False)
        .alias("delisting_date"),
    )
    return (
        out.filter(pl.col("ticker").is_in(sorted(universe)))
        .sort("delisting_date", "ticker")
        .select(list(DELISTING_SCHEMA))
    )


def load_tiingo(cfg: Config) -> pl.DataFrame | None:
    try:
        p = raw.latest(cfg.data / "raw", "prices/tiingo_*.parquet")
    except FileNotFoundError:
        return None
    return pl.read_parquet(p)


def load_delistings(cfg: Config) -> pl.DataFrame | None:
    p = cfg.data / "checks" / "delistings.csv"
    if not p.exists():
        return None
    return pl.read_csv(p, schema_overrides=DELISTING_SCHEMA)


# --- reconcile and merge --------------------------------------------------


def month_end_returns(daily: pl.DataFrame) -> pl.DataFrame:
    """Frame[month, ticker, ret]: calendar-month return from the last
    adjusted close of each month, per source."""
    me = (
        daily.with_columns(pl.col("date").dt.month_end().alias("month"))
        .sort("ticker", "date")
        .group_by("ticker", "month", maintain_order=True)
        .agg(pl.col("adj_close").last().alias("px"))
        .sort("ticker", "month")
    )
    return me.with_columns(
        (pl.col("px") / pl.col("px").shift(1).over("ticker") - 1).alias("ret")
    ).select("month", "ticker", "ret")


def reconcile(yf: pl.DataFrame, tiingo: pl.DataFrame, threshold: float) -> pl.DataFrame:
    """Frame[month, ticker, ret_yf, ret_tiingo, diff, conflict] for every
    (month, ticker) both sources price; ``conflict`` where the monthly
    returns differ by more than ``threshold``."""
    a = month_end_returns(yf).rename({"ret": "ret_yf"})
    b = month_end_returns(tiingo).rename({"ret": "ret_tiingo"})
    j = a.join(b, on=["month", "ticker"], how="inner").filter(
        pl.col("ret_yf").is_not_null() & pl.col("ret_tiingo").is_not_null()
    )
    return j.with_columns(
        (pl.col("ret_yf") - pl.col("ret_tiingo")).abs().alias("diff")
    ).with_columns((pl.col("diff") > threshold).alias("conflict"))


def merge(
    yf: pl.DataFrame, tiingo: pl.DataFrame | None, threshold: float
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(daily, conflicts). yfinance rows where the two sources agree on the
    month or where Tiingo has nothing; Tiingo rows for a month the two
    conflict on and for a name only Tiingo has. Every row carries
    ``source``; ``conflicts`` is the reconcile frame's conflict rows."""
    if tiingo is None or tiingo.height == 0:
        return yf.with_columns(pl.lit("yfinance").alias("source")), pl.DataFrame(
            schema={
                "month": pl.Date,
                "ticker": pl.Utf8,
                "ret_yf": pl.Float64,
                "ret_tiingo": pl.Float64,
                "diff": pl.Float64,
                "conflict": pl.Boolean,
            }
        )
    rec = reconcile(yf, tiingo, threshold)
    conflicts = rec.filter(pl.col("conflict"))
    yf_m = yf.with_columns(pl.col("date").dt.month_end().alias("month"))
    ti_m = tiingo.with_columns(pl.col("date").dt.month_end().alias("month"))
    bad = conflicts.select("month", "ticker").with_columns(pl.lit(True).alias("_c"))
    keep_yf = (
        yf_m.join(bad, on=["month", "ticker"], how="left")
        .filter(pl.col("_c").is_null())
        .drop("_c", "month")
        .with_columns(pl.lit("yfinance").alias("source"))
    )
    yf_names = set(yf["ticker"].unique().to_list())
    from_tiingo_conflict = (
        ti_m.join(bad, on=["month", "ticker"], how="inner")
        .drop("_c", "month")
        .with_columns(pl.lit("tiingo").alias("source"))
    )
    only_tiingo = (
        ti_m.filter(~pl.col("ticker").is_in(sorted(yf_names)))
        .drop("month")
        .with_columns(pl.lit("tiingo").alias("source"))
    )
    cols = [*TIINGO_SCHEMA, "source"]
    out = pl.concat(
        [
            keep_yf.select(cols),
            from_tiingo_conflict.select(cols),
            only_tiingo.select(cols),
        ]
    ).sort("ticker", "date")
    return out, conflicts


# --- delisting classes ----------------------------------------------------


def classify_removed(
    membership: pl.DataFrame,
    daily: pl.DataFrame,
    delistings: pl.DataFrame | None,
    grace_days: int = 45,
) -> pl.DataFrame:
    """Frame[ticker, end, last_px, delisting_date, last_close, prior_me_close,
    class] for every removed name whose last print is within
    ``grace_days`` of its removal (the names the terminal rule touches).

    acquired  a delisting date is on record and the last close is within
              ACQUIRED_BAND of the close at the prior month-end: the
              shares were bought, the last actual return stands
    failed    a delisting date is on record and the last close is more
              than ACQUIRED_BAND below the prior month-end: the shock
    unknown   no delisting record for the name: the shock
    """
    if "close" not in daily.columns:  # a dates-only frame: nothing to class by
        daily = daily.with_columns(pl.lit(None, dtype=pl.Float64).alias("close"))
    last = (
        daily.sort("ticker", "date")
        .group_by("ticker", maintain_order=True)
        .agg(
            pl.col("date").last().alias("last_px"),
            pl.col("close").last().alias("last_close"),
        )
    )
    removed = (
        membership.filter(pl.col("end").is_not_null())
        .group_by("ticker")
        .agg(pl.col("end").max())
        .join(last, on="ticker", how="inner")
        .filter(pl.col("last_px") <= pl.col("end").dt.offset_by(f"{grace_days}d"))
    )
    prior = (
        daily.with_columns(pl.col("date").dt.month_end().alias("month"))
        .sort("ticker", "date")
        .group_by("ticker", "month", maintain_order=True)
        .agg(pl.col("close").last().alias("prior_me_close"))
    )
    removed = removed.with_columns(
        pl.col("last_px").dt.offset_by("-1mo").dt.month_end().alias("month")
    ).join(prior, on=["ticker", "month"], how="left")
    if delistings is not None and delistings.height:
        removed = removed.join(
            delistings.select("ticker", "delisting_date"), on="ticker", how="left"
        )
    else:
        removed = removed.with_columns(
            pl.lit(None, dtype=pl.Date).alias("delisting_date")
        )
    within = (
        pl.col("last_close") / pl.col("prior_me_close") - 1
    ).abs() <= ACQUIRED_BAND
    return (
        removed.with_columns(
            pl.when(pl.col("delisting_date").is_null())
            .then(pl.lit("unknown"))
            .when(pl.col("prior_me_close").is_not_null() & within)
            .then(pl.lit("acquired"))
            .otherwise(pl.lit("failed"))
            .alias("class")
        )
        .select(
            "ticker",
            "end",
            "last_px",
            "delisting_date",
            "last_close",
            "prior_me_close",
            "class",
        )
        .sort("end", "ticker")
    )
