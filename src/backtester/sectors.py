"""CIKs for every universe name, and SIC codes mapped by hand to 11
GICS-like buckets.

    cik_map(membership, constituents, num, sec_tickers, overrides)
        -> (Frame[ticker, cik, start, end], log)
    cik_at(ciks, months) -> Frame[month, ticker, cik]
    sic_to_sector(sic) -> str
    build(cfg, num, ciks) -> Frame[ticker, cik, start, end, sic, sector]

Current members carry a CIK on the Wikipedia constituents table. Removed
names do not, and the SEC has no historical ticker file, so they are
matched by company name against the names on their own filings in
sub.txt. Every match records how it was made; every miss is a row too.
Unmapped SICs go to "Other" and are counted, not dropped.

A ticker can have more than one registrant over time: Disney filed
under CIK 1001039 until its 2019 reorganisation and under 1744489
after; the ticker CB was Chubb Corp until ACE Ltd bought it in 2016
and took the name and the symbol. data/checks/cik_overrides.csv
(hand-written, FIX_PLAN F1b) carries one row per (ticker, CIK) era
with an EDGAR URL as evidence; ``cik_at`` resolves the CIK for each
month. An override's date range beats the base map inside the range;
outside it the base map applies; two override ranges for one ticker
never overlap (tests/test_cik_overrides.py).
"""

from __future__ import annotations

import re

import polars as pl

from backtester.config import Config

SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
]

# (low, high, sector), first match wins; specific ranges before broad ones.
_SIC_RANGES: list[tuple[int, int, str]] = [
    (1520, 1540, "Consumer Discretionary"),  # homebuilders
    (2830, 2836, "Health Care"),  # drugs, before chemicals
    (3021, 3021, "Consumer Discretionary"),  # rubber footwear (Nike)
    (3826, 3826, "Health Care"),  # lab analytical instruments (Thermo, Agilent)
    (4400, 4499, "Consumer Discretionary"),  # water transport: cruise lines here
    (4700, 4799, "Consumer Discretionary"),  # travel arrangement (Booking, Expedia)
    (4922, 4925, "Energy"),  # gas transmission: midstream
    (5013, 5013, "Consumer Discretionary"),  # auto parts wholesale
    (5122, 5122, "Health Care"),  # drug wholesale
    (5961, 5961, "Consumer Discretionary"),  # catalogue and mail order (Amazon)
    (8731, 8731, "Health Care"),  # commercial biological research
    (2840, 2844, "Consumer Staples"),  # soap, cosmetics, before chemicals
    (3570, 3579, "Information Technology"),  # computers, before machinery
    (3660, 3679, "Information Technology"),  # comms equipment, semis
    (3711, 3716, "Consumer Discretionary"),  # autos
    (3751, 3751, "Consumer Discretionary"),
    (3812, 3812, "Industrials"),  # navigation / defence
    (3821, 3829, "Information Technology"),  # instruments
    (3840, 3851, "Health Care"),  # medical instruments
    (5047, 5047, "Health Care"),  # medical wholesale
    (5140, 5149, "Consumer Staples"),  # grocery wholesale
    (5331, 5331, "Consumer Staples"),  # variety stores (Walmart)
    (5400, 5499, "Consumer Staples"),  # food stores
    (5912, 5912, "Consumer Staples"),  # drug stores
    (6324, 6324, "Health Care"),  # health insurers
    (6500, 6599, "Real Estate"),
    (6798, 6798, "Real Estate"),  # REITs
    (7310, 7319, "Communication Services"),  # advertising
    (7370, 7379, "Information Technology"),  # software, services
    (7810, 7841, "Communication Services"),  # films
    (2711, 2741, "Communication Services"),  # publishing
    (1300, 1399, "Energy"),
    (2900, 2999, "Energy"),
    (1000, 1499, "Materials"),
    (2600, 2699, "Materials"),
    (2800, 2899, "Materials"),
    (3000, 3099, "Materials"),  # rubber, plastics
    (3200, 3399, "Materials"),  # stone, glass, primary metals
    (1500, 1799, "Industrials"),
    (3400, 3599, "Industrials"),
    (3600, 3699, "Industrials"),  # electrical equipment (what is left)
    (3700, 3799, "Industrials"),  # aerospace, rail
    (3800, 3899, "Industrials"),  # instruments (what is left)
    (4000, 4799, "Industrials"),  # transport
    (5000, 5199, "Industrials"),  # wholesale (what is left)
    (7300, 7399, "Industrials"),  # business services (what is left)
    (8700, 8799, "Industrials"),  # engineering, accounting
    (2000, 2199, "Consumer Staples"),  # food, tobacco
    (2200, 2599, "Consumer Discretionary"),  # textiles, apparel, furniture
    (3900, 3999, "Consumer Discretionary"),  # toys, misc
    (5200, 5999, "Consumer Discretionary"),  # retail (what is left)
    (7000, 7299, "Consumer Discretionary"),  # hotels, personal services
    (7500, 7999, "Consumer Discretionary"),  # repair, amusement
    (8000, 8099, "Health Care"),
    (6000, 6799, "Financials"),
    (4800, 4899, "Communication Services"),
    (4900, 4999, "Utilities"),
    (100, 999, "Materials"),  # agriculture
]


