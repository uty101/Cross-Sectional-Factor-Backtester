"""Price identity: is the series under a ticker that filer's price?

    float_windows      flagged public-float rows -> 12-month exclusion windows
    write_exclusions   the float and identity windows -> data/checks/
                       price_identity_exclusions.csv (FIX_PLAN_3 H1, H2)
    load_exclusions    the file, or an empty frame before either check ran
    apply              drop the listed ticker-months from a (month, ticker)
                       frame; log the count per month (H3)

Every real bug in this repo was caught by comparing the pipeline's number
with an external one. The 10-K cover page carries two: the public float
(the SEC's own market value of the non-affiliate shares at the end of the
second fiscal quarter) and the share count. Price x count at the float
date must be at least the float and rarely more than a few times it, so
a ratio outside [0.5, 20] says the price, the count or the filer is
wrong, whatever the cause (a reused symbol resolved to another
instrument, a split basis, a thousands-for-units filing). The rule is
one list; each row says which check put it there.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from backtester.config import Config

EXCLUSIONS = "price_identity_exclusions.csv"
EXCLUSION_SCHEMA = {
    "ticker": pl.Utf8,
    "start": pl.Date,
    "end": pl.Date,
    "reason": pl.Utf8,
    "source_check": pl.Utf8,
}
FLOAT_EXCLUSION_MONTHS = 12


def float_windows(
    check: pl.DataFrame, months: int = FLOAT_EXCLUSION_MONTHS
) -> pl.DataFrame:
    """EXCLUSION_SCHEMA rows for every flagged row of
    ``fundamentals.public_float_check`` output: the ``months`` after the
    float date, ``source_check = public_float``. A missing float is not a
    flag and produces nothing, and neither does a flag whose reason is
    ``float_scale``: there the filed float is the number that is wrong
    (fundamentals.FLOAT_REASONS)."""
    flagged = check.filter(
        pl.col("flag").is_in(["low", "high"]) & (pl.col("reason") != "float_scale")
    )
    if not flagged.height:
        return pl.DataFrame(schema=EXCLUSION_SCHEMA)
    return flagged.select(
        "ticker",
        pl.col("float_date").alias("start"),
        pl.col("float_date").dt.offset_by(f"{months}mo").alias("end"),
        pl.format(
            "FY{} cap/float {} ({}, {}): close {} x shares {} = {} against float {}",
            "fy",
            pl.col("ratio").round(4),
            "flag",
            "reason",
            pl.col("close").round(2),
            pl.col("shares").round(0),
            pl.col("cap").round(0),
            pl.col("public_float").round(0),
        ).alias("reason"),
        pl.lit("public_float").alias("source_check"),
    ).sort("ticker", "start")


def write_exclusions(
    cfg: Config, float_check: pl.DataFrame | None, identity: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Compose the exclusion list from both checks and write it. Either
    input may be None (its check has not run); the file then carries the
    other's rows only, so a rebuild never leaves a stale window behind."""
    parts = []
    if float_check is not None:
        parts.append(float_windows(float_check))
    if identity is not None and identity.height:
        parts.append(identity.select(list(EXCLUSION_SCHEMA)))
    out = (
        pl.concat(parts).sort("source_check", "ticker", "start")
        if parts
        else pl.DataFrame(schema=EXCLUSION_SCHEMA)
    )
    path = cfg.data / "checks" / EXCLUSIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(path)
    return out


def load_exclusions(cfg: Config) -> pl.DataFrame:
    path = cfg.data / "checks" / EXCLUSIONS
    if not path.exists():
        return pl.DataFrame(schema=EXCLUSION_SCHEMA)
    return pl.read_csv(path, schema_overrides=EXCLUSION_SCHEMA)


def excluded_months(exclusions: pl.DataFrame, months: list) -> pl.DataFrame:
    """Frame[month, ticker] of every month-end inside a window. A month
    is excluded when ``start <= month <= end``."""
    if not exclusions.height or not months:
        return pl.DataFrame(schema={"month": pl.Date, "ticker": pl.Utf8})
    grid = pl.DataFrame({"month": months}, schema={"month": pl.Date}).join(
        exclusions.select("ticker", "start", "end"), how="cross"
    )
    return (
        grid.filter(
            (pl.col("start") <= pl.col("month")) & (pl.col("month") <= pl.col("end"))
        )
        .select("month", "ticker")
        .unique()
        .sort("month", "ticker")
    )


def apply(
    frame: pl.DataFrame, exclusions: pl.DataFrame, log: Path | None = None
) -> pl.DataFrame:
    """``frame`` (any frame with month and ticker) without the excluded
    ticker-months. When ``log`` is given the count dropped per month is
    written there (data/checks/exclusions_applied.csv)."""
    months = sorted(frame.get_column("month").unique().to_list())
    drop = excluded_months(exclusions, months)
    if not drop.height:
        if log is not None:
            pl.DataFrame(schema={"month": pl.Date, "dropped": pl.Int64}).write_csv(log)
        return frame
    kept = frame.join(drop, on=["month", "ticker"], how="anti")
    if log is not None:
        hit = frame.join(drop, on=["month", "ticker"], how="semi")
        (
            hit.group_by("month")
            .agg(
                pl.len().alias("dropped"),
                pl.col("ticker").sort().str.join(" ").alias("tickers"),
            )
            .sort("month")
            .write_csv(log)
        )
    return kept


IDENTITY = "yf_identity.csv"


def load_identity_flags(cfg: Config) -> pl.DataFrame | None:
    """The flagged rows of ``prices.identity_check`` output
    (data/checks/yf_identity.csv) as EXCLUSION_SCHEMA windows covering the
    whole membership interval, ``source_check = identity``; None before
    the check has run. A membership with no end runs to the window's end."""
    path = cfg.data / "checks" / IDENTITY
    if not path.exists():
        return None
    df = pl.read_csv(
        path,
        schema_overrides={
            "member_start": pl.Date,
            "member_end": pl.Date,
            "first_price": pl.Date,
            "flag": pl.Boolean,
        },
    )
    flagged = df.filter(pl.col("flag"))
    if not flagged.height:
        return pl.DataFrame(schema=EXCLUSION_SCHEMA)
    return flagged.select(
        "ticker",
        pl.col("member_start").alias("start"),
        pl.col("member_end").fill_null(cfg.end).alias("end"),
        "reason",
        pl.lit("identity").alias("source_check"),
    ).sort("ticker", "start")
