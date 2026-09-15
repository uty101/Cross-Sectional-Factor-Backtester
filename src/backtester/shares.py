"""Shares outstanding in the basis the price series uses (FIX_PLAN F2).

    fetch_cover      dei:EntityCommonStockSharesOutstanding per universe CIK
                     from the SEC companyconcept API (the 10-K/10-Q cover
                     page count), never overwritten
    fetch_splits     stock split events per ticker from yfinance
    build            both -> data/interim/cover_shares.parquet, splits.parquet
    resolve          cover count, then balance-sheet count, then the diluted
                     weighted average, each in the price basis, with a
                     plausibility guard; the source is recorded per row
    split_factor     the product of split ratios after a filing date, so a
                     count reported in 2015 meets a 2024-split-adjusted price
    crosscheck       SEC count against yfinance's current count and cap

Why a separate source for the cover count: the Financial Statement Data
Sets carry the us-gaap facts and almost none of the dei cover items
(10 of 6,877 filings in 2015q3 have EntityCommonStockSharesOutstanding
in num.txt), so the tag-map route in FIX_PLAN F2 returns nothing. The
companyconcept API returns every non-dimensional fact for the concept
with its accession number and filing date, so the first-filed and as-of
rules apply unchanged. Filers that report the count per share class
(Alphabet, Berkshire) have only dimensional facts there and fall back to
the balance-sheet count or the weighted average.

Why splits: yfinance's Close is split-adjusted (only dividends are left
in), so a 2015 price is in 2026 share-basis while a 2015 filing counts
2015 shares. Chipotle's 50-for-1 split of 2024 made every pre-2024 cap
50 times too small, which is what the old 1bn floor was catching. A
count is scaled by every split after its filing date (a filing made
after a split already reports post-split numbers, ASC 260) and before
the price series' own as-of date.
"""

from __future__ import annotations

import io
import json
import time
from datetime import date
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config

COMPANYCONCEPT = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}"
    "/dei/EntityCommonStockSharesOutstanding.json"
)
# The same API for the us-gaap counts, because the FSDS num.txt is
# missing them for a few large filers (General Dynamics has 664 USD rows
# in 2020q3 and not one share count) and the cover count can stop early.
FALLBACK_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
)
FALLBACK_TAGS = {
    "shares": "CommonStockSharesOutstanding",
    "shares_wavg": "WeightedAverageNumberOfDilutedSharesOutstanding",
}
SEC_USER_AGENT = "Utkarsh Malhotra factor-research utkarsh.malhotra@yahoo.co.uk"
SEC_RATE = 0.11  # seconds between requests: the SEC allows 10 per second
COVER_SCHEMA = {
    "cik": pl.Int64,
    "adsh": pl.Utf8,
    "ddate": pl.Date,
    "filed": pl.Date,
    "form": pl.Utf8,
    "value": pl.Float64,
}
SPLIT_SCHEMA = {"ticker": pl.Utf8, "date": pl.Date, "ratio": pl.Float64}
SOURCES = ("cover", "balance_sheet", "weighted_average")
RATIO_BAND = (0.5, 2.0)


# --- fetch --------------------------------------------------------------


def _universe_ciks(cfg: Config, rebuild_map: bool = False) -> list[int]:
    """Every CIK in the map. ``rebuild_map`` regenerates sectors.parquet
    from the num cache and the overrides first, so a build never reads a
    map older than the one the panel will use."""
    from backtester import fundamentals

    if rebuild_map or not (cfg.data / "interim" / "sectors.parquet").exists():
        fundamentals.build_map(cfg, fundamentals.load_num(cfg))
    sectors = pl.read_parquet(cfg.data / "interim" / "sectors.parquet")
    return sorted(set(int(c) for c in sectors["cik"].to_list()))


