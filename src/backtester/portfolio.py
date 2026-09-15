"""The backtest engine. Accepts any signal frame shaped (month, ticker, z).

    backtest(signal_z, returns, cfg, caps=None, ...) -> BacktestResult

At each rebalance month the cross-section is cut into ``n_deciles`` by z
(decile 1 lowest, decile n highest); each decile is a portfolio, equal- or
cap-weighted; the long-short portfolio is decile n minus decile 1. A
position formed at month t earns ``ret_fwd`` for t, which ``prices``
defines from the execution close ``lag_days`` after the month-end
(invariant 4), so nothing in here touches prices directly.

Turnover is half the sum of absolute weight changes against the *drifted*
weights, both legs counted for long-short (invariant 6). Costs: every
dollar bought and every dollar sold pays the one-way cost c, so
``ret_net = ret_gross - c * sum|dw| = ret_gross - 2c * turnover``. The
brief writes ``ret_gross - c * turnover``, which with c one-way charges
half the true cost of replacing a position; the stricter form is used
here and the report says so. With ``holding_months`` > 1 the portfolio
is only re-formed every k months and drifts in between.

Every call appends one row to ``reports/specifications.csv`` (invariant
8) through ``speclog``; the distinct specifications in that file are
the N in the deflated Sharpe.

This module is the reuse surface for projects 2 and 7: swapping in a new
signal must be a change to the caller, not to this file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from backtester.config import Config
from backtester.speclog import (  # noqa: F401  (re-exported; the log moved to speclog)
    SPEC_COLUMNS,
    count_specifications,
    git_commit,
    log_specification,
    spec_kind,
)


@dataclass
class BacktestResult:
    factor: str
    deciles: pl.DataFrame  # month, decile, ret_gross, ret_net, turnover, n
    long_short: pl.DataFrame  # month, ret_gross, ret_net, turnover, n_long, n_short
    weights: pl.DataFrame  # month, ticker, decile, w


# --- pieces -------------------------------------------------------------


def assign_deciles(z: pl.DataFrame, n: int) -> pl.DataFrame:
    """Frame[month, ticker, z] -> Frame[month, ticker, z, decile], 1 = lowest."""
    return z.with_columns(
        (
            (pl.col("z").rank(method="ordinal").over("month") - 1)
            * n
            // pl.len().over("month")
            + 1
        )
        .cast(pl.Int32)
        .alias("decile")
    )


def weights(
    deciles: pl.DataFrame, caps: pl.DataFrame | None, weighting: str
) -> pl.DataFrame:
    """Per (month, decile): equal weights, or cap weights.

    ``caps`` is Frame[month, ticker, cap]; needed only for ``weighting="cw"``.
    """
    if weighting == "ew":
        return deciles.with_columns(
            (1.0 / pl.len().over("month", "decile")).alias("w")
        ).select("month", "ticker", "decile", "w")
    if caps is None:
        raise ValueError("cap weighting needs a caps frame")
    d = deciles.join(
        caps.select("month", "ticker", "cap"), on=["month", "ticker"], how="inner"
    )
    d = d.filter(pl.col("cap") > 0)
    return d.with_columns(
        (pl.col("cap") / pl.col("cap").sum().over("month", "decile")).alias("w")
    ).select("month", "ticker", "decile", "w")


def drift(w: dict[str, float], rets: dict[str, float]) -> dict[str, float]:
    """Weights after one holding period of returns, renormalised to 1.

    A name with no return is treated as flat (its weight neither grows nor
    shrinks); a name that was closed early has its partial return applied.
    """
    grown = {t: x * (1.0 + rets.get(t, 0.0)) for t, x in w.items()}
    total = sum(grown.values())
    return {t: x / total for t, x in grown.items()} if total > 0 else dict(w)


def turnover(w_new: dict[str, float], w_minus: dict[str, float]) -> float:
    """Half the sum of absolute weight changes (invariant 6)."""
    names = set(w_new) | set(w_minus)
    return 0.5 * sum(abs(w_new.get(t, 0.0) - w_minus.get(t, 0.0)) for t in names)


def portfolio_return(w: dict[str, float], rets: dict[str, float]) -> float:
    """Weighted return over the names with a return, weights renormalised.

    A name that cannot be priced forward is dropped from the return and
    the remaining weights scaled up. This is optimistic by construction and
    the count of such names is reported alongside.
    """
    have = {t: x for t, x in w.items() if t in rets}
    total = sum(have.values())
    if total <= 0:
        return 0.0
    return sum(x / total * rets[t] for t, x in have.items())


# --- the loop -----------------------------------------------------------


def backtest(
    signal_z: pl.DataFrame,
    returns: pl.DataFrame,
    cfg: Config,
    *,
    factor: str,
    signal: str = "",
    caps: pl.DataFrame | None = None,
    note: str = "",
    sector_neutral: bool = True,
    variant: str = "",
    log_path: Path | None = None,
) -> BacktestResult:
    """Run one specification and log it.

    signal_z: Frame[month, ticker, z]
    returns:  Frame[month, ticker, ret_fwd] (null where the name cannot be
              priced forward)
    """
    n = cfg.n_deciles
    z = signal_z.filter(pl.col("z").is_finite())
    # A month whose cross-section is thinner than min_names forms no
    # portfolio at all: the first months of a new data source can have a
    # handful of names, and a decile of them is one stock's return.
    z = z.filter(pl.len().over("month") >= cfg.min_names)
    dec = assign_deciles(z, n)
    target = weights(dec, caps, cfg.weighting)
    months = sorted(returns.select("month").unique().get_column("month").to_list())
    sig_months = set(target.get_column("month").unique().to_list())
    ret_by_month = {
        m: dict(zip(g["ticker"].to_list(), g["ret_fwd"].to_list(), strict=True))
        for (m,), g in returns.filter(pl.col("ret_fwd").is_not_null()).group_by("month")
    }
    tgt_by_month = {
        (m, d): dict(zip(g["ticker"].to_list(), g["w"].to_list(), strict=True))
        for (m, d), g in target.group_by("month", "decile")
    }
    cost = cfg.base_bps / 1e4
    k = cfg.holding_months

    held: dict[int, dict[str, float]] = {d: {} for d in range(1, n + 1)}
    dec_rows, ls_rows, w_rows = [], [], []
    since_rebalance = k  # rebalance on the first month with a signal
    for m in months:
        if m not in sig_months:
            continue
        rets = ret_by_month.get(m, {})
        rebalance = since_rebalance >= k
        row_ret, row_to, row_n = {}, {}, {}
        for d in range(1, n + 1):
            w_minus = held[d]
            if rebalance:
                w_new = tgt_by_month.get((m, d), {})
                to = turnover(w_new, w_minus)
            else:
                w_new, to = w_minus, 0.0
            r = portfolio_return(w_new, rets)
            dec_rows.append(
                {
                    "month": m,
                    "decile": d,
                    "ret_gross": r,
                    "ret_net": r - 2 * cost * to,
                    "turnover": to,
                    "n": len(w_new),
                    "n_unpriced": sum(1 for t in w_new if t not in rets),
                }
            )
            row_ret[d], row_to[d], row_n[d] = r, to, len(w_new)
            if rebalance:
                w_rows.extend(
                    {"month": m, "ticker": t, "decile": d, "w": x}
                    for t, x in w_new.items()
                )
            held[d] = drift(w_new, rets)
        to_ls = row_to[n] + row_to[1]
        gross = row_ret[n] - row_ret[1]
        ls_rows.append(
            {
                "month": m,
                "ret_gross": gross,
                "ret_net": gross - 2 * cost * to_ls,
                "turnover": to_ls,
                "n_long": row_n[n],
                "n_short": row_n[1],
            }
        )
        since_rebalance = 1 if rebalance else since_rebalance + 1

    deciles = pl.DataFrame(
        dec_rows,
        schema={
            "month": pl.Date,
            "decile": pl.Int32,
            "ret_gross": pl.Float64,
            "ret_net": pl.Float64,
            "turnover": pl.Float64,
            "n": pl.Int64,
            "n_unpriced": pl.Int64,
        },
    )
    long_short = pl.DataFrame(
        ls_rows,
        schema={
            "month": pl.Date,
            "ret_gross": pl.Float64,
            "ret_net": pl.Float64,
            "turnover": pl.Float64,
            "n_long": pl.Int64,
            "n_short": pl.Int64,
        },
    )
    wdf = pl.DataFrame(
        w_rows,
        schema={
            "month": pl.Date,
            "ticker": pl.Utf8,
            "decile": pl.Int32,
            "w": pl.Float64,
        },
    )
    result = BacktestResult(factor, deciles, long_short, wdf)
    log_specification(
        log_path or cfg.specifications,
        cfg,
        factor=factor,
        signal=signal or factor,
        sharpe_gross=_sharpe(long_short["ret_gross"]),
        sharpe_net=_sharpe(long_short["ret_net"]),
        note=note,
        sector_neutral=sector_neutral,
        variant=variant,
    )
    return result


def _sharpe(r: pl.Series) -> float:
    sd = r.std()
    if sd is None or sd == 0 or r.len() < 2:
        return float("nan")
    return float(r.mean() / sd * math.sqrt(12))


# --- beta hedge (FIX_PLAN F5) --------------------------------------------

HEDGE_WINDOW = 36
HEDGE_MIN_MONTHS = 24


def beta_hedge(
    long_short: pl.DataFrame,
    french: pl.DataFrame,
    window: int = HEDGE_WINDOW,
    min_months: int = HEDGE_MIN_MONTHS,
) -> pl.DataFrame:
    """The long-short series with its market beta hedged out.

    Row t of ``long_short`` is stamped with its formation month and earns
    its return over the following month, the month ``french`` stamps
    Mkt-RF with. The beta applied to row t is the OLS slope of the series
    on Mkt-RF over the ``window`` formation months strictly before t (at
    least ``min_months`` of them), so no month at or after t is used:
    ``hedged_t = ls_t - beta_{t-1} x mkt_rf_{t+1}``. Rows without a beta
    (the first ``min_months``) are dropped. Both ``ret_gross`` and
    ``ret_net`` are hedged; ``beta`` is kept on each row. Low volatility
    and low beta long-shorts carry a market beta near -0.65, and BAB is
    beta-neutral by construction, so the raw series is not the
    like-for-like comparison.
    """
    mkt = french.select(
        pl.col("month").dt.offset_by("-1mo").dt.month_end().alias("month"),
        pl.col("mkt_rf"),
    )
    df = (
        long_short.join(mkt, on="month", how="inner")
        .filter(pl.col("mkt_rf").is_not_null())
        .sort("month")
    )
    x, y = df["mkt_rf"].to_list(), df["ret_gross"].to_list()
    betas: list[float | None] = []
    for i in range(len(x)):
        lo = max(0, i - window)
        xs, ys = x[lo:i], y[lo:i]
        if len(xs) < min_months:
            betas.append(None)
            continue
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((a - mx) ** 2 for a in xs)
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
        betas.append(sxy / sxx if sxx > 0 else None)
    out = df.with_columns(pl.Series("beta", betas, dtype=pl.Float64)).filter(
        pl.col("beta").is_not_null()
    )
    return out.with_columns(
        (pl.col("ret_gross") - pl.col("beta") * pl.col("mkt_rf")).alias("ret_gross"),
        (pl.col("ret_net") - pl.col("beta") * pl.col("mkt_rf")).alias("ret_net"),
    ).drop("mkt_rf")
