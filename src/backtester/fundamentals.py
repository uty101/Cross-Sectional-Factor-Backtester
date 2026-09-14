"""SEC Financial Statement Data Sets, keyed on filing date.

    fetch            the quarterly zips, 2009q1 onward, never overwritten
    ingest           sub.txt + num.txt of every zip -> one long parquet of the
                     concepts in tag_map.toml (DuckDB does the reading)
    first_filed      per (cik, concept, period, qtrs) keep the earliest filing
                     (invariant 2): amendments and later comparatives do not
                     rewrite history
    asof_join        the point-in-time join (invariant 1): the value used at
                     month-end t was filed on or before t - buffer_days
    signal           book_to_price, earnings_yield, gross_profitability,
                     accruals, asset_growth from the as-of panel

Flow concepts (income, cash flow) are taken as annual values from 10-K
filings (qtrs = 4) and updated when the next 10-K is filed; stock
concepts (balance sheet, shares) are the latest 10-K or 10-Q value. That
is the Fama-French annual convention with the six-month lag replaced by
the actual filing date, which is what the brief asks for. A trailing
twelve-month build from 10-Qs is a refinement, not done here.
"""

from __future__ import annotations

import tomllib
import warnings
import zipfile
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config

SEC_BASE = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
FIRST_QUARTER = (2009, 1)
SEC_USER_AGENT = "Utkarsh Malhotra factor-research utkarsh.malhotra@yahoo.co.uk"
MIN_CAP = 1e9
# How old a reported period may be before the value is treated as missing:
# an annual figure is stale 18 months after its year end (the next 10-K is
# due within 12), a quarterly one 9 months after its quarter end.
MAX_AGE_MONTHS = {
    "flow": 18,
    "latest_flow": 9,
    "stock": 9,
    "annual_stock": 18,
    "ttm": 9,  # a trailing sum is refreshed every 10-Q
}
TAG_MAP = Path(__file__).with_name("tag_map.toml")

NUM_SCHEMA = {
    "adsh": pl.Utf8,
    "cik": pl.Int64,
    "concept": pl.Utf8,
    "tag": pl.Utf8,
    "ddate": pl.Date,
    "qtrs": pl.Int32,
    "value": pl.Float64,
    "filed": pl.Date,
    "form": pl.Utf8,
    "fy": pl.Int32,
    "fp": pl.Utf8,
    "sic": pl.Int32,
    "name": pl.Utf8,
}


