"""FIX_PLAN_2 G5: why the RMW replica's correlation with French's big-cap
RMW leg falls to 0.38 over 2013-2015 when the other 3-year blocks are
0.6-0.8.

    uv run python scripts/rmw_trough.py

Month by month over 2013-01 to 2015-12 the replica's tercile membership
(pre-tax income over fiscal-year equity, cap-weighted terciles) is
compared with a naive operating-profitability sort, net income plus
interest expense plus tax over the same equity, where the two extra
tags exist. The 20 names with the largest rank disagreement are listed
with their sector and the concept that drives it. Then the replica is
re-run twice, with Financials excluded and with equity averaged over
the last two fiscal years, and each run's correlation with big-cap RMW
is printed by block. Both re-runs are logged to the specification log
as diagnostics (variant ``exfin`` / ``equity_avg2``); nothing under
data/processed or reports/ changes.

Writes data/checks/rmw_trough_disagreements.csv and
data/checks/rmw_trough_blocks.csv; the finding is written by hand to
decisions/g5_rmw_trough.md from what this prints.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import polars as pl

from backtester import config, fundamentals, portfolio, signals
from backtester.run import load_inputs, member_panel, raw_signal

ROOT = Path(__file__).resolve().parent.parent
TROUGH = (date(2013, 1, 31), date(2015, 12, 31))
EXTRA_TAGS = {
    "InterestExpense": "interest_expense",
    "IncomeTaxExpenseBenefit": "income_tax",
}
# 10-Ks for FY2011-FY2015 arrive in the 2012q1-2016q2 zips; that covers
# every annual value the trough months can see.
EXTRA_QUARTERS = [f"{y}q{q}" for y in range(2012, 2017) for q in range(1, 5)]
BLOCKS = [(2010, 2012), (2013, 2015), (2016, 2018), (2019, 2021), (2022, 2026)]
REUSED = ["HAR", "EP", "COL"]


def extra_num(cfg: config.Config) -> pl.DataFrame:
    """InterestExpense and IncomeTaxExpenseBenefit rows from the SEC zips,
    cached under data/interim (gitignored) because the read is minutes."""
    cache = cfg.data / "interim" / "rmw_trough_extra.parquet"
    if cache.exists():
        return pl.read_parquet(cache)
    frames = []
    for q in EXTRA_QUARTERS:
        zp = cfg.data / "raw" / "sec" / f"{q}.zip"
        if not zp.exists():
            continue
        print(f"  reading {q}", file=sys.stderr)
        df = fundamentals.ingest_quarter(zp, list(EXTRA_TAGS))
        frames.append(
            df.with_columns(
                pl.col("tag").replace_strict(EXTRA_TAGS, default=None).alias("concept")
            )
        )
    out = pl.concat(frames)
    out.write_parquet(cache)
    return out


def annual_asof(
    cfg: config.Config, ff: pl.DataFrame, panel: pl.DataFrame, concept: str
) -> pl.DataFrame:
    """One annual 10-K value per (month, cik), as-of filed, like a flow concept."""
    vals = ff.filter(
        (pl.col("concept") == concept)
        & (pl.col("qtrs") == 4)
        & pl.col("form").str.starts_with("10-K")
    )
    j = fundamentals.asof_join(panel, vals, cfg.asof_buffer_days)
    max_age = fundamentals.MAX_AGE_MONTHS["flow"]
    return j.with_columns(
        pl.when(pl.col("period_end") < pl.col("month").dt.offset_by(f"-{max_age}mo"))
        .then(None)
        .otherwise(pl.col("value"))
        .alias(concept)
    ).select("month", "cik", concept)


def month_earned_corr(
    ls: pl.DataFrame, french: pl.DataFrame, col: str, years: tuple[int, int] | None
) -> tuple[float, int]:
    """Correlation of the gross long-short with ``col``, the series shifted
    to the month earned (run.validate), restricted to ``years`` inclusive."""
    j = (
        ls.with_columns(
            pl.col("month").dt.offset_by("1mo").dt.month_end().alias("month_earned")
        )
        .join(french.select("month", col), left_on="month_earned", right_on="month")
        .filter(pl.col(col).is_not_null())
    )
    if years is not None:
        j = j.filter(pl.col("month_earned").dt.year().is_between(years[0], years[1]))
    if j.height < 3:
        return float("nan"), j.height
    return float(j.select(pl.corr("ret_gross", col)).item()), j.height


def blocks_row(name: str, ls: pl.DataFrame, french: pl.DataFrame) -> dict:
    row = {"series": name}
    c, n = month_earned_corr(ls, french, "big_rmw", None)
    row["all"] = round(c, 3)
    row["months"] = n
    for a, b in BLOCKS:
        c, _ = month_earned_corr(ls, french, "big_rmw", (a, b))
        row[f"{a}-{b}"] = round(c, 3)
    return row


def _member_std(monthly: pl.DataFrame, members: pl.DataFrame, ticker: str) -> float:
    x = monthly.join(members, on=["month", "ticker"]).filter(pl.col("ticker") == ticker)
    return float(x["ret_cal"].std())


def terciles(frame: pl.DataFrame, col: str) -> pl.DataFrame:
    """Percentile rank and tercile (1 low, 3 high) of ``col`` within month."""
    return frame.with_columns(
        (
            (pl.col(col).rank(method="average").over("month") - 0.5)
            / pl.len().over("month")
        ).alias(f"{col}_pct")
    ).with_columns(
        (pl.col(f"{col}_pct") * 3)
        .floor()
        .clip(0, 2)
        .cast(pl.Int32)
        .alias(f"{col}_terc")
        + 1
    )


def main() -> int:
    cfg = config.load(ROOT / "config.toml")
    c = cfg.with_(weighting="cw", n_deciles=3)
    inp = load_inputs(cfg)
    french = inp.french
    months = sorted(
        m
        for m in inp.monthly.get_column("month").unique().to_list()
        if cfg.start <= m <= cfg.end
    )
    members = member_panel(inp.membership, months)
    f = inp.fundamentals
    sectors = inp.sectors.select("ticker", "sector").unique(subset=["ticker"])
    checks = cfg.data / "checks"

    # --- 1. the replica as saved, and its correlation by block -------------
    base_ls = pl.read_parquet(cfg.data / "processed" / "long_short_rmw_replica.parquet")
    rows = [blocks_row("replica as reported", base_ls, french)]
    print("\n== correlation with big-cap RMW by block ==")
    print(rows[0])

    # --- 2. the naive sort and the disagreement list ------------------------
    print("\n== extra tags from the SEC zips ==", file=sys.stderr)
    xn = extra_num(cfg)
    ff = fundamentals.first_filed(xn)
    panel = f.select("month", "cik").unique()
    interest = annual_asof(cfg, ff, panel, "interest_expense")
    tax = annual_asof(cfg, ff, panel, "income_tax")
    g = (
        f.join(interest, on=["month", "cik"], how="left")
        .join(tax, on=["month", "cik"], how="left")
        .join(members, on=["month", "ticker"], how="inner")
        .join(sectors, on="ticker", how="left")
        .filter(pl.col("month").is_between(*TROUGH))
        .with_columns(pl.coalesce("equity_fy", "equity").alias("den"))
        .filter(pl.col("den") > 0)
        .with_columns(
            pl.coalesce("pretax_income", "operating_income").alias("rep_num"),
            pl.col("pretax_income").is_null().alias("used_operating_income"),
            (
                pl.col("net_income")
                + pl.col("income_tax")
                + pl.col("interest_expense").fill_null(0.0)
            ).alias("naive_num"),
            (
                pl.col("net_income_ttm")
                + pl.col("income_tax")
                + pl.col("interest_expense").fill_null(0.0)
            ).alias("naive_ttm_num"),
        )
        .with_columns(
            (pl.col("rep_num") / pl.col("den")).alias("rep"),
            (pl.col("naive_num") / pl.col("den")).alias("naive"),
            (pl.col("naive_ttm_num") / pl.col("den")).alias("naive_ttm"),
        )
    )
    both = g.filter(pl.col("rep").is_not_null() & pl.col("naive").is_not_null())
    print(
        f"\n== trough months: {g['month'].n_unique()} months, "
        f"{g.height} name-months with a replica value, {both.height} also with a "
        f"naive value (interest tag present for "
        f"{100 * both['interest_expense'].is_not_null().mean():.0f}%) =="
    )
    both = terciles(terciles(both, "rep"), "naive")
    both = both.with_columns(
        (pl.col("rep_pct") - pl.col("naive_pct")).abs().alias("gap"),
        (
            ((pl.col("rep_terc") == 3) & (pl.col("naive_terc") == 1))
            | ((pl.col("rep_terc") == 1) & (pl.col("naive_terc") == 3))
        ).alias("crossed"),
        (pl.col("rep_terc") == pl.col("naive_terc")).alias("same_terc"),
    )
    print(
        f"tercile agreement {100 * both['same_terc'].mean():.1f}% of name-months; "
        f"top-bottom crossings {both['crossed'].sum()}; "
        f"rank correlation replica vs naive "
        f"{both.select(pl.corr('rep_pct', 'naive_pct')).item():.3f}"
    )
    ttm_both = both.filter(pl.col("naive_ttm").is_not_null())
    ttm_both = terciles(ttm_both, "naive_ttm")
    print(
        "with net_income_ttm instead of the annual net income: tercile agreement "
        f"{100 * (ttm_both['rep_terc'] == ttm_both['naive_ttm_terc']).mean():.1f}%"
    )
    # per-name aggregation and what drives the gap
    per = (
        both.group_by("ticker", "sector")
        .agg(
            pl.len().alias("months"),
            pl.col("gap").mean().alias("mean_gap"),
            pl.col("crossed").sum().alias("crossings"),
            pl.col("rep").median().alias("replica_op"),
            pl.col("naive").median().alias("naive_op"),
            pl.col("used_operating_income").mean().alias("operating_income_fallback"),
            (
                (
                    pl.col("pretax_income")
                    / (pl.col("net_income") + pl.col("income_tax"))
                )
                .log()
                .abs()
                .median()
            ).alias("log_pretax_over_ni_plus_tax"),
            (
                pl.col("interest_expense").fill_null(0.0).abs()
                / (pl.col("net_income") + pl.col("income_tax")).abs()
            )
            .median()
            .alias("interest_over_ni_plus_tax"),
            (pl.col("equity_fy") / pl.col("equity"))
            .log()
            .abs()
            .median()
            .alias("log_equity_fy_over_equity"),
        )
        .filter(pl.col("months") >= 6)
        .sort("mean_gap", descending=True)
    )

    def driver(r: dict) -> str:
        if r["operating_income_fallback"] and r["operating_income_fallback"] > 0.5:
            return "pretax_income (missing; operating income used)"
        cands = {
            "pretax_income": r["log_pretax_over_ni_plus_tax"] or 0.0,
            "interest add-back": r["interest_over_ni_plus_tax"] or 0.0,
            "equity": r["log_equity_fy_over_equity"] or 0.0,
        }
        k = max(cands, key=cands.get)
        return k if cands[k] > 0.1 else "none of the three (rank gap under noise)"

    per = per.with_columns(
        pl.struct(per.columns)
        .map_elements(driver, return_dtype=pl.Utf8)
        .alias("driver")
    )
    top = per.head(20)
    print("\n== 20 names with the largest rank disagreement, 2013-2015 ==")
    with pl.Config(tbl_rows=25, tbl_cols=20, tbl_width_chars=200, fmt_str_lengths=45):
        print(
            top.select(
                "ticker",
                "sector",
                "months",
                pl.col("mean_gap").round(3),
                "crossings",
                pl.col("replica_op").round(3),
                pl.col("naive_op").round(3),
                pl.col("log_pretax_over_ni_plus_tax").round(2),
                pl.col("interest_over_ni_plus_tax").round(2),
                pl.col("log_equity_fy_over_equity").round(2),
                "driver",
            )
        )
    print("\ndriver counts over the 20:", top["driver"].value_counts().sort("count"))
    print("sector counts over the 20:", top["sector"].value_counts().sort("count"))
    per.write_csv(checks / "rmw_trough_disagreements.csv")

    # --- 3. cap-weight concentration in the trough (the shares question) ----
    z = pl.read_parquet(cfg.data / "processed" / "signals_z_rmw_replica.parquet")
    caps = inp.caps.select("month", "ticker", "cap")
    w = (
        portfolio.assign_deciles(z, 3)
        .join(caps, on=["month", "ticker"], how="inner")
        .filter(pl.col("month").is_between(*TROUGH))
        .with_columns(
            (pl.col("cap") / pl.col("cap").sum().over("month", "decile")).alias("w")
        )
    )
    conc = (
        w.group_by("month", "decile")
        .agg(
            pl.col("w").max().alias("max_w"), pl.col("w").top_k(5).sum().alias("top5_w")
        )
        .group_by("decile")
        .agg(pl.col("max_w").mean(), pl.col("top5_w").mean())
        .sort("decile")
    )
    print("\n== cap-weight concentration in the trough terciles (mean over months) ==")
    print(conc)
    heavy = (
        w.filter(pl.col("decile").is_in([1, 3]))
        .group_by("ticker", "decile")
        .agg(pl.col("w").mean().alias("mean_w"), pl.len().alias("months"))
        .sort("mean_w", descending=True)
        .head(10)
    )
    print(heavy)

    # --- 4. the replica without Financials -----------------------------------
    log = cfg.specifications
    returns = inp.monthly.select("month", "ticker", "ret_fwd").join(
        members, on=["month", "ticker"], how="inner"
    )
    raw = raw_signal("operating_profitability", inp, cfg).join(
        members, on=["month", "ticker"], how="inner"
    )
    nonfin = raw.join(sectors, on="ticker", how="left").filter(
        pl.col("sector") != "Financials"
    )
    res_exfin = portfolio.backtest(
        signals.normalise(nonfin.select("month", "ticker", "value"), None, cfg.winsor),
        returns,
        c,
        factor="rmw_replica",
        signal="operating_profitability",
        caps=inp.caps,
        note="diagnostic rmw trough ex-financials no-sector",
        sector_neutral=False,
        variant="exfin",
        log_path=log,
    )
    rows.append(
        blocks_row("replica, Financials excluded", res_exfin.long_short, french)
    )
    print("\n", rows[-1])

    # --- 5. equity averaged over the last two fiscal years -------------------
    lag = f.select(
        pl.col("month").dt.offset_by("12mo").dt.month_end().alias("month"),
        "ticker",
        pl.col("equity_fy").alias("equity_fy_prev"),
        pl.col("equity_fy_period_end").alias("equity_fy_prev_period_end"),
    )
    avg = (
        f.join(lag, on=["month", "ticker"], how="left")
        .with_columns(
            pl.when(
                pl.col("equity_fy_prev").is_not_null()
                & (pl.col("equity_fy_prev_period_end") < pl.col("equity_fy_period_end"))
            )
            .then((pl.col("equity_fy") + pl.col("equity_fy_prev")) / 2)
            .otherwise(pl.col("equity_fy"))
            .alias("equity_avg")
        )
        .with_columns(pl.coalesce("equity_avg", "equity").alias("den"))
        .filter(pl.col("den") > 0)
        .select(
            "month",
            "ticker",
            (pl.coalesce("pretax_income", "operating_income") / pl.col("den")).alias(
                "value"
            ),
        )
        .filter(pl.col("value").is_not_null())
        .join(members, on=["month", "ticker"], how="inner")
    )
    res_avg = portfolio.backtest(
        signals.normalise(avg, None, cfg.winsor),
        returns,
        c,
        factor="rmw_replica",
        signal="operating_profitability",
        caps=inp.caps,
        note="diagnostic rmw trough equity averaged over two fiscal years no-sector",
        sector_neutral=False,
        variant="equity_avg2",
        log_path=log,
    )
    rows.append(
        blocks_row("replica, equity = mean of last two FY", res_avg.long_short, french)
    )
    print("\n", rows[-1])

    # --- 6. the three reused tickers ----------------------------------------
    # Found by the cap-weight concentration above: HAR is 10-16% of the
    # short tercile in 2013 with a $0.4-2.3trn cap. Its yfinance series
    # (median close $5,620, from 2013-01) is not Harman International;
    # EP (median $1.68) is not El Paso and COL (median $0.135) is not
    # Rockwell Collins. All three left the index and the symbol was reused.
    reused = raw.filter(~pl.col("ticker").is_in(REUSED))
    res_reused = portfolio.backtest(
        signals.normalise(reused, None, cfg.winsor),
        returns,
        c,
        factor="rmw_replica",
        signal="operating_profitability",
        caps=inp.caps,
        note="diagnostic rmw trough without reused tickers HAR EP COL no-sector",
        sector_neutral=False,
        variant="ex_reused_tickers",
        log_path=log,
    )
    rows.append(
        blocks_row("replica without HAR, EP, COL", res_reused.long_short, french)
    )
    print(rows[-1])
    for t in REUSED:
        d = inp.daily_returns.filter(pl.col("ticker") == t)
        print(
            f"{t}: daily series {d['date'].min()} to {d['date'].max()}, "
            f"{d.height} days; monthly std while a member "
            f"{_member_std(inp.monthly, members, t):.2f}"
        )

    # --- 7. which months carry the trough -------------------------------------
    j = (
        base_ls.with_columns(
            pl.col("month").dt.offset_by("1mo").dt.month_end().alias("month_earned")
        )
        .join(
            french.select("month", "big_rmw"), left_on="month_earned", right_on="month"
        )
        .filter(pl.col("month_earned").is_between(date(2013, 1, 1), date(2015, 12, 31)))
        .with_columns((pl.col("ret_gross") - pl.col("big_rmw")).abs().alias("absdiff"))
        .sort("absdiff", descending=True)
    )
    print("\n== trough months with the largest replica-minus-RMW gap ==")
    print(
        j.select(
            "month",
            "month_earned",
            "ret_gross",
            "big_rmw",
            "absdiff",
            "n_long",
            "n_short",
        ).head(8)
    )
    corr_wo = j.sort("absdiff", descending=True).slice(3)
    print(
        "correlation over 2013-2015 without the three worst months:",
        round(float(corr_wo.select(pl.corr("ret_gross", "big_rmw")).item()), 3),
    )

    out = pl.DataFrame(rows)
    out.write_csv(checks / "rmw_trough_blocks.csv")
    print("\n== blocks ==")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