def sic_to_sector(sic: int | None) -> str:
    if sic is None:
        return "Other"
    for lo, hi, s in _SIC_RANGES:
        if lo <= sic <= hi:
            return s
    return "Other"


# --- CIK matching -------------------------------------------------------

_SUFFIX = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|COMPANIES|LTD|LIMITED|PLC|"
    r"HOLDINGS?|HLDGS?|GROUP|GRP|THE|LLC|LP|L P|NV|N V|SA|S A|AG|CL A|CL B|CLASS A|"
    r"CLASS B|NEW|OLD|DE|TRUST|TR|INTERNATIONAL|INTL|ENTERPRISES?|INDUSTRIES|INDS?)\b"
)


def normalise_name(name: str | None) -> str:
    if not name:
        return ""
    s = name.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


OVERRIDE_SCHEMA = {
    "ticker": pl.Utf8,
    "cik": pl.Int64,
    "start": pl.Date,
    "end": pl.Date,
    "source_url": pl.Utf8,
    "note": pl.Utf8,
}


def load_overrides(cfg: Config) -> pl.DataFrame:
    """data/checks/cik_overrides.csv, or an empty frame if it is absent."""
    path = cfg.data / "checks" / "cik_overrides.csv"
    if not path.exists():
        return pl.DataFrame(schema=OVERRIDE_SCHEMA)
    return pl.read_csv(path, schema_overrides=OVERRIDE_SCHEMA).select(
        list(OVERRIDE_SCHEMA)
    )