def quarters(last: date) -> list[str]:
    out = []
    y, q = FIRST_QUARTER
    while (y, q) <= (last.year, (last.month - 1) // 3 + 1):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


# --- fetch --------------------------------------------------------------


def fetch(cfg: Config, as_of: date) -> list[Path]:
    """Every quarterly zip not already on disk. A quarter's zip is the same
    bytes forever once published, so it is stamped with its quarter, not
    the fetch date, and skipped if present. The most recent quarter may not
    exist yet; a 404 there is not an error."""
    import requests

    root = cfg.data / "raw"
    stored = []
    for q in quarters(as_of):
        rel = f"sec/{q}.zip"
        if (root / rel).exists():
            stored.append(root / rel)
            continue
        r = requests.get(
            SEC_BASE + f"{q}.zip", headers={"User-Agent": SEC_USER_AGENT}, timeout=600
        )
        if r.status_code == 404:
            continue
        r.raise_for_status()
        stored.append(raw.store_raw(root, rel, r.content, SEC_BASE + f"{q}.zip"))
    # The SEC's own ticker -> CIK map, date-stamped: it changes as names
    # list and delist (BUILD_PLAN 4.6).
    rel = f"sec/company_tickers_{as_of.isoformat()}.json"
    if not (root / rel).exists():
        r = requests.get(
            SEC_TICKERS, headers={"User-Agent": SEC_USER_AGENT}, timeout=60
        )
        r.raise_for_status()
        stored.append(raw.store_raw(root, rel, r.content, SEC_TICKERS))
    return stored


def sec_tickers(cfg: Config) -> dict[str, int] | None:
    """ticker -> cik from the latest company_tickers.json on disk, or None
    if none was fetched. Tickers use the repo's convention (BRK-B)."""
    import json

    try:
        path = raw.latest(cfg.data / "raw", "sec/company_tickers_*.json")
    except FileNotFoundError:
        return None
    entries = json.loads(path.read_text(encoding="utf-8")).values()
    return {e["ticker"].replace(".", "-"): int(e["cik_str"]) for e in entries}


# --- tag map ------------------------------------------------------------


def load_tag_map(path: Path = TAG_MAP) -> dict[str, dict]:
    """concept -> {tags: [...ordered], kind: 'flow' | 'stock'}."""
    with open(path, "rb") as f:
        return tomllib.load(f)["concept"]


def tag_priority(tag_map: dict[str, dict]) -> pl.DataFrame:
    """Frame[tag, concept, priority]; lower priority wins within a concept."""
    rows = [
        {"tag": t, "concept": c, "priority": i}
        for c, spec in tag_map.items()
        for i, t in enumerate(spec["tags"])
    ]
    return pl.DataFrame(
        rows, schema={"tag": pl.Utf8, "concept": pl.Utf8, "priority": pl.Int32}
    )


# --- ingest -------------------------------------------------------------


def ingest_quarter(zip_path: Path, tags: list[str]) -> pl.DataFrame:
    """num.txt rows for ``tags`` (consolidated: no segment, no coreg) joined
    to sub.txt for cik, form, filing date, fiscal year/period, SIC, name."""
    import duckdb

    with zipfile.ZipFile(zip_path) as z:
        num_bytes = z.read("num.txt")
        sub_bytes = z.read("sub.txt")
    tmp = zip_path.parent / "_tmp"
    tmp.mkdir(exist_ok=True)
    num_p, sub_p = tmp / f"{zip_path.stem}_num.txt", tmp / f"{zip_path.stem}_sub.txt"
    num_p.write_bytes(num_bytes)
    sub_p.write_bytes(sub_bytes)
    try:
        con = duckdb.connect()
        tag_list = ",".join(f"'{t}'" for t in tags)
        df = con.execute(
            f"""
            WITH num AS (
                SELECT adsh, tag, ddate, qtrs, uom, value,
                       coalesce(segments, '') AS segments, coalesce(coreg, '') AS coreg
                FROM read_csv('{num_p.as_posix()}', delim='\t', header=true, quote='',
                              all_varchar=true, ignore_errors=true)
                WHERE tag IN ({tag_list})
            ),
            sub AS (
                SELECT adsh, cik, name, sic, form, fy, fp, filed
                FROM read_csv('{sub_p.as_posix()}', delim='\t', header=true, quote='',
                              all_varchar=true, ignore_errors=true)
                WHERE form IN ('10-K', '10-K/A', '10-Q', '10-Q/A', '10-KT', '10-QT')
            )
            SELECT num.adsh, sub.cik, num.tag, num.ddate, num.qtrs, num.uom, num.value,
                   sub.filed, sub.form, sub.fy, sub.fp, sub.sic, sub.name
            FROM num JOIN sub USING (adsh)
            WHERE num.segments = '' AND num.coreg = '' AND num.value <> ''
              AND num.uom IN ('USD', 'shares')
            """
        ).pl()
    finally:
        num_p.unlink(missing_ok=True)
        sub_p.unlink(missing_ok=True)
    return df.select(
        "adsh",
        pl.col("cik").cast(pl.Int64),
        "tag",
        pl.col("ddate").str.strptime(pl.Date, "%Y%m%d", strict=False),
        pl.col("qtrs").cast(pl.Int32, strict=False),
        pl.col("value").cast(pl.Float64, strict=False),
        pl.col("filed").str.strptime(pl.Date, "%Y%m%d", strict=False),
        "form",
        pl.col("fy").cast(pl.Int32, strict=False),
        "fp",
        pl.col("sic").cast(pl.Int32, strict=False),
        "name",
    ).drop_nulls(["cik", "ddate", "filed", "value"])


def ingest(cfg: Config) -> pl.DataFrame:
    """All quarters -> data/interim/sec_num.parquet, concept-labelled."""
    tag_map = load_tag_map()
    prio = tag_priority(tag_map)
    tags = prio["tag"].to_list()
    zips = sorted((cfg.data / "raw" / "sec").glob("*.zip"))
    frames = [ingest_quarter(z, tags) for z in zips]
    df = pl.concat(frames).join(prio, on="tag", how="inner")
    # Within one filing and (concept, ddate, qtrs), the highest-priority tag
    # that is present is the concept's value.
    df = (
        df.sort("priority")
        .unique(subset=["adsh", "concept", "ddate", "qtrs"], keep="first")
        .select(
            "adsh",
            "cik",
            "concept",
            "tag",
            "ddate",
            "qtrs",
            "value",
            "filed",
            "form",
            "fy",
            "fp",
            "sic",
            "name",
        )
        .sort("cik", "concept", "ddate", "filed")
    )
    out = cfg.data / "interim" / "sec_num.parquet"
    df.with_columns(pl.lit(zips[-1].stem).alias("as_of")).write_parquet(out)
    return df


# --- point in time ------------------------------------------------------


def first_filed(num: pl.DataFrame) -> pl.DataFrame:
    """Keep the earliest filing of each (cik, concept, ddate, qtrs) (invariant 2).

    A 10-K/A that restates, and next year's 10-K that carries last year as
    a comparative column, both come later and both lose.
    """
    return (
        num.sort("filed", "adsh")
        .unique(subset=["cik", "concept", "ddate", "qtrs"], keep="first")
        .sort("cik", "concept", "ddate")
    )


def asof_join(
    panel: pl.DataFrame,
    values: pl.DataFrame,
    buffer_days: int,
    value_col: str = "value",
) -> pl.DataFrame:
    """For each (month, cik) in ``panel``, the value from the latest filing
    with ``filed + buffer_days <= month`` (invariant 1).

    ``values`` needs cik, ddate, filed, value. Within a cik a filing that
    does not advance the period (an amendment for an old period arriving
    after a newer one) is dropped first, so the as-of pick is by filing
    date and the period it reports on can only move forward.
    """
    v = (
        values.sort("cik", "filed", "ddate")
        .with_columns(pl.col("ddate").cum_max().over("cik").alias("_maxd"))
        .filter(pl.col("ddate") == pl.col("_maxd"))
        .with_columns(
            (pl.col("filed") + timedelta(days=buffer_days)).alias("available")
        )
        .select("cik", "available", "ddate", pl.col(value_col).alias("value"))
        .sort("available")
    )
    p = panel.select("month", "cik").unique().sort("month")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # polars cannot check sortedness with `by`
        joined = p.join_asof(
            v, left_on="month", right_on="available", by="cik", strategy="backward"
        )
    return joined.select("month", "cik", "value", "ddate", "available").rename(
        {"ddate": "period_end", "available": "available_from"}
    )


def ttm(ff: pl.DataFrame) -> pl.DataFrame:
    """Trailing twelve months of every flow concept, at every filing.

    At a 10-K the TTM is the annual value (qtrs 4). At a 10-Q reporting
    ``k`` quarters year-to-date at ``ddate``, it is

        YTD(k, ddate) + annual(fye) - YTD(k, ddate - 12 months)

    with ``fye = ddate - 3k months``: the previous fiscal year end. All
    three are first-filed values; the row is stamped ``filed`` with the
    latest of their filing dates, so it is available only once every
    input was (invariant 1). A 10-Q whose annual or prior-year YTD is
    missing produces no row rather than a partial sum (BUILD_PLAN 4.5).
    ``ff`` is ``first_filed`` output; the result has the same columns
    plus ``ttm`` in place of ``value``.
    """
    flow = ff.filter(pl.col("qtrs").is_in([1, 2, 3, 4]))
    annual = flow.filter(pl.col("qtrs") == 4).select(
        "cik",
        "concept",
        pl.col("ddate").alias("fye"),
        pl.col("value").alias("annual"),
        pl.col("filed").alias("filed_a"),
    )
    ytd = flow.filter(pl.col("qtrs") < 4).with_columns(
        pl.col("ddate")
        .dt.offset_by(pl.format("-{}mo", pl.col("qtrs") * 3))
        .dt.month_end()
        .alias("fye"),
        pl.col("ddate").dt.offset_by("-12mo").dt.month_end().alias("prev"),
    )
    prior = ytd.select(
        "cik",
        "concept",
        pl.col("ddate").alias("prev"),
        "qtrs",
        pl.col("value").alias("prior"),
        pl.col("filed").alias("filed_p"),
    )
    q = (
        ytd.join(annual, on=["cik", "concept", "fye"], how="inner")
        .join(prior, on=["cik", "concept", "prev", "qtrs"], how="inner")
        .with_columns(
            (pl.col("value") + pl.col("annual") - pl.col("prior")).alias("value"),
            pl.max_horizontal("filed", "filed_a", "filed_p").alias("filed"),
        )
        .select(ff.columns)
    )
    k = flow.filter(pl.col("qtrs") == 4).select(ff.columns)
    return pl.concat([q, k]).sort("cik", "concept", "ddate", "filed")


# --- monthly panel and signals ------------------------------------------


def monthly_panel(
    cfg: Config, num: pl.DataFrame, ciks: pl.DataFrame, months: list[date]
) -> pl.DataFrame:
    """Frame[month, ticker, cik, <concept>..., <concept>_period_end].

    Flow concepts from annual 10-K values (qtrs = 4); stock concepts from
    any 10-K/10-Q (qtrs = 0). ``ciks`` is Frame[ticker, cik].
    """
    tag_map = load_tag_map()
    ff = first_filed(num)
    base = pl.DataFrame({"month": months}).join(ciks, how="cross")
    out = base
    for concept, spec in tag_map.items():
        if spec["kind"] == "flow":
            vals = ff.filter(
                (pl.col("concept") == concept)
                & (pl.col("qtrs") == 4)
                & pl.col("form").str.starts_with("10-K")
            )
        elif spec["kind"] == "annual_stock":
            vals = ff.filter(
                (pl.col("concept") == concept)
                & (pl.col("qtrs") == 0)
                & pl.col("form").str.starts_with("10-K")
            )
        elif spec["kind"] == "latest_flow":
            # The most recently reported period of any length: a quarter
            # from a 10-Q or a year from a 10-K.
            vals = ff.filter(
                (pl.col("concept") == concept) & pl.col("qtrs").is_in([1, 4])
            )
        else:
            vals = ff.filter((pl.col("concept") == concept) & (pl.col("qtrs") == 0))
        j = asof_join(base, vals, cfg.asof_buffer_days)
        # A value is carried forward only while it is current: a name that
        # has stopped filing must not keep its last 10-K forever.
        max_age = MAX_AGE_MONTHS[spec["kind"]]
        j = j.with_columns(
            pl.when(
                pl.col("period_end") < pl.col("month").dt.offset_by(f"-{max_age}mo")
            )
            .then(None)
            .otherwise(pl.col("value"))
            .alias("value")
        )
        out = out.join(
            j.rename({"value": concept, "period_end": f"{concept}_period_end"}).drop(
                "available_from"
            ),
            on=["month", "cik"],
            how="left",
        )
    # Trailing twelve months of every flow concept, alongside the annual.
    trailing = ttm(ff.filter(pl.col("concept").is_in(_flow_concepts(tag_map))))
    for concept in _flow_concepts(tag_map):
        vals = trailing.filter(pl.col("concept") == concept)
        j = asof_join(base, vals, cfg.asof_buffer_days)
        max_age = MAX_AGE_MONTHS["ttm"]
        j = j.with_columns(
            pl.when(
                pl.col("period_end") < pl.col("month").dt.offset_by(f"-{max_age}mo")
            )
            .then(None)
            .otherwise(pl.col("value"))
            .alias("value")
        )
        out = out.join(
            j.select("month", "cik", pl.col("value").alias(f"{concept}_ttm")),
            on=["month", "cik"],
            how="left",
        )
    return out


def _flow_concepts(tag_map: dict[str, dict]) -> list[str]:
    return [c for c, spec in tag_map.items() if spec["kind"] == "flow"]


def signal(
    name: str,
    fundamentals: pl.DataFrame,
    monthly: pl.DataFrame,
    caps: pl.DataFrame | None,
) -> pl.DataFrame:
    """Frame[month, ticker, value] for a fundamentals-based signal."""
    f = fundamentals
    # A ``_ttm`` suffix uses the trailing-twelve-month flows (BUILD_PLAN
    # 4.5) in place of the annual 10-K values; the formula is unchanged.
    sfx = ""
    if name.endswith("_ttm"):
        name, sfx = name[: -len("_ttm")], "_ttm"
    if name in ("book_to_price", "earnings_yield"):
        if caps is None:
            raise RuntimeError(f"{name} needs market caps")
        j = f.join(
            caps.select("month", "ticker", "cap"), on=["month", "ticker"], how="inner"
        )
        num = "equity" if name == "book_to_price" else "net_income" + sfx
        return j.filter((pl.col("cap") > 0) & pl.col(num).is_not_null()).select(
            "month", "ticker", (pl.col(num) / pl.col("cap")).alias("value")
        )
    if name == "operating_profitability":
        # French's RMW numerator is revenue less COGS, SG&A and interest;
        # pre-tax income is the reported line closest to that, with operating
        # income as the fallback. Over book equity at the same fiscal year
        # end, as French does, with the latest quarterly equity as fallback.
        den = pl.coalesce("equity_fy", "equity")
        return (
            f.filter(den > 0)
            .select(
                "month",
                "ticker",
                (pl.coalesce("pretax_income", "operating_income") / den).alias("value"),
            )
            .filter(pl.col("value").is_not_null())
        )
    if name == "gross_profitability":
        gp = pl.coalesce(
            pl.col("gross_profit" + sfx), pl.col("revenue" + sfx) - pl.col("cogs" + sfx)
        )
        return (
            f.filter(pl.col("assets") > 0)
            .select("month", "ticker", (gp / pl.col("assets")).alias("value"))
            .filter(pl.col("value").is_not_null())
        )
    if name == "accruals":
        # Cash-flow accruals: (net income - cash from operations) / assets,
        # negated so that low accruals is the long leg.
        return (
            f.filter(pl.col("assets") > 0)
            .select(
                "month",
                "ticker",
                (
                    -(pl.col("net_income" + sfx) - pl.col("cfo" + sfx))
                    / pl.col("assets")
                ).alias("value"),
            )
            .filter(pl.col("value").is_not_null())
        )
    if name == "asset_growth":
        # Assets against the value reported a year earlier: negated, low growth long.
        prev = f.select(
            "month", "ticker", pl.col("assets").alias("assets_prev")
        ).with_columns(
            pl.col("month").dt.offset_by("12mo").dt.month_end().alias("month")
        )
        return (
            f.join(prev, on=["month", "ticker"], how="inner")
            .filter((pl.col("assets_prev") > 0) & (pl.col("assets") > 0))
            .select(
                "month",
                "ticker",
                (-(pl.col("assets") / pl.col("assets_prev") - 1)).alias("value"),
            )
        )
    raise KeyError(name)


def market_caps(fundamentals: pl.DataFrame, monthly: pl.DataFrame) -> pl.DataFrame:
    """Frame[month, ticker, cap, shares_source]: unadjusted month-end price x
    shares outstanding as of the latest filing (point in time, like everything
    else). The diluted weighted-average count first: it is the per-share
    denominator every filer reports and gets the units right; the
    balance-sheet count, which a few large filers mis-scale (RTX, CMG), only
    where that is missing."""
    sh = fundamentals.select(
        "month",
        "ticker",
        pl.coalesce("shares_wavg", "shares").alias("n_shares"),
        pl.when(pl.col("shares_wavg").is_not_null())
        .then(pl.lit("weighted_average"))
        .when(pl.col("shares").is_not_null())
        .then(pl.lit("balance_sheet"))
        .otherwise(pl.lit(None))
        .alias("shares_source"),
    )
    caps = (
        monthly.select("month", "ticker", "px_me_raw")
        .join(sh, on=["month", "ticker"], how="inner")
        .filter((pl.col("n_shares") > 0) & (pl.col("px_me_raw") > 0))
        .select(
            "month",
            "ticker",
            (pl.col("px_me_raw") * pl.col("n_shares")).alias("cap"),
            "shares_source",
        )
    )
    # A member of the S&P 500 is never worth less than a billion dollars. A
    # cap below that is a share count in the wrong units: Berkshire reports
    # class-A equivalents against a class-B price. Dropped, and listed.
    return caps.filter(pl.col("cap") >= MIN_CAP)


# --- pipeline entry -----------------------------------------------------


def build(cfg: Config, reingest: bool = False) -> pl.DataFrame:
    """ingest -> cik map -> monthly as-of panel -> caps; writes the checks."""
    from backtester import sectors

    cached = cfg.data / "interim" / "sec_num.parquet"
    num = ingest(cfg) if reingest or not cached.exists() else pl.read_parquet(cached)
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    constituents = pl.read_parquet(cfg.data / "interim" / "sp500_constituents.parquet")
    ciks, cik_log = sectors.cik_map(membership, constituents, num, sec_tickers(cfg))
    sectors.build(cfg, num, ciks)

    monthly = pl.read_parquet(cfg.data / "processed" / "returns_monthly.parquet")
    daily = pl.read_parquet(cfg.data / "interim" / "prices_daily.parquet")
    months = sorted(monthly.get_column("month").unique().to_list())
    panel = monthly_panel(cfg, num, ciks, months)

    # Unadjusted month-end close for market cap: shares outstanding are not
    # split-adjusted, and neither should the price be.
    px_raw = monthly.select("month", "ticker", "t").join(
        daily.select("date", "ticker", pl.col("close").alias("px_me_raw")),
        left_on=["t", "ticker"],
        right_on=["date", "ticker"],
        how="left",
    )
    caps = market_caps(panel, px_raw)
    implausible = (
        monthly.select("month", "ticker", "t")
        .join(px_raw.select("month", "ticker", "px_me_raw"), on=["month", "ticker"])
        .join(
            panel.select("month", "ticker", "shares", "shares_wavg"),
            on=["month", "ticker"],
        )
        .with_columns(
            (pl.col("px_me_raw") * pl.coalesce("shares_wavg", "shares")).alias("cap")
        )
        .filter(pl.col("cap").is_not_null() & (pl.col("cap") < MIN_CAP))
        .group_by("ticker")
        .agg(pl.len().alias("months"), pl.col("cap").median().alias("median_cap"))
        .sort("months", descending=True)
    )

    processed = cfg.data / "processed"
    stamp = pl.lit(num["as_of"][0] if "as_of" in num.columns else "").alias("as_of")
    panel.with_columns(stamp).write_parquet(processed / "fundamentals_monthly.parquet")
    caps.with_columns(stamp).write_parquet(processed / "market_cap.parquet")

    checks = cfg.data / "checks"
    cik_log.write_csv(checks / "cik_map.csv")
    implausible.write_csv(checks / "market_cap_dropped.csv")
    tag_coverage(num, ciks, cfg).write_csv(checks / "tag_coverage.csv")
    concept_coverage(panel, membership, cfg, caps).write_csv(
        checks / "fundamentals_coverage.csv"
    )
    amendments(num).write_csv(checks / "sec_amendments_by_year.csv")
    return panel


def tag_coverage(num: pl.DataFrame, ciks: pl.DataFrame, cfg: Config) -> pl.DataFrame:
    """Per concept and fiscal year: share of universe CIKs with a 10-K value,
    and which tag supplied it. The brief's 'check coverage per year'."""
    universe_ciks = ciks.select("cik").unique()
    n = universe_ciks.height
    k = (
        num.join(universe_ciks, on="cik", how="inner")
        .filter(
            pl.col("form").str.starts_with("10-K")
            & (pl.col("fy") >= cfg.start.year - 1)
        )
        .group_by("concept", "fy")
        .agg(
            pl.col("cik").n_unique().alias("ciks"),
            pl.col("tag").mode().first().alias("main_tag"),
        )
        .with_columns((100 * pl.col("ciks") / n).round(1).alias("pct_of_universe"))
        .sort("concept", "fy")
    )
    return k


def concept_coverage(
    panel: pl.DataFrame,
    membership: pl.DataFrame,
    cfg: Config,
    caps: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Per month: members with each concept available as-of."""
    from backtester.universe import members_at

    concepts = [c for c in load_tag_map()]
    rows = []
    for (m,), g in panel.group_by("month"):
        if not (cfg.start <= m <= cfg.end):
            continue
        members = set(members_at(membership, m))
        g = g.filter(pl.col("ticker").is_in(list(members)))
        row = {"month": m, "n_members": len(members)}
        for c in concepts:
            row[c] = int(g[c].is_not_null().sum())
        if caps is not None:
            row["market_cap"] = caps.filter(
                (pl.col("month") == m) & pl.col("ticker").is_in(list(members))
            ).height
        rows.append(row)
    return pl.DataFrame(rows).sort("month")


def amendments(num: pl.DataFrame) -> pl.DataFrame:
    """Per filing year: 10-K/A and 10-Q/A filings as a share of all, the size
    of the first-filed choice."""
    filings = num.select(
        "adsh", "form", pl.col("filed").dt.year().alias("year")
    ).unique()
    return (
        filings.group_by("year")
        .agg(
            pl.len().alias("filings"),
            pl.col("form").str.ends_with("/A").sum().alias("amendments"),
        )
        .with_columns(
            (100 * pl.col("amendments") / pl.col("filings")).round(2).alias("pct")
        )
        .sort("year")
    )