def fetch_cover(cfg: Config, as_of: date, ciks: list[int] | None = None) -> list[Path]:
    """One JSON per universe CIK under data/raw/sec/companyconcept/. A 404
    (no non-dimensional fact for the concept) is stored as the SEC's own
    body so the fetch is resumable and the manifest records the answer."""
    import requests

    root = cfg.data / "raw"
    stamp = as_of.isoformat()
    session = requests.Session()
    stored = []
    for cik in ciks if ciks is not None else _universe_ciks(cfg):
        rel = (
            f"sec/companyconcept/{cik}_EntityCommonStockSharesOutstanding_{stamp}.json"
        )
        if (root / rel).exists():
            stored.append(root / rel)
            continue
        url = COMPANYCONCEPT.format(cik=cik)
        r = session.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=60)
        if r.status_code not in (200, 404):
            r.raise_for_status()
        stored.append(raw.store_raw(root, rel, r.content, url))
        time.sleep(SEC_RATE)
    return stored


def fetch_fallback(cfg: Config, as_of: date) -> list[Path]:
    """The two us-gaap share counts for every universe CIK, from the same
    API. A cover file can hold facts for a few early years only (Comcast
    reported a total to 2012 and per class after), so every CIK is
    fetched, not just the ones with an empty cover file."""
    import requests

    root = cfg.data / "raw"
    stamp = as_of.isoformat()
    session = requests.Session()
    stored = []
    for cik in _universe_ciks(cfg):
        for tag in FALLBACK_TAGS.values():
            rel = f"sec/companyconcept/{cik}_{tag}_{stamp}.json"
            if (root / rel).exists():
                stored.append(root / rel)
                continue
            url = FALLBACK_URL.format(cik=cik, tag=tag)
            r = session.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=60)
            if r.status_code not in (200, 404):
                r.raise_for_status()
            stored.append(raw.store_raw(root, rel, r.content, url))
            time.sleep(SEC_RATE)
    return stored


API_SCHEMA = {**COVER_SCHEMA, "concept": pl.Utf8, "qtrs": pl.Int32}


def parse_fallback(text: str, cik: int, concept: str) -> pl.DataFrame:
    """API_SCHEMA rows for a us-gaap share concept: an instant fact has
    qtrs 0, a duration fact the number of quarters between start and end."""
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        return pl.DataFrame(schema=API_SCHEMA)
    rows = []
    for f in (j.get("units") or {}).get("shares") or []:
        if not f.get("val") or float(f["val"]) <= 0:
            continue
        end = date.fromisoformat(f["end"])
        qtrs = 0
        if f.get("start"):
            start = date.fromisoformat(f["start"])
            months = (end.year - start.year) * 12 + end.month - start.month + 1
            qtrs = max(1, round(months / 3))
        rows.append(
            {
                "cik": cik,
                "adsh": f["accn"],
                "ddate": end,
                "filed": date.fromisoformat(f["filed"]),
                "form": f["form"],
                "value": float(f["val"]),
                "concept": concept,
                "qtrs": qtrs,
            }
        )
    return pl.DataFrame(rows, schema=API_SCHEMA)


def parse_cover(text: str, cik: int) -> pl.DataFrame:
    """COVER_SCHEMA rows from one companyconcept response; a 404 body or a
    zero count yields nothing."""
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        return pl.DataFrame(schema=COVER_SCHEMA)
    facts = (j.get("units") or {}).get("shares") or []
    rows = [
        {
            "cik": cik,
            "adsh": f["accn"],
            "ddate": date.fromisoformat(f["end"]),
            "filed": date.fromisoformat(f["filed"]),
            "form": f["form"],
            "value": float(f["val"]),
        }
        for f in facts
        if f.get("val") and float(f["val"]) > 0
    ]
    return pl.DataFrame(rows, schema=COVER_SCHEMA)


