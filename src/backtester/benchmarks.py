"""Ken French factors and the FRED one-month Treasury rate.

Produces ``data/interim/french_monthly.parquet`` with columns
month, mkt_rf, smb, hml, rmw, cma, umd, rf (all in decimal, monthly) and
``data/interim/fred_dgs1mo.parquet`` (date, rate_pct).

The validation bar is fixed in the README: each long-short series must
correlate above 0.7 with the matching French factor, or the pipeline is
wrong. French RF is the risk-free rate used for excess returns; DGS1MO is
fetched as well and kept for reference (the brief allows either).
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FIVE_FACTORS = "F-F_Research_Data_5_Factors_2x3_CSV.zip"
MOMENTUM = "F-F_Momentum_Factor_CSV.zip"
# The six size x B/M and size x profitability portfolios: their big-cap
# legs (BIG HiBM - BIG LoBM, BIG HiOP - BIG LoOP) are the like-for-like
# comparison for a large-cap universe, since HML and RMW are half small-cap.
SIX_BM = "6_Portfolios_2x3_CSV.zip"
SIX_OP = "6_Portfolios_ME_OP_2x3_CSV.zip"
FRED_DGS1MO = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS1MO"
# AQR's betting-against-beta factor, monthly, by country; the USA column
# is the benchmark for the beta factor (BUILD_PLAN 3.6 / 8.1). AQR
# reconstructs the whole history on each update, so pulls are date-stamped.
AQR_BAB = (
    "https://images.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/"
    "Betting-Against-Beta-Equity-Factors-Monthly.xlsx"
)

_MONTHLY_ROW = re.compile(r"^\s*(\d{6})\s*,")


def fetch(cfg: Config, as_of: date) -> list[Path]:
    root = cfg.data / "raw"
    return [
        raw.fetch_to_raw(
            root, f"french/{FIVE_FACTORS[:-4]}_{as_of}.zip", FRENCH_BASE + FIVE_FACTORS
        ),
        raw.fetch_to_raw(
            root, f"french/{MOMENTUM[:-4]}_{as_of}.zip", FRENCH_BASE + MOMENTUM
        ),
        raw.fetch_to_raw(root, f"fred/DGS1MO_{as_of}.csv", FRED_DGS1MO),
        raw.fetch_to_raw(
            root, f"french/{SIX_BM[:-4]}_{as_of}.zip", FRENCH_BASE + SIX_BM
        ),
        raw.fetch_to_raw(
            root, f"french/{SIX_OP[:-4]}_{as_of}.zip", FRENCH_BASE + SIX_OP
        ),
        raw.fetch_to_raw(root, f"aqr/bab_monthly_{as_of}.xlsx", AQR_BAB),
    ]


def parse_aqr_bab(path: Path, country: str = "USA") -> pl.DataFrame:
    """Frame[month, bab] from the 'BAB Factors' sheet: the DATE header row
    names the countries; values are already decimal monthly returns."""
    sheet = pl.read_excel(path, sheet_name="BAB Factors", has_header=False)
    first = sheet.get_column(sheet.columns[0])
    header_at = next(i for i, v in enumerate(first) if v == "DATE")
    names = [str(v) for v in sheet.row(header_at)]
    col = sheet.columns[names.index(country)]
    return (
        sheet.slice(header_at + 1)
        .select(
            pl.col(sheet.columns[0]).str.strptime(pl.Date, "%m/%d/%Y").alias("month"),
            pl.col(col).cast(pl.Float64, strict=False).alias("bab"),
        )
        .drop_nulls()
        .with_columns(pl.col("month").dt.month_end())
        .sort("month")
    )


def parse_french_monthly(text: str) -> pl.DataFrame:
    """The first (monthly) block of a French CSV: YYYYMM rows until a gap.

    Values are percent; returned as decimals. Column names are lower-cased
    with ``-`` replaced by ``_`` (``Mkt-RF`` -> ``mkt_rf``, ``Mom`` -> ``umd``).
    """
    lines = text.splitlines()
    header_idx = next(
        i
        for i, ln in enumerate(lines)
        if i + 1 < len(lines) and _MONTHLY_ROW.match(lines[i + 1])
    )
    header = [h.strip() for h in lines[header_idx].split(",")]
    header[0] = "yyyymm"
    rows = []
    for ln in lines[header_idx + 1 :]:
        if not _MONTHLY_ROW.match(ln):
            break
        rows.append([c.strip() for c in ln.split(",")])
    df = pl.DataFrame(rows, schema=header, orient="row")
    rename = {
        h: (
            "umd"
            if h.lower() == "mom"
            else h.lower().replace("-", "_").replace(" ", "_")
        )
        for h in header[1:]
    }
    return df.select(
        pl.col("yyyymm").str.strptime(pl.Date, "%Y%m").dt.month_end().alias("month"),
        *[(pl.col(h).cast(pl.Float64) / 100).alias(rename[h]) for h in header[1:]],
    )


def _read_zip_csv(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.read(name).decode("latin-1")


def parse_fred(text: str) -> pl.DataFrame:
    df = pl.read_csv(io.StringIO(text), null_values=["."])
    date_col, val_col = df.columns[0], df.columns[1]
    return df.select(
        pl.col(date_col).str.strptime(pl.Date, "%Y-%m-%d").alias("date"),
        pl.col(val_col).cast(pl.Float64).alias("rate_pct"),
    ).drop_nulls()


def build(cfg: Config) -> pl.DataFrame:
    root = cfg.data / "raw"
    five = parse_french_monthly(
        _read_zip_csv(raw.latest(root, f"french/{FIVE_FACTORS[:-4]}_*.zip"))
    )
    mom = parse_french_monthly(
        _read_zip_csv(raw.latest(root, f"french/{MOMENTUM[:-4]}_*.zip"))
    )
    french = five.join(mom.select("month", "umd"), on="month", how="left").sort("month")
    six_bm = parse_french_monthly(
        _read_zip_csv(raw.latest(root, f"french/{SIX_BM[:-4]}_*.zip"))
    )
    six_op = parse_french_monthly(
        _read_zip_csv(raw.latest(root, f"french/{SIX_OP[:-4]}_*.zip"))
    )
    french = french.join(
        six_bm.select(
            "month", (pl.col("big_hibm") - pl.col("big_lobm")).alias("big_hml")
        ),
        on="month",
        how="left",
    ).join(
        six_op.select(
            "month", (pl.col("big_hiop") - pl.col("big_loop")).alias("big_rmw")
        ),
        on="month",
        how="left",
    )
    as_of = french["month"].max()
    interim = cfg.data / "interim"
    french.with_columns(pl.lit(as_of).alias("as_of")).write_parquet(
        interim / "french_monthly.parquet"
    )
    fred = parse_fred(raw.latest(root, "fred/DGS1MO_*.csv").read_text(encoding="utf-8"))
    fred.with_columns(pl.lit(fred["date"].max()).alias("as_of")).write_parquet(
        interim / "fred_dgs1mo.parquet"
    )
    try:
        bab = parse_aqr_bab(raw.latest(root, "aqr/bab_monthly_*.xlsx"))
    except FileNotFoundError:
        print("no AQR BAB file fetched; the beta factor has no benchmark")
    else:
        bab.with_columns(pl.lit(bab["month"].max()).alias("as_of")).write_parquet(
            interim / "aqr_bab.parquet"
        )
    return french
