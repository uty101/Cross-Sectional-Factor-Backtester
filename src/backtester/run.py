"""One factor, end to end: signal -> z -> deciles -> long-short -> validation.

    run_factor(cfg, "momentum") -> RunResult

Every factor is a list of signals averaged into a composite z, a French
factor to validate against, and nothing else; adding one is a dict entry.
The cross-section at month t is restricted to index members on t
(invariant 3) before anything is ranked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from backtester import portfolio, signals, universe
from backtester.config import Config

FACTORS: dict[str, dict] = {
    "momentum": {"signals": ["momentum_12_1"], "french": "umd", "big": None},
    "value": {
        "signals": ["book_to_price", "earnings_yield"],
        "french": "hml",
        "big": "big_hml",
    },
    "quality": {
        "signals": ["gross_profitability", "accruals"],
        "french": "rmw",
        "big": "big_rmw",
    },
    "low_vol": {"signals": ["volatility_252"], "french": None},
    "asset_growth": {"signals": ["asset_growth"], "french": "cma"},
    "beta": {"signals": ["beta_252"], "french": None},
    # Year-on-year similarity of the 10-K text (Cohen, Malloy and Nguyen
    # 2020): long the names whose filing did not change. No French factor
    # to validate against; attribution on the five is the check.
    "text_change": {"signals": ["doc_similarity"], "french": None},
    # Replications of the French construction, used only to validate the
    # fundamentals join: one signal, no sector neutralisation, cap-weighted
    # terciles (see run.replicate).
    "hml_replica": {"signals": ["book_to_price"], "french": "hml", "big": "big_hml"},
    "rmw_replica": {
        "signals": ["operating_profitability"],
        "french": "rmw",
        "big": "big_rmw",
    },
    "composite": {
        "signals": [
            "momentum_12_1",
            "book_to_price",
            "earnings_yield",
            "gross_profitability",
            "accruals",
            "volatility_252",
        ],
        "french": None,
    },
}


@dataclass
class Inputs:
    cfg: Config
    membership: pl.DataFrame
    monthly: pl.DataFrame  # prices.monthly_returns output
    daily_returns: pl.DataFrame
    french: pl.DataFrame
    sectors: pl.DataFrame | None  # ticker, sector
    fundamentals: pl.DataFrame | None  # month, ticker, concept columns (phase 5)
    caps: pl.DataFrame | None  # month, ticker, cap
    text: pl.DataFrame | None = None  # text.build output: cik, period, filed, scores


@dataclass
class RunResult:
    factor: str
    z: pl.DataFrame
    result: portfolio.BacktestResult
    validation: dict


def load_inputs(cfg: Config) -> Inputs:
    interim, processed = cfg.data / "interim", cfg.data / "processed"
    monthly = pl.read_parquet(processed / "returns_monthly.parquet")
    sectors = (
        pl.read_parquet(interim / "sectors.parquet")
        if (interim / "sectors.parquet").exists()
        else None
    )
    fundamentals = (
        pl.read_parquet(processed / "fundamentals_monthly.parquet")
        if (processed / "fundamentals_monthly.parquet").exists()
        else None
    )
    caps = (
        pl.read_parquet(processed / "market_cap.parquet")
        if (processed / "market_cap.parquet").exists()
        else None
    )
    text = (
        pl.read_parquet(interim / "text_similarity.parquet")
        if (interim / "text_similarity.parquet").exists()
        else None
    )
    return Inputs(
        cfg,
        pl.read_parquet(interim / "membership.parquet"),
        monthly,
        pl.read_parquet(processed / "returns_daily.parquet"),
        pl.read_parquet(interim / "french_monthly.parquet"),
        sectors,
        fundamentals,
        caps,
        text,
    )


def member_panel(membership: pl.DataFrame, months: list[date]) -> pl.DataFrame:
    """Frame[month, ticker] of index members at each month-end."""
    rows = [
        {"month": m, "ticker": t}
        for m in months
        for t in universe.members_at(membership, m)
    ]
    return pl.DataFrame(rows, schema={"month": pl.Date, "ticker": pl.Utf8})


def raw_signal(name: str, inp: Inputs) -> pl.DataFrame:
    """Frame[month, ticker, value] for one named signal."""
    cfg = inp.cfg
    month_ends = inp.monthly.select("month", "t").unique().sort("month")
    if name == "momentum_12_1":
        back, skip = cfg.momentum_window
        return signals.momentum_12_1(inp.monthly, back, skip)
    if name == "volatility_252":
        return signals.volatility(
            inp.daily_returns.filter(pl.col("ticker") != "^GSPC"),
            month_ends,
            cfg.vol_window,
        )
    if name == "beta_252":
        mkt = inp.daily_returns.filter(pl.col("ticker") == "^GSPC").select(
            "date", "ret"
        )
        return signals.beta(
            inp.daily_returns.filter(pl.col("ticker") != "^GSPC"),
            mkt,
            month_ends,
            cfg.beta_window,
        )
    if name == "doc_similarity":
        if inp.text is None or inp.sectors is None:
            raise RuntimeError("doc_similarity needs `build --step text` and sectors")
        from backtester import text

        months = sorted(month_ends.get_column("month").to_list())
        return text.signal(cfg, inp.text, inp.sectors, months)
    if inp.fundamentals is None:
        raise RuntimeError(f"{name} needs fundamentals (phase 5) which are not built")
    from backtester import fundamentals as fx

    return fx.signal(name, inp.fundamentals, inp.monthly, inp.caps)


def run_factor(
    cfg: Config,
    factor: str,
    inp: Inputs | None = None,
    *,
    note: str = "",
    sector_neutral: bool = True,
) -> RunResult:
    inp = inp or load_inputs(cfg)
    spec = FACTORS[factor]
    months = sorted(
        m
        for m in inp.monthly.get_column("month").unique().to_list()
        if cfg.start <= m <= cfg.end
    )
    members = member_panel(inp.membership, months)
    sectors = inp.sectors if sector_neutral else None

    zs = []
    for name in spec["signals"]:
        raw = raw_signal(name, inp).join(members, on=["month", "ticker"], how="inner")
        zs.append(signals.normalise(raw, sectors, cfg.winsor))
    z = zs[0] if len(zs) == 1 else signals.composite(zs)

    returns = inp.monthly.select("month", "ticker", "ret_fwd").join(
        members, on=["month", "ticker"], how="inner"
    )
    caps = inp.caps if cfg.weighting == "cw" else None
    result = portfolio.backtest(
        z,
        returns,
        cfg,
        factor=factor,
        signal="+".join(spec["signals"]),
        caps=caps,
        note=(note + ("" if sector_neutral else " no-sector")).strip(),
    )
    validation = validate(result.long_short, inp.french, spec["french"])
    big = spec.get("big")
    if big and big in inp.french.columns:
        validation["big"] = validate(result.long_short, inp.french, big)
    return RunResult(factor, z, result, validation)


def validate(
    long_short: pl.DataFrame, french: pl.DataFrame, factor_col: str | None
) -> dict:
    """Correlation of the gross long-short series with the French factor.

    A long-short row is stamped with its formation month and earns its
    return over the following month, which is the month the French factor
    is stamped with. So row t is compared with the factor at t + 1.
    """
    if factor_col is None:
        return {"french": None, "corr": None, "months": 0}
    earned = long_short.with_columns(
        pl.col("month").dt.offset_by("1mo").dt.month_end().alias("month_earned")
    )
    j = earned.join(
        french.select("month", factor_col),
        left_on="month_earned",
        right_on="month",
        how="inner",
    )
    j = j.filter(pl.col(factor_col).is_not_null())
    corr = j.select(pl.corr("ret_gross", factor_col)).item() if j.height > 2 else None
    return {"french": factor_col, "corr": corr, "months": j.height}


def save(res: RunResult, cfg: Config, tag: str = "") -> None:
    processed = cfg.data / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    suffix = f"{res.factor}{('_' + tag) if tag else ''}"
    res.z.write_parquet(processed / f"signals_z_{suffix}.parquet")
    res.result.deciles.write_parquet(processed / f"deciles_{suffix}.parquet")
    res.result.long_short.write_parquet(processed / f"long_short_{suffix}.parquet")
    res.result.weights.write_parquet(processed / f"weights_{suffix}.parquet")


def summary_line(res: RunResult) -> str:
    ls = res.result.long_short
    v = res.validation
    corr = "n/a" if v["corr"] is None else f"{v['corr']:.3f} vs {v['french'].upper()}"
    if "big" in v and v["big"]["corr"] is not None:
        corr += f", {v['big']['corr']:.3f} vs big-cap leg"
    sg, sn = portfolio._sharpe(ls["ret_gross"]), portfolio._sharpe(ls["ret_net"])
    return (
        f"{res.factor}: {ls.height} months, gross Sharpe {sg:.2f}, net {sn:.2f}, "
        f"mean turnover {ls['turnover'].mean():.2f}, corr {corr} ({v['months']} months)"
    )


# --- the loops ----------------------------------------------------------

REPORTED = ["momentum", "value", "quality", "low_vol", "composite", "text_change"]


def run_all(
    cfg: Config, factors: list[str] = REPORTED, note: str = "base"
) -> dict[str, RunResult]:
    """The base specification of every reported factor, saved under its name."""
    inp = load_inputs(cfg)
    out = {}
    for f in factors:
        res = run_factor(cfg, f, inp, note=note)
        save(res, cfg)
        out[f] = res
        print(summary_line(res))
    return out


def sensitivities(cfg: Config, factors: list[str] = REPORTED) -> dict[str, RunResult]:
    """Weighting and holding-period variants, each one logged and saved with
    a tag. Cost is not looped: net returns at any cost follow from gross
    returns and turnover, and stats.sharpe_by_cost does that analytically.
    """
    inp = load_inputs(cfg)
    out = {}
    variants = [
        ("cw", cfg.with_(weighting="cw")),
        ("hold3", cfg.with_(holding_months=3)),
        ("hold6", cfg.with_(holding_months=6)),
        ("hold12", cfg.with_(holding_months=12)),
        ("nosector", cfg),
    ]
    for tag, c in variants:
        for f in factors:
            if tag == "cw" and inp.caps is None:
                continue
            res = run_factor(
                c, f, inp, note=f"sensitivity {tag}", sector_neutral=(tag != "nosector")
            )
            save(res, c, tag=tag)
            out[f"{f}_{tag}"] = res
            print(tag, summary_line(res))
    return out


def replicate(cfg: Config, inp: Inputs | None = None) -> dict[str, RunResult]:
    """Validate the fundamentals join by building the French factors the
    way French does, as nearly as this universe allows: one raw signal, no
    sector neutralisation, cap-weighted, top third minus bottom third."""
    inp = inp or load_inputs(cfg)
    c = cfg.with_(weighting="cw", n_deciles=3)
    out = {}
    for f in ("hml_replica", "rmw_replica"):
        res = run_factor(c, f, inp, note="French replication", sector_neutral=False)
        save(res, c)
        out[f] = res
        print(summary_line(res))
    return out