def fetch_splits(
    cfg: Config, as_of: date, tickers: list[str] | None = None
) -> list[Path]:
    """Split events per universe ticker from yfinance, one CSV each under
    data/raw/prices/yfinance_splits/ (an empty CSV means yfinance lists
    none, and is stored so the fetch is resumable)."""
    import yfinance as yf

    from backtester.prices import _raw_name, to_yahoo

    if tickers is None:
        membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
        tickers = sorted(set(membership["ticker"].to_list()))
    root = cfg.data / "raw"
    stamp = as_of.isoformat()
    stored = []
    for t in tickers:
        rel = f"prices/yfinance_splits/{_raw_name(t)}_{stamp}.csv"
        if (root / rel).exists():
            stored.append(root / rel)
            continue
        y = to_yahoo(t)
        try:
            s = yf.Ticker(y).splits
        except Exception:  # noqa: BLE001 - yfinance raises many types on a dead symbol
            s = None
        lines = ["date,ratio"]
        if s is not None and len(s):
            for ts, ratio in s.items():
                lines.append(f"{ts.date().isoformat()},{float(ratio)}")
        stored.append(
            raw.store_raw(
                root, rel, ("\n".join(lines) + "\n").encode(), f"yfinance-splits:{y}"
            )
        )
    return stored


# --- build --------------------------------------------------------------


