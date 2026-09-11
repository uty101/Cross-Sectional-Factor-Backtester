"""Statistics on portfolio and signal series.

    ic_series            Spearman rank IC per month
    ic_decay             IC at horizons 1, 2, 3, 6, 12 and a fitted half-life
    fama_macbeth         cross-sectional premia per month, Newey-West t-stat
    newey_west_variance  HAC variance of a mean, hand-written from the brief
    sharpe, annualised, max_drawdown
    deflated_sharpe      Bailey & Lopez de Prado, N from the specification log
    attribution          long-short on Mkt-RF, HML, UMD, RMW
    breakeven_cost       one-way cost at which the mean net return is zero

Newey-West is written from the formula in the brief and cross-checked
against statsmodels in a test; statsmodels is not a runtime dependency.
Monthly series are stamped with the formation month; anything compared
with a French factor is shifted to the month earned first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl
from scipy import stats as sps

EULER_GAMMA = 0.5772156649015329
PERIODS = 12


# --- information coefficient --------------------------------------------


def ic_series(
    z: pl.DataFrame, returns: pl.DataFrame, ret_col: str = "ret_fwd"
) -> pl.DataFrame:
    """Per month: Spearman correlation between z and the forward return, and n."""
    j = z.join(
        returns.select("month", "ticker", ret_col), on=["month", "ticker"], how="inner"
    )
    j = j.filter(pl.col(ret_col).is_not_null() & pl.col("z").is_finite())
    ranked = j.with_columns(
        pl.col("z").rank().over("month").alias("rz"),
        pl.col(ret_col).rank().over("month").alias("rr"),
    )
    return (
        ranked.group_by("month")
        .agg(pl.corr("rz", "rr").alias("ic"), pl.len().alias("n"))
        .filter(pl.col("n") >= 10)
        .sort("month")
    )


def ic_summary(ic: pl.DataFrame) -> dict:
    """Mean IC, its t-stat (plain, since monthly ICs at one horizon barely overlap),
    and the annualised IC information ratio from the brief."""
    x = ic["ic"].drop_nulls().to_numpy()
    if len(x) < 3:
        return {
            "mean_ic": float("nan"),
            "ic_t": float("nan"),
            "ic_ir": float("nan"),
            "months": len(x),
        }
    mean, sd = x.mean(), x.std(ddof=1)
    return {
        "mean_ic": float(mean),
        "ic_t": float(mean / (sd / math.sqrt(len(x)))),
        "ic_ir": float(mean / sd * math.sqrt(PERIODS)),
        "months": int(len(x)),
    }


def forward_returns(monthly: pl.DataFrame, horizons: list[int]) -> pl.DataFrame:
    """Frame[month, ticker, ret_h{h}...]: the return *in* month t+h, that is
    px_me(t+h) / px_me(t+h-1) - 1, on the consecutive monthly grid. Period
    returns rather than cumulative ones, so that the IC at each horizon is a
    separate reading and the curve is a decay, not an accumulation. Calendar
    returns; the decay curve is about the signal, not execution."""
    months = monthly.select("month").unique().sort("month")
    tickers = monthly.select("ticker").unique()
    grid = (
        months.join(tickers, how="cross")
        .join(
            monthly.select("month", "ticker", "px_me"),
            on=["month", "ticker"],
            how="left",
        )
        .sort("ticker", "month")
    )
    return grid.with_columns(
        [
            (
                pl.col("px_me").shift(-h).over("ticker")
                / pl.col("px_me").shift(-(h - 1)).over("ticker")
                - 1
            ).alias(f"ret_h{h}")
            for h in horizons
        ]
    ).select("month", "ticker", *[f"ret_h{h}" for h in horizons])


def ic_decay(
    z: pl.DataFrame, monthly: pl.DataFrame, horizons: list[int]
) -> tuple[pl.DataFrame, float]:
    """Mean IC of z(t) with the return over t -> t+h, and the half-life of an
    exponential fit IC_h = a * exp(-h / tau) (half-life = tau * ln 2).

    Fitted by least squares on the mean ICs; if the fit fails or the decay
    is not positive the half-life is nan and the table stands on its own.
    """
    fr = forward_returns(monthly, horizons)
    rows = []
    for h in horizons:
        s = ic_summary(ic_series(z, fr, f"ret_h{h}"))
        rows.append(
            {
                "horizon": h,
                "mean_ic": s["mean_ic"],
                "ic_t": s["ic_t"],
                "months": s["months"],
            }
        )
    table = pl.DataFrame(rows)
    hs = np.array(horizons, dtype=float)
    ics = table["mean_ic"].to_numpy()
    half_life = float("nan")
    try:
        from scipy.optimize import curve_fit

        (a, tau), _ = curve_fit(
            lambda h, a, tau: a * np.exp(-h / tau),
            hs,
            ics,
            p0=(max(ics[0], 1e-3), 6.0),
            maxfev=10000,
        )
        if tau > 0 and a > 0:
            half_life = float(tau * math.log(2))
    except (RuntimeError, ValueError):
        pass
    return table, half_life


# --- Fama-MacBeth and Newey-West ----------------------------------------


def newey_west_variance(x: np.ndarray, lags: int) -> float:
    """Variance of the mean of ``x`` with Bartlett-weighted autocovariances:

        Var = (1/T) [ g0 + 2 * sum_{l=1..L} (1 - l/(L+1)) g_l ]

    with g_l the lag-l autocovariance (divided by T, as in the brief).
    """
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    T = len(x)
    d = x - x.mean()
    g0 = float(d @ d) / T
    acc = g0
    for lag in range(1, lags + 1):
        gl = float(d[lag:] @ d[:-lag]) / T
        acc += 2.0 * (1.0 - lag / (lags + 1)) * gl
    return acc / T


@dataclass
class Premium:
    mean: float
    se: float
    t: float
    months: int
    lambdas: pl.DataFrame


def fama_macbeth(
    z: pl.DataFrame, returns: pl.DataFrame, lags: int, ret_col: str = "ret_fwd"
) -> Premium:
    """Each month, regress next-period returns on z (with an intercept); the
    premium is the mean slope, its standard error Newey-West with ``lags``."""
    j = z.join(
        returns.select("month", "ticker", ret_col), on=["month", "ticker"], how="inner"
    )
    j = j.filter(pl.col(ret_col).is_not_null() & pl.col("z").is_finite())
    lam = (
        j.group_by("month")
        .agg(
            (pl.cov("z", ret_col) / pl.col("z").var()).alias("lambda"),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") >= 10)
        .sort("month")
    )
    x = lam["lambda"].to_numpy()
    var = newey_west_variance(x, lags)
    se = math.sqrt(var)
    return Premium(
        float(x.mean()),
        se,
        float(x.mean() / se) if se > 0 else float("nan"),
        len(x),
        lam,
    )


# --- performance --------------------------------------------------------


def sharpe(r: np.ndarray | pl.Series, periods: int = PERIODS) -> float:
    x = np.asarray(r, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * math.sqrt(periods))


def annualised(
    r: np.ndarray | pl.Series, periods: int = PERIODS
) -> tuple[float, float]:
    """(arithmetic mean * periods, std * sqrt(periods))."""
    x = np.asarray(r, dtype=float)
    x = x[~np.isnan(x)]
    return float(x.mean() * periods), float(x.std(ddof=1) * math.sqrt(periods))


def max_drawdown(r: np.ndarray | pl.Series) -> float:
    """Largest peak-to-trough fall of the cumulative (compounded) series."""
    x = np.asarray(r, dtype=float)
    x = x[~np.isnan(x)]
    wealth = np.cumprod(1.0 + x)
    peak = np.maximum.accumulate(wealth)
    return float((wealth / peak - 1.0).min())


def deflated_sharpe(
    sr: float, sr_var_trials: float, n_trials: int, T: int, skew: float, kurt: float
) -> tuple[float, float]:
    """Bailey & Lopez de Prado (2014). Everything per period (monthly).

    SR0 = sqrt(V[SR]) * [ (1-g) Phi^-1(1 - 1/N) + g Phi^-1(1 - 1/(N e)) ]
    DSR = Phi( (SR - SR0) sqrt(T-1) / sqrt(1 - g3 SR + (g4-1)/4 SR^2) )

    Returns (SR0, DSR). ``kurt`` is the raw fourth moment (normal = 3).
    With N = 1 there is no selection, so SR0 = 0.
    """
    if n_trials <= 1 or sr_var_trials <= 0:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(sr_var_trials) * (
            (1 - EULER_GAMMA) * sps.norm.ppf(1 - 1 / n_trials)
            + EULER_GAMMA * sps.norm.ppf(1 - 1 / (n_trials * math.e))
        )
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    dsr = float(sps.norm.cdf((sr - sr0) * math.sqrt(T - 1) / denom))
    return sr0, dsr


def moments(r: np.ndarray | pl.Series) -> tuple[float, float]:
    """(skew, raw kurtosis) of a return series."""
    x = np.asarray(r, dtype=float)
    x = x[~np.isnan(x)]
    return float(sps.skew(x)), float(sps.kurtosis(x, fisher=False))


# --- attribution --------------------------------------------------------

FRENCH_FACTORS = ["mkt_rf", "hml", "umd", "rmw"]


@dataclass
class Attribution:
    alpha_monthly: float
    alpha_annual: float
    alpha_t: float
    betas: dict[str, float]
    beta_t: dict[str, float]
    r2: float
    months: int


def to_month_earned(long_short: pl.DataFrame) -> pl.DataFrame:
    """Re-stamp a formation-month series with the month its return is earned."""
    return long_short.with_columns(
        pl.col("month").dt.offset_by("1mo").dt.month_end().alias("month")
    )


def attribution(
    long_short: pl.DataFrame,
    french: pl.DataFrame,
    factors: list[str] = FRENCH_FACTORS,
    ret_col: str = "ret_gross",
    lags: int = 0,
) -> Attribution:
    """OLS of the long-short series on the French factors, HAC t-stats.

    The long-short series is a spread and needs no risk-free adjustment.
    """
    j = to_month_earned(long_short).join(
        french.select("month", *factors), on="month", how="inner"
    )
    j = j.drop_nulls([ret_col, *factors])
    y = j[ret_col].to_numpy()
    X = np.column_stack([np.ones(len(y)), j.select(factors).to_numpy()])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    # HAC sandwich with Bartlett weights, matching newey_west_variance.
    T = len(y)
    u = X * resid[:, None]
    S = u.T @ u / T
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        gl = u[lag:].T @ u[:-lag] / T
        S += w * (gl + gl.T)
    cov = XtX_inv @ (S * T) @ XtX_inv
    se = np.sqrt(np.diag(cov))
    r2 = 1 - resid.var() / y.var() if y.var() > 0 else float("nan")
    return Attribution(
        float(beta[0]),
        float(beta[0] * PERIODS),
        float(beta[0] / se[0]),
        {f: float(b) for f, b in zip(factors, beta[1:], strict=True)},
        {f: float(b / s) for f, b, s in zip(factors, beta[1:], se[1:], strict=True)},
        float(r2),
        T,
    )


# --- costs --------------------------------------------------------------


def breakeven_cost(long_short: pl.DataFrame) -> float:
    """One-way cost (decimal) at which the mean net return is zero, under
    ret_net = ret_gross - 2c * turnover: c* = mean(gross) / (2 mean(turnover))."""
    g = long_short["ret_gross"].mean()
    to = long_short["turnover"].mean()
    return float(g / (2 * to)) if to and to > 0 else float("nan")


def net_series(long_short: pl.DataFrame, cost: float) -> np.ndarray:
    """Net returns at an arbitrary one-way cost (decimal)."""
    return (long_short["ret_gross"] - 2 * cost * long_short["turnover"]).to_numpy()


def sharpe_by_cost(long_short: pl.DataFrame, costs_bps: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cost_bps": costs_bps,
            "sharpe_net": [sharpe(net_series(long_short, c / 1e4)) for c in costs_bps],
        }
    )
