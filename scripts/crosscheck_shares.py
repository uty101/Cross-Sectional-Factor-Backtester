"""FIX_PLAN F2: the SEC share count against yfinance's, name by name.

    uv run python scripts/crosscheck_shares.py [--limit N]

For every ticker with a SEC count at its latest month in
market_cap.parquet, yfinance's current ``shares`` and ``marketCap``
(fast_info) are fetched and compared with the SEC count in the price
basis (split factor applied) and with price x shares. Writes
data/checks/shares_crosscheck.csv: ticker, sec_shares, yf_shares, ratio,
sec_source, sec_cap, yf_cap, cap_ratio, flag; ``flag`` is set when the
share ratio is outside [0.5, 2] or yfinance has no count.

The comparison is at the latest date only, where both counts are in
today's basis; it cannot see a historical split mismatch on its own,
which is why the split factor is applied to every month rather than
tuned here. A flagged name is a count in the wrong units or a
share-class filer whose cover page counts one class; the rows in
data/checks/shares_overrides.csv say what was done about each.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import polars as pl

from backtester import config, shares
from backtester.prices import to_yahoo


def yfinance_counts(tickers: list[str]) -> pl.DataFrame:
    import yfinance as yf

    rows = []
    for i, t in enumerate(tickers, 1):
        sh = cap = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fi = yf.Ticker(to_yahoo(t)).fast_info
                sh = fi["shares"]
                cap = fi["marketCap"]
        except Exception:  # noqa: BLE001 - a dead symbol raises many types
            pass
        rows.append(
            {
                "ticker": t,
                "yf_shares": float(sh) if sh else None,
                "yf_cap": float(cap) if cap else None,
            }
        )
        if i % 50 == 0:
            print(f"{i}/{len(tickers)}", flush=True)
    return pl.DataFrame(
        rows, schema={"ticker": pl.Utf8, "yf_shares": pl.Float64, "yf_cap": pl.Float64}
    )


def sec_latest(cfg: config.Config) -> pl.DataFrame:
    """Frame[ticker, sec_shares, sec_source, sec_cap] at each ticker's
    latest month with a cap, the count in the price basis."""
    caps = pl.read_parquet(cfg.data / "processed" / "market_cap.parquet")
    panel = pl.read_parquet(cfg.data / "processed" / "fundamentals_monthly.parquet")
    _, splits = shares.load(cfg)
    latest = caps.sort("month").group_by("ticker").agg(pl.all().last())
    sel = shares.resolve(panel, splits, shares.load_overrides(cfg)).join(
        latest.select("month", "ticker"), on=["month", "ticker"], how="inner"
    )
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    current = membership.filter(pl.col("end").is_null())["ticker"].unique()
    return (
        latest.select("ticker", "month", pl.col("cap").alias("sec_cap"))
        .join(sel, on=["month", "ticker"], how="inner")
        .filter(pl.col("ticker").is_in(current.implode()))
        .select(
            "ticker",
            pl.col("n_basis").alias("sec_shares"),
            pl.col("shares_source").alias("sec_source"),
            "sec_cap",
        )
        .sort("ticker")
    )


def main(argv: list[str]) -> int:
    cfg = config.load()
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    sec = sec_latest(cfg)
    if limit:
        sec = sec.head(limit)
    yf = yfinance_counts(sec["ticker"].to_list())
    out = shares.crosscheck(sec, yf).sort("flag", "ratio", descending=[True, True])
    out.write_csv(cfg.data / "checks" / "shares_crosscheck.csv")
    n_flag = int(out["flag"].sum())
    print(f"{out.height} names, {n_flag} flagged")
    print(out.filter(pl.col("flag")))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.exit(main(sys.argv[1:]))
