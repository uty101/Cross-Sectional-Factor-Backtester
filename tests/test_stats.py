import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from backtester import stats

rng = np.random.default_rng(7)


def test_newey_west_matches_statsmodels() -> None:
    sm = pytest.importorskip("statsmodels.api")
    x = rng.normal(size=300).cumsum() * 0.01 + rng.normal(size=300)
    for lags in (0, 1, 3, 6):
        ours = stats.newey_west_variance(x, lags)
        fit = sm.OLS(x, np.ones(len(x))).fit(
            cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": False}
        )
        theirs = float(np.asarray(fit.cov_params())[0, 0])
        assert abs(ours - theirs) / theirs < 1e-9


def test_newey_west_with_zero_lags_is_the_plain_variance_of_the_mean() -> None:
    x = rng.normal(size=100)
    assert abs(stats.newey_west_variance(x, 0) - x.var(ddof=0) / len(x)) < 1e-12


def test_deflated_sharpe_worked_example() -> None:
    # Normal returns: skew 0, kurtosis 3 -> denominator sqrt(1 + SR^2 / 2).
    sr, T = 0.2, 121
    sr0, dsr = stats.deflated_sharpe(
        sr, sr_var_trials=0.0, n_trials=1, T=T, skew=0.0, kurt=3.0
    )
    assert sr0 == 0.0
    z = sr * math.sqrt(T - 1) / math.sqrt(1 + sr**2 / 2)
    from scipy.stats import norm

    assert abs(dsr - norm.cdf(z)) < 1e-12
    # More trials with dispersion raise the hurdle and lower the DSR.
    _, dsr10 = stats.deflated_sharpe(
        sr, sr_var_trials=0.01, n_trials=10, T=T, skew=0.0, kurt=3.0
    )
    _, dsr100 = stats.deflated_sharpe(
        sr, sr_var_trials=0.01, n_trials=100, T=T, skew=0.0, kurt=3.0
    )
    assert dsr > dsr10 > dsr100


def test_sharpe_and_drawdown() -> None:
    r = np.array([0.1, -0.5, 0.2, 0.2])
    assert abs(stats.max_drawdown(r) + 0.5) < 1e-12
    assert (
        abs(
            stats.sharpe(np.array([0.01] * 12 + [0.03] * 12))
            - (0.02 / np.std([0.01] * 12 + [0.03] * 12, ddof=1) * math.sqrt(12))
        )
        < 1e-12
    )
    assert math.isnan(stats.sharpe(np.array([0.01, 0.01])))


def test_ic_and_fama_macbeth_recover_a_planted_relationship() -> None:
    months = [date(2020, m, 1) for m in range(1, 13)]
    months = [pl.Series([d]).dt.month_end()[0] for d in months]
    rows = []
    for m in months:
        z = rng.normal(size=200)
        r = 0.01 * z + rng.normal(scale=0.02, size=200)
        rows += [
            {"month": m, "ticker": f"T{i}", "z": z[i], "ret_fwd": r[i]}
            for i in range(200)
        ]
    df = pl.DataFrame(rows)
    ic = stats.ic_series(
        df.select("month", "ticker", "z"), df.select("month", "ticker", "ret_fwd")
    )
    s = stats.ic_summary(ic)
    assert s["months"] == 12 and s["mean_ic"] > 0.3 and s["ic_t"] > 5
    fm = stats.fama_macbeth(
        df.select("month", "ticker", "z"),
        df.select("month", "ticker", "ret_fwd"),
        lags=0,
    )
    assert abs(fm.mean - 0.01) < 0.003 and fm.t > 5


def test_attribution_recovers_planted_betas() -> None:
    n = 240
    months = pl.date_range(
        date(2000, 1, 31), date(2019, 12, 31), "1mo", eager=True
    ).dt.month_end()
    f = pl.DataFrame(
        {
            "month": months,
            "mkt_rf": rng.normal(scale=0.04, size=n),
            "hml": rng.normal(scale=0.03, size=n),
            "umd": rng.normal(scale=0.04, size=n),
            "rmw": rng.normal(scale=0.02, size=n),
        }
    )
    y = (
        0.002
        + 0.5 * f["umd"].to_numpy()
        - 0.3 * f["hml"].to_numpy()
        + rng.normal(scale=0.005, size=n)
    )
    # The long-short frame is stamped with the formation month = month earned - 1.
    ls = pl.DataFrame(
        {
            "month": months.dt.offset_by("-1mo").dt.month_end(),
            "ret_gross": y,
            "turnover": np.full(n, 0.5),
        }
    )
    a = stats.attribution(ls, f, lags=2)
    assert abs(a.betas["umd"] - 0.5) < 0.05 and abs(a.betas["hml"] + 0.3) < 0.05
    assert abs(a.alpha_monthly - 0.002) < 0.001 and a.alpha_t > 3
    assert a.months == n


def test_breakeven_cost_zeroes_the_mean_net_return() -> None:
    ls = pl.DataFrame({"ret_gross": [0.01, 0.02, 0.0], "turnover": [0.5, 0.5, 0.5]})
    c = stats.breakeven_cost(ls)
    assert abs(stats.net_series(ls, c).mean()) < 1e-15
    assert abs(c - 0.01) < 1e-12  # mean gross 1% / (2 * 0.5)


def test_ic_decay_half_life_of_a_planted_exponential() -> None:
    # Build a signal whose IC with h-month returns decays as exp(-h/6).
    months = pl.date_range(
        date(2015, 1, 31), date(2021, 12, 31), "1mo", eager=True
    ).dt.month_end()
    tickers = [f"T{i}" for i in range(300)]
    rows = []
    z_prev = None
    px = {t: 100.0 for t in tickers}
    z_by_month = {}
    for m in months:
        z = (
            rng.normal(size=300)
            if z_prev is None
            else 0.85 * z_prev + math.sqrt(1 - 0.85**2) * rng.normal(size=300)
        )
        z_by_month[m] = z
        # This month's return depends on last month's signal, so IC at
        # horizon h is proportional to 0.85 ** (h - 1): half-life ~4.3 months.
        drive = z_prev if z_prev is not None else np.zeros(300)
        for i, t in enumerate(tickers):
            px[t] *= 1 + 0.01 * drive[i] + rng.normal(scale=0.03)
            rows.append({"month": m, "ticker": t, "px_me": px[t]})
        z_prev = z
    monthly = pl.DataFrame(rows)
    zf = pl.DataFrame(
        [
            {"month": m, "ticker": t, "z": z_by_month[m][i]}
            for m in months
            for i, t in enumerate(tickers)
        ]
    )
    table, hl = stats.ic_decay(zf, monthly, [1, 2, 3, 6, 12])
    assert table["mean_ic"][0] > table["mean_ic"][-1]
    assert 2 < hl < 8