def cik_map(
    membership: pl.DataFrame,
    constituents: pl.DataFrame,
    num: pl.DataFrame,
    sec_tickers: dict[str, int] | None = None,
    overrides: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Frame[ticker, cik, start, end] for every universe ticker that can be
    placed, and a log with one row per (ticker, cik): method, the SEC
    name matched, the range.

    Order of evidence: the SEC's own company_tickers.json for a ticker
    that is a member today, then the CIK Wikipedia's constituents table
    carries, then the hand-written overrides, then a name match against
    the filers. The SEC map is a snapshot of today's symbols, so it is
    never applied to a removed name: S is SentinelOne now and was Sprint
    then, DV is DoubleVerify now and was DeVry then. Each CIK must have
    filings; the log says which was used and, when the SEC and Wikipedia
    disagree, what Wikipedia had.

    A ticker with override rows keeps its SEC or constituents CIK for
    the months outside the override ranges and is never name-matched:
    the override is the hand-verified answer to the question the name
    match was asking. Start and end are null when unbounded.
    """
    filer_names = (
        num.select("cik", "name", "filed")
        .sort("filed", descending=True)
        .unique(subset=["cik", "name"], keep="first")
        .with_columns(
            pl.col("name")
            .map_elements(normalise_name, return_dtype=pl.Utf8)
            .alias("norm")
        )
    )
    by_norm: dict[str, set[int]] = {}
    for cik, norm in zip(filer_names["cik"], filer_names["norm"], strict=True):
        if norm:
            by_norm.setdefault(norm, set()).add(int(cik))
    by_squashed: dict[str, set[int]] = {}
    for norm, ciks in by_norm.items():
        by_squashed.setdefault(norm.replace(" ", ""), set()).update(ciks)
    by_prefix: dict[str, set[int]] = {}
    for norm, ciks in by_norm.items():
        key = " ".join(norm.split()[:2])
        by_prefix.setdefault(key, set()).update(ciks)

    direct = {
        r["ticker"]: int(r["cik"])
        for r in constituents.iter_rows(named=True)
        if r["cik"] and r["cik"].strip("0")
    }
    filers = set(int(c) for c in filer_names["cik"].unique())
    sec_tickers = sec_tickers or {}
    current = set(membership.filter(pl.col("end").is_null())["ticker"].to_list())
    over: dict[str, list[dict]] = {}
    if overrides is not None:
        for o in overrides.iter_rows(named=True):
            over.setdefault(o["ticker"], []).append(o)
    rows = []
    for r in membership.unique(subset=["ticker"]).iter_rows(named=True):
        t, sec_name = r["ticker"], r["security"]
        base = None
        if t in current and t in sec_tickers and sec_tickers[t] in filers:
            method = "sec company_tickers"
            if t in direct and direct[t] != sec_tickers[t]:
                method += f" (wikipedia had {direct[t]})"
            base = {"ticker": t, "cik": sec_tickers[t], "method": method}
        elif t in direct and direct[t] in filers:
            base = {"ticker": t, "cik": direct[t], "method": "constituents"}
        if base is not None:
            rows.append({**base, "matched": sec_name, "start": None, "end": None})
        if t in over:
            for o in over[t]:
                if base is not None and o["cik"] == base["cik"]:
                    continue  # the override agrees with the base map
                rows.append(
                    {
                        "ticker": t,
                        "cik": int(o["cik"]),
                        "method": "override",
                        "matched": o["note"],
                        "start": o["start"],
                        "end": o["end"],
                    }
                )
            continue
        if base is not None:
            continue
        # Wikipedia's CIK can be a brand-new entity with no filing history
        # (ExxonMobil's 2026 reorganisation): then the name has to place it.
        prefix = "constituents cik absent; " if t in direct else ""
        norm = normalise_name(sec_name)
        if norm in by_norm and len(by_norm[norm]) == 1:
            rows.append(
                {
                    "ticker": t,
                    "cik": next(iter(by_norm[norm])),
                    "method": prefix + "name exact",
                    "matched": norm,
                }
            )
            continue
        squashed = norm.replace(" ", "")
        if squashed in by_squashed and len(by_squashed[squashed]) == 1:
            rows.append(
                {
                    "ticker": t,
                    "cik": next(iter(by_squashed[squashed])),
                    "method": prefix + "name exact (spaces removed)",
                    "matched": squashed,
                }
            )
            continue
        key = " ".join(norm.split()[:2])
        if key and key in by_prefix and len(by_prefix[key]) == 1:
            rows.append(
                {
                    "ticker": t,
                    "cik": next(iter(by_prefix[key])),
                    "method": prefix + "name prefix",
                    "matched": key,
                }
            )
            continue
        rows.append(
            {"ticker": t, "cik": None, "method": prefix + "unmatched", "matched": norm}
        )
    log = pl.DataFrame(
        [{"start": None, "end": None, **r} for r in rows],
        schema={
            "ticker": pl.Utf8,
            "cik": pl.Int64,
            "method": pl.Utf8,
            "matched": pl.Utf8,
            "start": pl.Date,
            "end": pl.Date,
        },
    ).sort("method", "ticker", "start", nulls_last=False)
    return (
        log.filter(pl.col("cik").is_not_null()).select("ticker", "cik", "start", "end"),
        log,
    )


def cik_at(ciks: pl.DataFrame, months: list) -> pl.DataFrame:
    """Frame[month, ticker, cik]: the registrant of each ticker at each
    month-end. A row whose range covers the month wins over an unbounded
    one; a ticker with no row covering a month has no CIK there. Raises
    if two ranged rows cover the same month for one ticker."""
    if "start" not in ciks.columns:
        ciks = ciks.with_columns(
            pl.lit(None, dtype=pl.Date).alias("start"),
            pl.lit(None, dtype=pl.Date).alias("end"),
        )
    grid = pl.DataFrame({"month": months}, schema={"month": pl.Date}).join(
        ciks.select("ticker", "cik", "start", "end"), how="cross"
    )
    covered = grid.filter(
        (pl.col("start").is_null() | (pl.col("start") <= pl.col("month")))
        & (pl.col("end").is_null() | (pl.col("month") <= pl.col("end")))
    ).with_columns(
        (pl.col("start").is_not_null() | pl.col("end").is_not_null()).alias("ranged")
    )
    clash = (
        covered.filter(pl.col("ranged"))
        .group_by("month", "ticker")
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
    )
    if clash.height:
        r = clash.row(0, named=True)
        raise ValueError(f"{r['ticker']} has {r['n']} CIK ranges covering {r['month']}")
    return (
        covered.sort("ranged", descending=True)
        .unique(subset=["month", "ticker"], keep="first", maintain_order=True)
        .select("month", "ticker", "cik")
        .sort("month", "ticker")
    )


# --- build --------------------------------------------------------------


def build(cfg: Config, num: pl.DataFrame, ciks: pl.DataFrame) -> pl.DataFrame:
    """Frame[ticker, cik, start, end, sic, sector]: one row per (ticker,
    CIK) era, the SIC from that CIK's most recent filing, and the sector
    of the ticker's latest era on every row (a sector is a property of
    the ticker in the cross-section, so it is one value per ticker);
    writes sectors.parquet and the agreement with Wikipedia's GICS sector
    for current members to data/checks/sector_map_check.csv."""
    latest_sic = (
        num.select("cik", "sic", "filed")
        .filter(pl.col("sic").is_not_null())
        .sort("filed", descending=True)
        .unique(subset=["cik"], keep="first")
        .select("cik", "sic")
    )
    if "start" not in ciks.columns:
        ciks = ciks.with_columns(
            pl.lit(None, dtype=pl.Date).alias("start"),
            pl.lit(None, dtype=pl.Date).alias("end"),
        )
    out = ciks.join(latest_sic, on="cik", how="left")
    latest_era = (
        out.sort("end", descending=True, nulls_last=False)
        .unique(subset=["ticker"], keep="first", maintain_order=True)
        .select(
            "ticker",
            "sic",
            pl.col("sic")
            .map_elements(sic_to_sector, return_dtype=pl.Utf8)
            .alias("sector"),
        )
    )
    out = out.join(latest_era.drop("sic"), on="ticker", how="left").sort(
        "ticker", "start", nulls_last=False
    )
    interim = cfg.data / "interim"
    out.write_parquet(interim / "sectors.parquet")

    cons = pl.read_parquet(interim / "sp500_constituents.parquet").select(
        "ticker", pl.col("gics_sector").alias("gics")
    )
    check = latest_era.join(cons, on="ticker", how="inner").with_columns(
        (pl.col("sector") == pl.col("gics")).alias("agree")
    )
    summary = (
        check.group_by("gics")
        .agg(pl.len().alias("n"), pl.col("agree").sum().alias("agree"))
        .with_columns((100 * pl.col("agree") / pl.col("n")).round(1).alias("pct"))
        .sort("gics")
    )
    total = pl.DataFrame(
        {"gics": ["ALL"], "n": [check.height], "agree": [int(check["agree"].sum())]}
    ).with_columns((100 * pl.col("agree") / pl.col("n")).round(1).alias("pct"))
    pl.concat(
        [
            summary.with_columns(
                pl.col("n").cast(pl.Int64), pl.col("agree").cast(pl.Int64)
            ),
            total.with_columns(
                pl.col("n").cast(pl.Int64), pl.col("agree").cast(pl.Int64)
            ),
        ]
    ).write_csv(cfg.data / "checks" / "sector_map_check.csv")
    check.filter(~pl.col("agree")).select("ticker", "sic", "sector", "gics").sort(
        "gics", "ticker"
    ).write_csv(cfg.data / "checks" / "sector_map_disagreements.csv")
    return out
