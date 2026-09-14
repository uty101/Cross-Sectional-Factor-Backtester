"""Raw signals and the one normaliser that turns them into z-scores.

Each signal is a function returning Frame[month, ticker, value], built
from data available at the month-end it is stamped with. Then:

    normalise(raw, sectors, winsor) -> Frame[month, ticker, z]
        winsorise at the config percentiles within each month, demean
        within sector, divide by the sector standard deviation
    composite(zs) -> z
        average of z-scores per name, re-standardised within each month

Sign convention: a higher value is "better" for the long leg. Signals
where the literature goes long the low end (volatility, accruals, asset
growth) are negated at construction so that decile 10 is always the long
leg of the factor.
"""

from __future__ import annotations

import math

import polars as pl

SIGNAL_SCHEMA = {"month": pl.Date, "ticker": pl.Utf8, "value": pl.Float64}
MIN_SECTOR_NAMES = 5  # below this a sector's stats are too noisy; use the market


# --- price signals ------------------------------------------------------


def momentum_12_1(monthly: pl.DataFrame, back: int = 12, skip: int = 1) -> pl.DataFrame:
    """Cumulative return from month t-back to t-skip (invariant 5).

    ``monthly`` needs month, ticker, px_me on a consecutive monthly grid per
    ticker (as ``prices.monthly_returns`` produces). With back=12, skip=1
    the value at t is px(t-1) / px(t-12) - 1, so the most recent month is
    excluded.
    """
    grid = _consecutive_grid(monthly)
    return (
        grid.with_columns(
            (
                pl.col("px_me").shift(skip).over("ticker")
                / pl.col("px_me").shift(back).over("ticker")
                - 1
            ).alias("value")
        )
        .filter(pl.col("value").is_not_null() & pl.col("px_me").is_not_null())
        .select("month", "ticker", "value")
    )


def volatility(
    daily_returns: pl.DataFrame, month_ends: pl.DataFrame, window: int = 252
) -> pl.DataFrame:
    """Negative annualised std of daily returns over the trailing window at
    each month-end trading day ``t``. Negative so that decile 10 is low vol.
    Requires at least 80% of the window."""
    min_obs = int(window * 0.8)
    stats = (
        daily_returns.sort("ticker", "date")
        .with_columns(
            pl.col("ret")
            .rolling_std(window_size=window, min_samples=min_obs)
            .over("ticker")
            .alias("vol")
        )
        .select("date", "ticker", "vol")
    )
    return (
        month_ends.select("month", "t")
        .join(stats, left_on="t", right_on="date", how="inner")
        .filter(pl.col("vol").is_not_null())
        .select("month", "ticker", (-pl.col("vol") * math.sqrt(252)).alias("value"))
    )


def beta(
    daily_returns: pl.DataFrame,
    market_returns: pl.DataFrame,
    month_ends: pl.DataFrame,
    window: int = 252,
) -> pl.DataFrame:
    """Negative trailing market beta at each month-end (low beta = decile 10)."""
    min_obs = int(window * 0.8)
    joined = daily_returns.join(
        market_returns.rename({"ret": "mkt"}), on="date", how="inner"
    ).sort("ticker", "date")
    stats = joined.with_columns(
        pl.rolling_cov(
            pl.col("ret"), pl.col("mkt"), window_size=window, min_samples=min_obs
        )
        .over("ticker")
        .alias("cov"),
        pl.col("mkt")
        .rolling_var(window_size=window, min_samples=min_obs)
        .over("ticker")
        .alias("var"),
    ).select("date", "ticker", (pl.col("cov") / pl.col("var")).alias("beta"))
    return (
        month_ends.select("month", "t")
        .join(stats, left_on="t", right_on="date", how="inner")
        .filter(pl.col("beta").is_not_null())
        .select("month", "ticker", (-pl.col("beta")).alias("value"))
    )


def _consecutive_grid(monthly: pl.DataFrame) -> pl.DataFrame:
    """month x ticker grid so that ``shift`` over ticker steps one month."""
    months = monthly.select("month").unique().sort("month")
    tickers = monthly.select("ticker").unique()
    return (
        months.join(tickers, how="cross")
        .join(
            monthly.select("month", "ticker", "px_me"),
            on=["month", "ticker"],
            how="left",
        )
        .sort("ticker", "month")
    )


# --- normalisation ------------------------------------------------------


def winsorise(raw: pl.DataFrame, lo: float, hi: float) -> pl.DataFrame:
    """Clip ``value`` to its [lo, hi] quantiles within each month."""
    return raw.with_columns(
        pl.col("value")
        .clip(
            pl.col("value").quantile(lo, interpolation="linear").over("month"),
            pl.col("value").quantile(hi, interpolation="linear").over("month"),
        )
        .alias("value")
    )


def normalise(
    raw: pl.DataFrame,
    sectors: pl.DataFrame | None,
    winsor: tuple[float, float],
) -> pl.DataFrame:
    """Winsorise, then z-score within (month, sector).

    ``sectors`` is Frame[ticker, sector] or None for a plain cross-sectional
    z-score. A sector with fewer than MIN_SECTOR_NAMES names in a month, or
    a name with no sector, is standardised against the whole cross-section
    for that month instead.
    """
    # A frame that still carries its availability date is checked here
    # too: nothing after the month may reach a z-score (BUILD_PLAN 5.5).
    from backtester.fundamentals import assert_point_in_time

    for col in ("available_from", "filed"):
        assert_point_in_time(raw, col)
    df = winsorise(raw.filter(pl.col("value").is_finite()), *winsor)
    if sectors is None:
        df = df.with_columns(pl.lit("ALL").alias("sector"))
    else:
        df = df.join(sectors.select("ticker", "sector"), on="ticker", how="left")
        df = df.with_columns(pl.col("sector").fill_null("ALL"))
    df = df.with_columns(
        pl.len().over("month", "sector").alias("n_sector"),
    ).with_columns(
        pl.when(pl.col("n_sector") < MIN_SECTOR_NAMES)
        .then(pl.lit("ALL"))
        .otherwise(pl.col("sector"))
        .alias("sector")
    )
    market = df.with_columns(
        pl.col("value").mean().over("month").alias("mu_all"),
        pl.col("value").std().over("month").alias("sd_all"),
    )
    grouped = market.with_columns(
        pl.when(pl.col("sector") == "ALL")
        .then(pl.col("mu_all"))
        .otherwise(pl.col("value").mean().over("month", "sector"))
        .alias("mu"),
        pl.when(pl.col("sector") == "ALL")
        .then(pl.col("sd_all"))
        .otherwise(pl.col("value").std().over("month", "sector"))
        .alias("sd"),
    )
    return (
        grouped.filter(pl.col("sd") > 0)
        .select(
            "month",
            "ticker",
            ((pl.col("value") - pl.col("mu")) / pl.col("sd")).alias("z"),
        )
        .sort("month", "ticker")
    )


def composite(zs: list[pl.DataFrame]) -> pl.DataFrame:
    """Average of z-scores per (month, ticker), re-standardised per month.

    A name needs a z on every component to enter, so the composite is not
    quietly a single-signal factor for names missing data.
    """
    out = zs[0].rename({"z": "z_0"})
    for i, z in enumerate(zs[1:], start=1):
        out = out.join(z.rename({"z": f"z_{i}"}), on=["month", "ticker"], how="inner")
    cols = [c for c in out.columns if c.startswith("z_")]
    avg = out.select("month", "ticker", pl.mean_horizontal(cols).alias("value"))
    return normalise(avg, None, (0.0, 1.0))
