"""FIX_PLAN F5: the beta hedge removes the market beta and looks only
backwards."""

from datetime import date

import numpy as np
import polars as pl

from backtester import portfolio, stats
from backtester.universe import month_ends


def _series(n: int = 120, seed: int = 7) -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(seed)
    months = month_ends(date(2010, 1, 31), date(2030, 12, 31))[:n]
    mkt = rng.normal(0.005, 0.04, n)
    # French stamps the month the return is earned: one month after formation.
    french = pl.DataFrame(
        {"month": month_ends(date(2010, 2, 28), date(2030, 12, 31))[:n], "mkt_rf": mkt}
    )
    ls = pl.DataFrame(
        {
            "month": months,
            "ret_gross": -0.5 * mkt,
            "ret_net": -0.5 * mkt - 0.001,
            "turnover": [0.2] * n,
        }
    )
    return ls, french


def test_a_series_that_is_minus_half_the_market_hedges_to_beta_zero() -> None:
    ls, french = _series()
    out = portfolio.beta_hedge(ls, french)
    assert out.height == ls.height - portfolio.HEDGE_MIN_MONTHS
    assert (out["beta"] + 0.5).abs().max() < 1e-8
    earned = stats.to_month_earned(out).join(french, on="month", how="inner")
    slope = np.polyfit(earned["mkt_rf"].to_numpy(), earned["ret_gross"].to_numpy(), 1)[
        0
    ]
    assert abs(slope) < 1e-8
    # The cost stays: the net series is the gross series less the same fee.
    assert ((out["ret_gross"] - out["ret_net"]) - 0.001).abs().max() < 1e-12


def test_the_beta_at_t_uses_no_month_at_or_after_t() -> None:
    ls, french = _series()
    # Break the relationship from month 60 on: a beta that peeked would move
    # at 60; a backward-looking one moves only from 61 and settles later.
    ls2 = ls.with_columns(
        pl.when(pl.col("month") >= ls["month"][60])
        .then(pl.col("ret_gross") * 0.0 + 0.02)
        .otherwise(pl.col("ret_gross"))
        .alias("ret_gross")
    )
    out = portfolio.beta_hedge(ls2, french)
    betas = dict(zip(out["month"], out["beta"], strict=True))
    assert abs(betas[ls["month"][60]] + 0.5) < 1e-8  # month 60 still sees only the past
    assert abs(betas[ls["month"][61]] + 0.5) > 1e-6  # month 61 sees month 60
    assert abs(betas[ls["month"][100]]) < 0.05  # the window has rolled past the break