def build(cfg: Config) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Latest raw file per CIK and per ticker -> the two interim tables."""
    root = cfg.data / "raw"
    frames = []
    ciks = _universe_ciks(cfg, rebuild_map=True)
    for cik in ciks:
        try:
            p = raw.latest(
                root,
                f"sec/companyconcept/{cik}_EntityCommonStockSharesOutstanding_*.json",
            )
        except FileNotFoundError:
            continue
        frames.append(parse_cover(p.read_text(encoding="utf-8"), cik))
    cover = (pl.concat(frames) if frames else pl.DataFrame(schema=COVER_SCHEMA)).sort(
        "cik", "filed", "ddate"
    )
    fallback = []
    for cik in ciks:
        for concept, tag in FALLBACK_TAGS.items():
            try:
                p = raw.latest(root, f"sec/companyconcept/{cik}_{tag}_*.json")
            except FileNotFoundError:
                continue
            fallback.append(parse_fallback(p.read_text(encoding="utf-8"), cik, concept))
    api = (pl.concat(fallback) if fallback else pl.DataFrame(schema=API_SCHEMA)).sort(
        "cik", "concept", "filed", "ddate"
    )

    from backtester.prices import _raw_name

    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    daily_as_of = pl.read_parquet(
        cfg.data / "interim" / "prices_daily.parquet", columns=["as_of"]
    )["as_of"].max()
    rows = []
    for t in sorted(set(membership["ticker"].to_list())):
        try:
            p = raw.latest(root, f"prices/yfinance_splits/{_raw_name(t)}_*.csv")
        except FileNotFoundError:
            continue
        df = pl.read_csv(
            io.StringIO(p.read_text()), schema={"date": pl.Date, "ratio": pl.Float64}
        )
        rows.append(
            df.with_columns(pl.lit(t).alias("ticker")).select(list(SPLIT_SCHEMA))
        )
    splits = (pl.concat(rows) if rows else pl.DataFrame(schema=SPLIT_SCHEMA)).filter(
        (pl.col("ratio") > 0) & (pl.col("date") <= daily_as_of)
    )
    # A split after the price series was fetched is not in its adjustment.
    interim = cfg.data / "interim"
    stamp = pl.lit(date.today().isoformat()).alias("as_of")
    cover.with_columns(stamp).write_parquet(interim / "cover_shares.parquet")
    api.with_columns(stamp).write_parquet(interim / "api_shares.parquet")
    splits.sort("ticker", "date").with_columns(stamp).write_parquet(
        interim / "splits.parquet"
    )
    return cover, splits


def load(cfg: Config) -> tuple[pl.DataFrame | None, pl.DataFrame | None]:
    interim = cfg.data / "interim"
    c, s = interim / "cover_shares.parquet", interim / "splits.parquet"
    return (
        pl.read_parquet(c).drop("as_of") if c.exists() else None,
        pl.read_parquet(s).drop("as_of") if s.exists() else None,
    )


def load_api(cfg: Config) -> pl.DataFrame | None:
    """The us-gaap fallback counts as rows in the num cache's shape, so
    fundamentals.monthly_panel can treat them as filings of the ``shares``
    and ``shares_wavg`` concepts for the CIKs the FSDS left out."""
    p = cfg.data / "interim" / "api_shares.parquet"
    if not p.exists():
        return None
    api = pl.read_parquet(p).drop("as_of")
    if not api.height:
        return None
    return api.select(
        "adsh",
        "cik",
        "concept",
        pl.lit("companyconcept").alias("tag"),
        "ddate",
        "qtrs",
        "value",
        "filed",
        "form",
        pl.col("ddate").dt.year().cast(pl.Int32).alias("fy"),
        pl.lit("").alias("fp"),
        pl.lit(None, dtype=pl.Int32).alias("sic"),
        pl.lit("").alias("name"),
    )


# --- the count used ----------------------------------------------------


def split_factor(
    keys: pl.DataFrame, splits: pl.DataFrame | None, basis_col: str = "shares_filed"
) -> pl.DataFrame:
    """``keys`` plus ``split_factor``: the product of split ratios for the
    ticker dated after ``basis_col`` (1.0 when none, or when splits is
    None). Multiplying a count by it puts the count in the basis of a
    split-adjusted price series."""
    if splits is None or splits.height == 0:
        return keys.with_columns(pl.lit(1.0).alias("split_factor"))
    j = (
        keys.select("ticker", basis_col)
        .unique()
        .join(splits.select("ticker", "date", "ratio"), on="ticker", how="inner")
        .filter(pl.col("date") > pl.col(basis_col))
        .group_by("ticker", basis_col)
        .agg(pl.col("ratio").product().alias("split_factor"))
    )
    return keys.join(j, on=["ticker", basis_col], how="left").with_columns(
        pl.col("split_factor").fill_null(1.0)
    )


# --- a count out of line with its neighbours ----------------------------

JUMP = 5.0
JUMP_WINDOW = 61  # months, centred: five years
# A count whose implied cap is outside this range does not anchor the
# reference: EchoStar reports its weighted average in thousands in every
# 10-Q and in units in every 10-K, so the wrong values are the majority
# of a window, and AEP's count is a million times too large for nine
# months of one year. No index member is worth 200m or 20 trillion.
CAP_PRIOR = (2e8, 2e13)
AGREE = 1.25  # two sources within 25% of each other confirm the level
UNITS = 50.0  # beyond this the disagreement is a units error, whatever agrees
MIN_SHARES = 1e5  # fewer is a shell or a placeholder, never an index member


def resolve(
    panel: pl.DataFrame,
    splits: pl.DataFrame | None = None,
    overrides: pl.DataFrame | None = None,
    prices: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Frame[month, ticker, n_shares, shares_source, shares_filed,
    split_factor, n_basis, implausible] from a monthly panel carrying
    shares_cover, shares, shares_wavg and their ``_filed`` dates.
    Priority: cover, balance sheet, weighted average. ``overrides``
    (data/checks/shares_overrides.csv: ticker, source, reason) pins a
    ticker to one source or marks it ``unresolved`` (dropped).

    Every source is first put in the price basis (its own split factor,
    by its own filing date). The ticker's reference count at each month
    is the rolling median over JUMP_WINDOW months of the per-month
    median across sources, computed from the values that pass a loose
    prior when ``prices`` (month, ticker, px_me_raw) is given: an index
    member's cap lies between CAP_PRIOR[0] and CAP_PRIOR[1], so a count
    that puts it at 30m or at 10 quadrillion is a units error and must
    not anchor the reference. The highest-priority source within a
    factor of JUMP of the reference is used; when none is, the month is
    ``implausible`` and carries no count. Garmin's XBRL reports both the balance-sheet
    and the weighted-average count in thousands in some filings and in
    units in others (191,815 against 192,239,000 in FY2015): the guard
    takes whichever is in units that month and drops the months where
    neither is. A real count never moves fivefold in a month once splits
    are normalised.
    """
    cols = {
        "cover": "shares_cover",
        "balance_sheet": "shares",
        "weighted_average": "shares_wavg",
    }
    forced: dict[str, str] = {}
    if overrides is not None and overrides.height:
        forced = dict(zip(overrides["ticker"], overrides["source"], strict=True))
    unresolved = [t for t, s in forced.items() if s == "unresolved"]
    longs = []
    for rank, src in enumerate(SOURCES):
        c = cols[src]
        if c not in panel.columns:
            continue
        f = f"{c}_filed" if f"{c}_filed" in panel.columns else None
        part = panel.select(
            "month",
            "ticker",
            pl.lit(src).alias("shares_source"),
            pl.lit(rank).alias("rank"),
            pl.col(c).alias("n_shares"),
            (pl.col(f) if f else pl.lit(None, dtype=pl.Date)).alias("shares_filed"),
        ).filter(pl.col("n_shares").is_not_null() & (pl.col("n_shares") > 0))
        longs.append(part)
    long = (
        pl.concat(longs)
        if longs
        else pl.DataFrame(
            schema={
                "month": pl.Date,
                "ticker": pl.Utf8,
                "shares_source": pl.Utf8,
                "rank": pl.Int32,
                "n_shares": pl.Float64,
                "shares_filed": pl.Date,
            }
        )
    )
    if unresolved:
        long = long.filter(~pl.col("ticker").is_in(unresolved))
    if forced:
        pinned = {t: s for t, s in forced.items() if s != "unresolved"}
        if pinned:
            long = long.filter(
                pl.col("ticker")
                .replace_strict(pinned, default=None, return_dtype=pl.Utf8)
                .is_null()
                | (
                    pl.col("shares_source")
                    == pl.col("ticker").replace_strict(
                        pinned, default=None, return_dtype=pl.Utf8
                    )
                )
            )
    long = split_factor(long, splits).with_columns(
        (pl.col("n_shares") * pl.col("split_factor")).alias("n_basis")
    )
    if prices is not None:
        long = long.join(
            prices.select("month", "ticker", "px_me_raw"),
            on=["month", "ticker"],
            how="left",
        ).with_columns(
            (
                pl.col("px_me_raw").is_null()
                | (
                    (pl.col("n_basis") * pl.col("px_me_raw")).is_between(
                        CAP_PRIOR[0], CAP_PRIOR[1]
                    )
                )
            ).alias("prior_ok")
        )
    else:
        long = long.with_columns(pl.lit(True).alias("prior_ok"))
    # The reference is rolled over calendar months, not over the rows a
    # ticker happens to have: a symbol that was two companies six years
    # apart (Q: Qwest to 2011, Quintiles in 2017) must not judge the
    # second by the first.
    grid = panel.select("month", "ticker").unique().sort("ticker", "month")
    per_month = (
        grid.join(
            long.filter(pl.col("prior_ok"))
            .group_by("month", "ticker")
            .agg(pl.col("n_basis").median().alias("n_mid")),
            on=["month", "ticker"],
            how="left",
        )
        .sort("ticker", "month")
        .with_columns(
            pl.col("n_mid")
            .rolling_median(JUMP_WINDOW, center=True, min_samples=1)
            .over("ticker")
            .alias("reference")
        )
    )
    long = long.join(
        per_month.select("month", "ticker", "reference"), on=["month", "ticker"]
    )
    # A count is plausible when it sits within JUMP of the reference, or
    # when a second source agrees with it within AGREE: AIG's 2011
    # recapitalisation took the count from 135m to 1.8bn in a quarter,
    # and the cover page and the weighted average both say so.
    agree = (
        long.join(
            long.select(
                "month",
                "ticker",
                pl.col("shares_source").alias("other"),
                pl.col("n_basis").alias("n_other"),
            ),
            on=["month", "ticker"],
        )
        .filter(pl.col("shares_source") != pl.col("other"))
        .filter(
            (pl.col("n_other") <= AGREE * pl.col("n_basis"))
            & (pl.col("n_other") >= pl.col("n_basis") / AGREE)
        )
        .select("month", "ticker", "shares_source")
        .unique()
        .with_columns(pl.lit(True).alias("agrees"))
    )
    long = long.join(agree, on=["month", "ticker", "shares_source"], how="left")
    # Agreement rescues a recapitalisation, not a units error: two
    # sources both in thousands agree with each other too (Garmin), and a
    # merger shell's cover page and balance sheet both say 1 share.
    long = long.with_columns(
        (
            (
                (pl.col("n_basis") <= JUMP * pl.col("reference"))
                & (pl.col("n_basis") >= pl.col("reference") / JUMP)
            )
            | (
                pl.col("agrees").fill_null(False)
                & (pl.col("n_basis") <= UNITS * pl.col("reference"))
                & (pl.col("n_basis") >= pl.col("reference") / UNITS)
            )
        ).alias("in_band")
    ).with_columns(
        # A merger shell's 1 or 100 shares stays a shell for as long as
        # it is the only count the registrant has (Baker Hughes, a GE
        # company, 2017-18); no index member has fewer than MIN_SHARES.
        (pl.col("in_band") & (pl.col("n_basis") >= MIN_SHARES)).alias("in_band")
    )
    chosen = (
        long.sort(
            "ticker", "month", "in_band", "rank", descending=[False, False, True, False]
        )
        .unique(subset=["month", "ticker"], keep="first", maintain_order=True)
        .with_columns((~pl.col("in_band")).alias("implausible"))
    )
    return chosen.select(
        "month",
        "ticker",
        "n_shares",
        "shares_source",
        "shares_filed",
        "split_factor",
        "n_basis",
        "implausible",
    ).sort("month", "ticker")


# --- cross-check ------------------------------------------------------


def flag_ratio(ratio: float | None, band: tuple[float, float] = RATIO_BAND) -> bool:
    """True when the SEC/yfinance ratio is outside the band (or missing)."""
    if ratio is None or ratio != ratio:
        return True
    return not (band[0] <= ratio <= band[1])


def crosscheck(sec: pl.DataFrame, yf: pl.DataFrame) -> pl.DataFrame:
    """Frame[ticker, sec_shares, yf_shares, ratio, sec_source, sec_cap,
    yf_cap, cap_ratio, flag]. ``sec`` has ticker, sec_shares, sec_source,
    sec_cap; ``yf`` has ticker, yf_shares, yf_cap."""
    out = sec.join(yf, on="ticker", how="left").with_columns(
        (pl.col("sec_shares") / pl.col("yf_shares")).alias("ratio"),
        (pl.col("sec_cap") / pl.col("yf_cap")).alias("cap_ratio"),
    )
    return out.with_columns(
        pl.col("ratio").map_elements(flag_ratio, return_dtype=pl.Boolean).alias("flag")
    ).select(
        "ticker",
        "sec_shares",
        "yf_shares",
        "ratio",
        "sec_source",
        "sec_cap",
        "yf_cap",
        "cap_ratio",
        "flag",
    )


# --- overrides ----------------------------------------------------------

OVERRIDE_SCHEMA = {"ticker": pl.Utf8, "source": pl.Utf8, "reason": pl.Utf8}


def load_overrides(cfg: Config) -> pl.DataFrame:
    """data/checks/shares_overrides.csv (ticker, source, reason), or empty.
    ``source`` is one of SOURCES or ``unresolved``."""
    path = cfg.data / "checks" / "shares_overrides.csv"
    if not path.exists():
        return pl.DataFrame(schema=OVERRIDE_SCHEMA)
    df = pl.read_csv(path, schema_overrides=OVERRIDE_SCHEMA).select(
        list(OVERRIDE_SCHEMA)
    )
    bad = df.filter(~pl.col("source").is_in([*SOURCES, "unresolved"]))
    if bad.height:
        raise ValueError(f"shares_overrides.csv: unknown source {bad['source'][0]!r}")
    return df
