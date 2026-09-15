"""SEC Financial Statement Data Sets, keyed on filing date.

    fetch            the quarterly zips, 2009q1 onward, never overwritten
    ingest           sub.txt + num.txt of every zip -> one long parquet of the
                     concepts in tag_map.toml (DuckDB does the reading)
    ingest_sub       sub.txt of every zip, every form -> the filer index
    first_filed      per (cik, concept, period, qtrs) keep the earliest filing
                     (invariant 2): amendments and later comparatives do not
                     rewrite history
    asof_join        the point-in-time join (invariant 1): the value used at
                     month-end t was filed on or before t - buffer_days
    signal           book_to_price, earnings_yield, gross_profitability,
                     accruals, asset_growth from the as-of panel
    public_float_check
                     the pipeline's cap at the float date against the 10-K's
                     EntityPublicFloat (FIX_PLAN_3 H1); feeds identity.py

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
    if none was fetched. The SEC writes share classes with a dash (BRK-B)
    and the universe with a dot (BRK.B); both spellings are keyed."""
    import json

    try:
        path = raw.latest(cfg.data / "raw", "sec/company_tickers_*.json")
    except FileNotFoundError:
        return None
    entries = json.loads(path.read_text(encoding="utf-8")).values()
    out = {}
    for e in entries:
        out[e["ticker"]] = int(e["cik_str"])
        out[e["ticker"].replace("-", ".")] = int(e["cik_str"])
    return out


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


def candidate_tags(
    cfg: Config, concept: str, fy: int, ciks: list[int], limit: int = 40
) -> pl.DataFrame:
    """Frame[tag, n_ciks, example_name]: every tag reported in fiscal year
    ``fy`` by the given CIKs (the ones with no value for ``concept``),
    from the raw zips of that year, most widely used first. What the
    tag-map agent reads to propose additions (BUILD_PLAN 11.4); the
    interim cache holds mapped tags only, so it cannot come from there.
    """
    import duckdb

    zips = sorted((cfg.data / "raw" / "sec").glob(f"{fy}q*.zip")) + sorted(
        (cfg.data / "raw" / "sec").glob(f"{fy + 1}q1.zip")
    )
    if not zips or not ciks:
        return pl.DataFrame(
            schema={"tag": pl.Utf8, "n_ciks": pl.Int64, "example": pl.Utf8}
        )
    cik_list = ",".join(str(int(c)) for c in ciks)
    tmp = cfg.data / "raw" / "sec" / "_tmp"
    tmp.mkdir(exist_ok=True)
    frames = []
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            num_p, sub_p = tmp / f"{z.stem}_num.txt", tmp / f"{z.stem}_sub.txt"
            num_p.write_bytes(zf.read("num.txt"))
            sub_p.write_bytes(zf.read("sub.txt"))
        try:
            con = duckdb.connect()
            frames.append(
                con.execute(
                    f"""
                    SELECT n.tag, s.cik, s.name
                    FROM read_csv('{num_p.as_posix()}', delim='	', header=true,
                                  quote='', all_varchar=true, ignore_errors=true) n
                    JOIN read_csv('{sub_p.as_posix()}', delim='	', header=true,
                                  quote='', all_varchar=true, ignore_errors=true) s
                      USING (adsh)
                    WHERE s.form IN ('10-K', '10-Q') AND s.cik IN ({cik_list})
                      AND coalesce(n.segments, '') = '' AND n.uom = 'USD'
                    """
                ).pl()
            )
        finally:
            num_p.unlink(missing_ok=True)
            sub_p.unlink(missing_ok=True)
    df = pl.concat(frames)
    return (
        df.group_by("tag")
        .agg(
            pl.col("cik").n_unique().alias("n_ciks"),
            pl.col("name").first().alias("example"),
        )
        .sort("n_ciks", descending=True)
        .head(limit)
    )


SUB_SCHEMA = {
    "adsh": pl.Utf8,
    "cik": pl.Int64,
    "name": pl.Utf8,
    "form": pl.Utf8,
    "filed": pl.Date,
    "sic": pl.Int32,
    "countryba": pl.Utf8,
}


def ingest_sub(cfg: Config) -> pl.DataFrame:
    """Every filing in every quarterly zip, all forms -> data/interim/
    sec_sub.parquet. The num cache keeps 10-K/10-Q rows for mapped tags
    only; this is the full filer index the CIK audit needs, because a
    member with no row there is either a foreign filer (20-F, 40-F) or
    a name the map placed on the wrong CIK, and only sub.txt can say.
    """
    import duckdb

    zips = sorted((cfg.data / "raw" / "sec").glob("*.zip"))
    tmp = cfg.data / "raw" / "sec" / "_tmp"
    tmp.mkdir(exist_ok=True)
    frames = []
    for z in zips:
        sub_p = tmp / f"{z.stem}_sub.txt"
        with zipfile.ZipFile(z) as zf:
            sub_p.write_bytes(zf.read("sub.txt"))
        try:
            con = duckdb.connect()
            df = con.execute(
                f"""
                SELECT adsh, cik, name, form, filed, sic, countryba
                FROM read_csv('{sub_p.as_posix()}', delim='	', header=true,
                              quote='', all_varchar=true, ignore_errors=true)
                """
            ).pl()
        finally:
            sub_p.unlink(missing_ok=True)
        frames.append(
            df.select(
                "adsh",
                pl.col("cik").cast(pl.Int64, strict=False),
                "name",
                "form",
                pl.col("filed").str.strptime(pl.Date, "%Y%m%d", strict=False),
                pl.col("sic").cast(pl.Int32, strict=False),
                "countryba",
            ).drop_nulls(["cik", "filed"])
        )
    out = pl.concat(frames).sort("cik", "filed")
    out.with_columns(pl.lit(zips[-1].stem).alias("as_of")).write_parquet(
        cfg.data / "interim" / "sec_sub.parquet"
    )
    return out


def load_sub(cfg: Config) -> pl.DataFrame:
    cached = cfg.data / "interim" / "sec_sub.parquet"
    return pl.read_parquet(cached) if cached.exists() else ingest_sub(cfg)


# Bump when the ingest's own rules change (what it keeps, how it breaks a
# tie): the cache stamp covers the rules as well as the tag map.
INGEST_VERSION = "2"


def tag_map_hash(path: Path = TAG_MAP) -> str:
    """sha256 of tag_map.toml and INGEST_VERSION, stamped on the num cache
    so a cache built under an older map or older rules is re-ingested
    rather than silently missing the tags added since (CLAUDE.md:
    "otherwise new tags silently come back empty"; the 2026-09-15
    recompute found exactly that)."""
    import hashlib

    return hashlib.sha256(path.read_bytes() + INGEST_VERSION.encode()).hexdigest()[:16]


def load_num(cfg: Config, reingest: bool = False) -> pl.DataFrame:
    """The num cache, re-ingested when absent, asked for, or built under
    a different tag map."""
    cached = cfg.data / "interim" / "sec_num.parquet"
    if reingest or not cached.exists():
        return ingest(cfg)
    stamp = pl.read_parquet(cached, n_rows=1)
    if (
        "tag_map_hash" not in stamp.columns
        or stamp["tag_map_hash"][0] != tag_map_hash()
    ):
        return ingest(cfg)
    return pl.read_parquet(cached)


def ingest(cfg: Config) -> pl.DataFrame:
    """All quarters -> data/interim/sec_num.parquet, concept-labelled."""
    tag_map = load_tag_map()
    prio = tag_priority(tag_map)
    tags = prio["tag"].to_list()
    zips = sorted((cfg.data / "raw" / "sec").glob("*.zip"))
    frames = [ingest_quarter(z, tags) for z in zips]
    df = pl.concat(frames).join(prio, on="tag", how="inner")
    # Within one filing and (concept, ddate, qtrs), the highest-priority tag
    # that is present is the concept's value. A filing can carry the same
    # tag twice for the same period without a segment (a share count for
    # the total and for a class, both bare); the larger value wins, as a
    # rule, because the sort's tie order is not one: the 2026-09-15
    # recompute differed from the incremental build by exactly that row.
    df = (
        df.sort(["priority", "value"], descending=[False, True])
        .unique(
            subset=["adsh", "concept", "ddate", "qtrs"],
            keep="first",
            maintain_order=True,
        )
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
    df.with_columns(
        pl.lit(zips[-1].stem).alias("as_of"),
        pl.lit(tag_map_hash()).alias("tag_map_hash"),
    ).write_parquet(out)
    return df


# --- point in time ------------------------------------------------------


def first_filed(num: pl.DataFrame) -> pl.DataFrame:
    """Keep the earliest filing of each (cik, concept, ddate, qtrs) (invariant 2).

    A 10-K/A that restates, and next year's 10-K that carries last year as
    a comparative column, both come later and both lose.
    """
    # Two rows of one filing for one period can carry different values:
    # the FSDS row and the SEC API's fallback row (tag "companyconcept",
    # shares.load_api) for a weighted average the filer reported twice.
    # The tie is a rule, not the sort's whim: tag, then the larger value,
    # so the FSDS row (an upper-case us-gaap tag) beats the API's. The
    # 2026-09-15 recompute differed by ten such rows before this.
    keys = ["filed", "adsh"] + (["tag"] if "tag" in num.columns else []) + ["value"]
    return (
        num.sort(keys, descending=[False] * (len(keys) - 1) + [True])
        .unique(
            subset=["cik", "concept", "ddate", "qtrs"],
            keep="first",
            maintain_order=True,
        )
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
        # Two filings can become available on the same day (a 10-K and a
        # 10-Q, or a re-filing); the asof join takes the last row in sort
        # order, so the order must be a rule, not the sort's whim: the
        # later period wins, and the sort is stable.
        .sort(["available", "ddate", "value"], maintain_order=True)
    )
    p = panel.select("month", "cik").unique().sort("month")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # polars cannot check sortedness with `by`
        joined = p.join_asof(
            v, left_on="month", right_on="available", by="cik", strategy="backward"
        )
    assert_point_in_time(joined, "available")
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


def assert_point_in_time(df: pl.DataFrame, col: str = "available_from") -> None:
    """Raise if any row's ``col`` (the date a value became usable) is after
    its ``month``. The join guarantees it; this is the runtime check the
    plan asks for (BUILD_PLAN 5.5), so a future edit cannot leak quietly.
    """
    if col not in df.columns or "month" not in df.columns:
        return
    late = df.filter(pl.col(col).is_not_null() & (pl.col(col) > pl.col("month")))
    if late.height:
        r = late.row(0, named=True)
        raise AssertionError(
            f"{late.height} rows use data after their month, e.g. "
            f"{col}={r[col]} at month {r['month']} (invariant 1)"
        )


# --- monthly panel and signals ------------------------------------------


SHARE_CONCEPTS = ("shares", "shares_wavg", "shares_cover")
# A share count is carried up to 18 months, not 9: a few filers (General
# Dynamics, PPG, Humana) reach the panel only through the balance-sheet
# count of their 10-K, and the next 10-K is due within 12 months. A
# quarterly filer's count is refreshed long before that.
SHARE_MAX_AGE_MONTHS = 18


def monthly_panel(
    cfg: Config,
    num: pl.DataFrame,
    ciks: pl.DataFrame,
    months: list[date],
    cover: pl.DataFrame | None = None,
    extra_num: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Frame[month, ticker, cik, <concept>..., <concept>_period_end].

    ``cover`` (shares.build output: cik, ddate, filed, value) is joined
    as-of like a stock concept into ``shares_cover``. The three share
    concepts also keep ``<concept>_filed``, the filing date, because a
    split after that date changes the basis of the count (shares.py).

    Flow concepts from annual 10-K values (qtrs = 4); stock concepts from
    any 10-K/10-Q (qtrs = 0). ``ciks`` is Frame[ticker, cik, start, end]
    (start and end optional): a ticker's registrant at each month is
    resolved by ``sectors.cik_at``, so a name whose filer changed (Disney
    in 2019, CB in 2016) reads each era's own filings.
    """
    from backtester.sectors import cik_at

    tag_map = load_tag_map()
    if extra_num is not None and extra_num.height:
        # Share counts the FSDS is missing for a few filers, from the SEC
        # API (shares.load_api); same first-filed rule as everything else.
        num = pl.concat([num.select(extra_num.columns), extra_num])
    ff = first_filed(num)
    base = cik_at(ciks, months)
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
            # from a 10-Q or a year from a 10-K. A 10-K reports both the
            # annual average and the fourth quarter's at the same date;
            # the quarter is the shorter, more recent window and wins.
            # Before this was a sort tie, and it moved value's net Sharpe
            # by 0.03 (recompute check, 2026-09-14).
            vals = (
                ff.filter((pl.col("concept") == concept) & pl.col("qtrs").is_in([1, 4]))
                .sort("qtrs")
                .unique(
                    subset=["cik", "ddate", "filed"], keep="first", maintain_order=True
                )
            )
        else:
            vals = ff.filter((pl.col("concept") == concept) & (pl.col("qtrs") == 0))
        max_age = MAX_AGE_MONTHS[spec["kind"]]
        if concept in SHARE_CONCEPTS:
            max_age = max(max_age, SHARE_MAX_AGE_MONTHS)
        out = _join_concept(out, base, vals, concept, max_age, cfg)
    if cover is not None and cover.height:
        vals = cover.select("cik", "ddate", "filed", "value")
        out = _join_concept(out, base, vals, "shares_cover", SHARE_MAX_AGE_MONTHS, cfg)
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


def _join_concept(
    out: pl.DataFrame,
    base: pl.DataFrame,
    vals: pl.DataFrame,
    concept: str,
    max_age: int,
    cfg: Config,
) -> pl.DataFrame:
    j = asof_join(base, vals, cfg.asof_buffer_days)
    # A value is carried forward only while it is current: a name that
    # has stopped filing must not keep its last 10-K forever.
    j = j.with_columns(
        pl.when(pl.col("period_end") < pl.col("month").dt.offset_by(f"-{max_age}mo"))
        .then(None)
        .otherwise(pl.col("value"))
        .alias("value")
    )
    j = j.rename({"value": concept, "period_end": f"{concept}_period_end"})
    if concept in SHARE_CONCEPTS:
        j = j.with_columns(
            (pl.col("available_from") - timedelta(days=cfg.asof_buffer_days)).alias(
                f"{concept}_filed"
            )
        )
    return out.join(j.drop("available_from"), on=["month", "cik"], how="left")


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
        # (revenue - COGS) / assets, Novy-Marx (2013). Financials are
        # excluded by rule, as in the paper: a bank has no cost of goods
        # sold and its derived revenue over its balance sheet is not the
        # same quantity (FIX_PLAN F3).
        gp = pl.coalesce(
            pl.col("gross_profit" + sfx), pl.col("revenue" + sfx) - pl.col("cogs" + sfx)
        )
        if "sector" in f.columns:
            f = f.filter(pl.col("sector").ne_missing("Financials"))
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


def market_caps(
    fundamentals: pl.DataFrame,
    monthly: pl.DataFrame,
    splits: pl.DataFrame | None = None,
    overrides: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Frame[month, ticker, cap, shares_source, split_factor]: month-end
    close x shares outstanding as of the latest filing (point in time,
    like everything else), the count scaled by every split after its
    filing date so it is in the basis of the split-adjusted price
    (FIX_PLAN F2, shares.py). The cover-page count first, then the
    balance-sheet count, then the diluted weighted average; a ticker in
    ``overrides`` is pinned to one source or, if ``unresolved``, dropped.
    Nothing else is dropped: the old 1bn floor was catching the split
    mismatch, not a units error."""
    from backtester import shares

    if "shares_cover" not in fundamentals.columns:
        fundamentals = fundamentals.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("shares_cover")
        )
    sh = shares.resolve(
        fundamentals, splits, overrides, monthly.select("month", "ticker", "px_me_raw")
    )
    return (
        monthly.select("month", "ticker", "px_me_raw")
        .join(sh, on=["month", "ticker"], how="inner")
        .filter((pl.col("n_shares") > 0) & (pl.col("px_me_raw") > 0))
        .select(
            "month",
            "ticker",
            (pl.col("px_me_raw") * pl.col("n_basis")).alias("cap"),
            "shares_source",
            "split_factor",
            "implausible",
        )
    )


# --- public float cross-check (FIX_PLAN_3 H1) ---------------------------

FLOAT_CHECK_SCHEMA = {
    "ticker": pl.Utf8,
    "cik": pl.Int64,
    "fy": pl.Int32,
    "float_date": pl.Date,
    "month": pl.Date,
    "close": pl.Float64,
    "shares": pl.Float64,
    "shares_source": pl.Utf8,
    "cap": pl.Float64,
    "public_float": pl.Float64,
    "ratio": pl.Float64,
    "flag": pl.Utf8,
    "reason": pl.Utf8,
}
# ``float_scale`` is the filed float's own error, not the pipeline's: the
# cap is inside the band against the ticker's float in a neighbouring
# fiscal year (GE filed $201.5m for FY2011, in thousands; eBay 3e19 for
# FY2019; Mattel, Duke, DuPont likewise). Recorded, not excluded: the
# price and the count are that filer's. The other reasons name the size
# of a real flag and every one of them is excluded (identity.float_windows).
FLOAT_REASONS = ("float_scale", "near_split", "near_1000", "over_100x", "other")
NEAR = 0.15  # a ratio within 15% of a split factor or of 1000 is "near" it
ADJACENT_YEARS = 2  # how far to look for the neighbouring float
# A scale error is a factor of 1000 (thousands), 1e6 or 1e9; a flag under
# this size is never one, whatever the neighbouring year says (Chesapeake's
# 2021 cap is 63x its float: a stale pre-emergence count, not a decimals
# attribute).
SCALE_MIN = 100.0


def float_thresholds(cfg: Config) -> tuple[float, float]:
    c = dict(cfg.checks)
    return float(c.get("float_ratio_lo", 0.5)), float(c.get("float_ratio_hi", 20))


def public_float_check(
    floats: pl.DataFrame,
    ciks: pl.DataFrame,
    caps: pl.DataFrame,
    px: pl.DataFrame,
    lo: float,
    hi: float,
    splits: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """FLOAT_CHECK_SCHEMA rows: for every (ticker, fiscal year) with a
    public float, the pipeline's own market cap at the last month-end on
    or before the float date against the 10-K's ``EntityPublicFloat``.

    ``floats`` is FLOAT_SCHEMA (cik, adsh, ddate = float date, filed,
    form, value, fy); the first-filed value per (cik, float date) is
    used, so a 10-K/A does not rewrite the float. ``caps`` is the
    ``market_caps`` output the portfolios read (cap = close x count in
    the price basis, after the split factor and the plausibility guard),
    ``px`` is Frame[month, ticker, px_me_raw], and ``ciks`` the CIK map
    (ticker, cik, start, end) so the ticker is the registrant's at that
    month. ``ratio = cap / float``; ``flag`` is ``low`` under ``lo``,
    ``high`` over ``hi``, else blank. A (ticker, year) with no cap at
    that month has a null ratio and no flag: a missing float or a missing
    price never excludes anything, only a bad ratio does. ``reason``
    names the size of a flagged ratio: near a split factor of the ticker
    (``splits``: ticker, date, ratio), near 1000, beyond 100x, or other.
    """
    from backtester.sectors import cik_at

    if not floats.height:
        return pl.DataFrame(schema=FLOAT_CHECK_SCHEMA)
    ff = first_filed(
        floats.with_columns(
            pl.lit("public_float").alias("concept"),
            pl.lit(0, dtype=pl.Int32).alias("qtrs"),
        )
    ).select(
        "cik",
        pl.col("ddate").alias("float_date"),
        "fy",
        pl.col("value").alias("public_float"),
    )
    # The last month-end on or before the float date.
    ff = ff.with_columns(
        pl.when(pl.col("float_date") == pl.col("float_date").dt.month_end())
        .then(pl.col("float_date"))
        .otherwise(pl.col("float_date").dt.offset_by("-1mo").dt.month_end())
        .alias("month")
    )
    months = sorted(ff.get_column("month").unique().to_list())
    who = cik_at(ciks, months)
    out = (
        ff.join(who, on=["month", "cik"], how="inner")
        .join(
            px.select("month", "ticker", pl.col("px_me_raw").alias("close")),
            on=["month", "ticker"],
            how="left",
        )
        .join(
            caps.select("month", "ticker", "cap", "shares_source"),
            on=["month", "ticker"],
            how="left",
        )
        .with_columns(
            (pl.col("cap") / pl.col("close")).alias("shares"),
            (pl.col("cap") / pl.col("public_float")).alias("ratio"),
        )
        .with_columns(
            pl.when(pl.col("ratio").is_null())
            .then(pl.lit(""))
            .when(pl.col("ratio") < lo)
            .then(pl.lit("low"))
            .when(pl.col("ratio") > hi)
            .then(pl.lit("high"))
            .otherwise(pl.lit(""))
            .alias("flag")
        )
    )
    out = _float_reason(out, splits, lo, hi)
    return out.select(list(FLOAT_CHECK_SCHEMA)).sort("ticker", "float_date")


def _near(x: pl.Expr, target: pl.Expr | float) -> pl.Expr:
    return (x / target - 1).abs() <= NEAR


def _float_reason(
    check: pl.DataFrame, splits: pl.DataFrame | None, lo: float, hi: float
) -> pl.DataFrame:
    """``reason`` for the flagged rows. First the filed float is tested
    against the ticker's own floats within ADJACENT_YEARS: a cap inside
    [lo, hi] of any other year's float, when the flag is at least
    SCALE_MIN, is ``float_scale`` (a filer that is wrong two years
    running, Corteva in billions, is still caught by the year before). Then
    the ratio (or its inverse, for a low flag) is compared with every
    split ratio of the ticker and with the product of the splits after
    the float date, then with 1000."""
    size = (
        pl.when(pl.col("flag") == "low")
        .then(1 / pl.col("ratio"))
        .otherwise(pl.col("ratio"))
    )
    c = check.with_columns(size.alias("_size"))
    others = check.select(
        "cik",
        pl.col("fy").alias("_fy2"),
        pl.col("public_float").alias("_float2"),
    )
    adjacent = (
        c.filter(pl.col("flag") != "")
        .select("cik", "fy", "float_date", "cap")
        .join(others, on="cik", how="inner")
        .filter(
            (pl.col("_fy2") != pl.col("fy"))
            & ((pl.col("_fy2") - pl.col("fy")).abs() <= ADJACENT_YEARS)
        )
        .with_columns((pl.col("cap") / pl.col("_float2")).alias("_adj"))
        .group_by("cik", "float_date")
        .agg(
            ((pl.col("_adj") >= lo) & (pl.col("_adj") <= hi))
            .any()
            .alias("_float_scale")
        )
    )
    c = c.join(adjacent, on=["cik", "float_date"], how="left").with_columns(
        (
            pl.col("_float_scale").fill_null(False) & (pl.col("_size") >= SCALE_MIN)
        ).alias("_float_scale")
    )
    if splits is not None and splits.height:
        per = (
            c.select("ticker", "float_date", "_size")
            .join(splits.select("ticker", "date", "ratio"), on="ticker", how="inner")
            .group_by("ticker", "float_date")
            .agg(
                _near(pl.col("_size").first(), pl.col("ratio")).any().alias("_one"),
                pl.col("ratio")
                .filter(pl.col("date") > pl.col("float_date"))
                .product()
                .alias("_after"),
                pl.col("_size").first(),
            )
            .with_columns(
                (
                    pl.col("_one")
                    | _near(pl.col("_size"), pl.col("_after")).fill_null(False)
                ).alias("_near_split")
            )
            .select("ticker", "float_date", "_near_split")
        )
        c = c.join(per, on=["ticker", "float_date"], how="left").with_columns(
            pl.col("_near_split").fill_null(False)
        )
    else:
        c = c.with_columns(pl.lit(False).alias("_near_split"))
    return c.with_columns(
        pl.when(pl.col("flag") == "")
        .then(pl.lit(""))
        .when(pl.col("_float_scale"))
        .then(pl.lit("float_scale"))
        .when(pl.col("_near_split"))
        .then(pl.lit("near_split"))
        .when(_near(pl.col("_size"), 1000.0))
        .then(pl.lit("near_1000"))
        .when(pl.col("_size") > 100)
        .then(pl.lit("over_100x"))
        .otherwise(pl.lit("other"))
        .alias("reason")
    ).drop("_size", "_near_split", "_float_scale")


def public_float_summary(
    check: pl.DataFrame, membership: pl.DataFrame, cfg: Config
) -> pl.DataFrame:
    """Per fiscal year from the window's start: member-years (tickers in
    the index at any month-end of that calendar year), how many have a
    float, a ratio, each flag, and each reason. The coverage the plan's
    bar reads (90% of member-years from 2011)."""
    from backtester.universe import members_at

    rows = []
    for fy in range(cfg.start.year, cfg.end.year + 1):
        members: set[str] = set()
        for m in range(1, 13):
            d = date(fy, m, 1) + timedelta(days=32)
            me = date(d.year, d.month, 1) - timedelta(days=1)
            if cfg.start <= me <= cfg.end:
                members |= set(members_at(membership, me))
        g = check.filter((pl.col("fy") == fy) & pl.col("ticker").is_in(list(members)))
        covered = g.select("ticker").unique().height
        row = {
            "fy": fy,
            "member_years": len(members),
            "with_float": covered,
            "pct_covered": round(100 * covered / len(members), 1) if members else None,
            "with_ratio": g.filter(pl.col("ratio").is_not_null())
            .select("ticker")
            .unique()
            .height,
            "low": g.filter(pl.col("flag") == "low").height,
            "high": g.filter(pl.col("flag") == "high").height,
        }
        for r in FLOAT_REASONS:
            row[r] = g.filter(pl.col("reason") == r).height
        row["excluded"] = g.filter(
            (pl.col("flag") != "") & (pl.col("reason") != "float_scale")
        ).height
        rows.append(row)
    return pl.DataFrame(rows)


def load_floats(cfg: Config, num: pl.DataFrame) -> pl.DataFrame:
    """The API's rows (shares.load_float) plus whatever the FSDS carried
    under the ``public_float`` concept, in FLOAT_SCHEMA."""
    from backtester import shares

    api = shares.load_float(cfg)
    fsds = num.filter(
        (pl.col("concept") == "public_float") & pl.col("form").str.starts_with("10-K")
    ).select("cik", "adsh", "ddate", "filed", "form", "value", "fy")
    parts = [f for f in (api, fsds) if f is not None and f.height]
    if not parts:
        return pl.DataFrame(schema=shares.FLOAT_SCHEMA)
    return pl.concat([f.select(list(shares.FLOAT_SCHEMA)) for f in parts])


# --- pipeline entry -----------------------------------------------------


def build_map(cfg: Config, num: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The CIK map and the sector table: (ciks, log), with sectors.parquet
    and data/checks/cik_map.csv written. Called by ``build`` and by
    ``shares.build``, which needs the universe CIKs before the panel
    exists; both must see the same map (recompute check, 2026-09-15)."""
    from backtester import sectors

    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    constituents = pl.read_parquet(cfg.data / "interim" / "sp500_constituents.parquet")
    ciks, cik_log = sectors.cik_map(
        membership, constituents, num, sec_tickers(cfg), sectors.load_overrides(cfg)
    )
    sectors.build(cfg, num, ciks)
    (cfg.data / "checks").mkdir(parents=True, exist_ok=True)
    cik_log.write_csv(cfg.data / "checks" / "cik_map.csv")
    return ciks, cik_log


def build(cfg: Config, reingest: bool = False) -> pl.DataFrame:
    """ingest -> cik map -> monthly as-of panel -> caps; writes the checks."""

    num = load_num(cfg, reingest)
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    ciks, cik_log = build_map(cfg, num)

    monthly = pl.read_parquet(cfg.data / "processed" / "returns_monthly.parquet")
    daily = pl.read_parquet(cfg.data / "interim" / "prices_daily.parquet")
    months = sorted(monthly.get_column("month").unique().to_list())
    from backtester import shares

    cover, splits = shares.load(cfg)
    panel = monthly_panel(cfg, num, ciks, months, cover, shares.load_api(cfg))
    sector_of = (
        pl.read_parquet(cfg.data / "interim" / "sectors.parquet")
        .select("ticker", "sector")
        .unique(subset=["ticker"])
    )
    panel = bank_revenue(panel.join(sector_of, on="ticker", how="left"))
    revenue_derived(panel, membership, cfg).write_csv(
        cfg.data / "checks" / "revenue_derived.csv"
    )

    # Unadjusted month-end close for market cap: shares outstanding are not
    # split-adjusted, and neither should the price be.
    px_raw = monthly.select("month", "ticker", "t").join(
        daily.select("date", "ticker", pl.col("close").alias("px_me_raw")),
        left_on=["t", "ticker"],
        right_on=["date", "ticker"],
        how="left",
    )
    share_overrides = shares.load_overrides(cfg)
    caps = market_caps(panel, px_raw, splits, share_overrides)
    # The dropped list: member-months whose count is out of line with the
    # ticker's neighbouring months (dropped) and member-months that still
    # come out under 1bn (kept, listed): the residual the split factor
    # and the cover count did not explain, mostly reused symbols whose
    # yfinance history is another company's (COL, EP) and names that
    # were small when they left the index.
    from backtester.universe import members_at

    member_rows = pl.concat(
        [
            pl.DataFrame(
                {
                    "month": [m] * len(members_at(membership, m)),
                    "ticker": members_at(membership, m),
                }
            )
            for m in months
        ]
    ).with_columns(pl.col("month").cast(pl.Date))
    member_caps = caps.join(member_rows, on=["month", "ticker"], how="inner")
    implausible = pl.concat(
        [
            member_caps.filter(pl.col("implausible"))
            .group_by("ticker")
            .agg(pl.len().alias("months"), pl.col("cap").median().alias("median_cap"))
            .with_columns(
                pl.lit("count out of line with neighbours; dropped").alias("reason")
            ),
            member_caps.filter(~pl.col("implausible") & (pl.col("cap") < MIN_CAP))
            .group_by("ticker")
            .agg(pl.len().alias("months"), pl.col("cap").median().alias("median_cap"))
            .with_columns(pl.lit("under 1bn; kept").alias("reason")),
        ]
    ).sort("reason", "months", "ticker", descending=[False, True, False])
    caps = caps.filter(~pl.col("implausible")).drop("implausible")

    processed = cfg.data / "processed"
    stamp = pl.lit(num["as_of"][0] if "as_of" in num.columns else "").alias("as_of")
    panel.with_columns(stamp).write_parquet(processed / "fundamentals_monthly.parquet")
    caps.with_columns(stamp).write_parquet(processed / "market_cap.parquet")

    checks = cfg.data / "checks"
    implausible.write_csv(checks / "market_cap_dropped.csv")
    # The public-float cross-check and the exclusion list it feeds
    # (FIX_PLAN_3 H1); the identity check's rows (H2) are read back from
    # its own file so a rebuild composes both.
    from backtester import identity

    lo, hi = float_thresholds(cfg)
    float_check = public_float_check(
        load_floats(cfg, num), ciks, caps, px_raw, lo, hi, splits
    )
    float_check.write_csv(checks / "public_float.csv")
    public_float_summary(float_check, membership, cfg).write_csv(
        checks / "public_float_summary.csv"
    )
    identity.write_exclusions(cfg, float_check, identity.load_identity_flags(cfg))
    tag_coverage(num, ciks, cfg).write_csv(checks / "tag_coverage.csv")
    concept_coverage(panel, membership, cfg, caps).write_csv(
        checks / "fundamentals_coverage.csv"
    )
    amendments(num).write_csv(checks / "sec_amendments_by_year.csv")
    return panel


def bank_revenue(panel: pl.DataFrame) -> pl.DataFrame:
    """Financials with no revenue tag get net interest income plus
    noninterest income, the bank convention (FIX_PLAN F3), for both the
    annual and the TTM columns; ``revenue_source`` says which rows.
    Only the Financials sector: a manufacturer with a missing revenue
    stays missing rather than taking its interest line."""
    if "sector" not in panel.columns:
        return panel
    fin = pl.col("sector") == "Financials"
    out = panel
    for sfx in ("", "_ttm"):
        nii, non = f"net_interest_income{sfx}", f"noninterest_income{sfx}"
        if nii not in out.columns or non not in out.columns:
            continue
        derived = pl.col(nii) + pl.col(non)
        out = out.with_columns(
            (fin & pl.col(f"revenue{sfx}").is_null() & derived.is_not_null()).alias(
                "_use"
            )
        )
        if sfx == "":
            out = out.with_columns(
                pl.when(pl.col("_use"))
                .then(pl.lit("derived_bank"))
                .when(pl.col("revenue").is_not_null())
                .then(pl.lit("tag"))
                .otherwise(pl.lit(None, dtype=pl.Utf8))
                .alias("revenue_source")
            )
        out = out.with_columns(
            pl.when(pl.col("_use"))
            .then(derived)
            .otherwise(pl.col(f"revenue{sfx}"))
            .alias(f"revenue{sfx}")
        ).drop("_use")
    return out


def revenue_derived(
    panel: pl.DataFrame, membership: pl.DataFrame, cfg: Config
) -> pl.DataFrame:
    """Per December month-end: members with revenue from a tag, derived
    for a bank, or missing. The log the plan asks for."""
    from backtester.universe import members_at

    rows = []
    for (m,), g in panel.group_by("month"):
        if not (cfg.start <= m <= cfg.end) or m.month != 12:
            continue
        members = members_at(membership, m)
        g = g.filter(pl.col("ticker").is_in(members))
        src = g["revenue_source"] if "revenue_source" in g.columns else None
        rows.append(
            {
                "month": m,
                "n_members": len(members),
                "revenue_tag": int((src == "tag").sum()) if src is not None else 0,
                "revenue_derived_bank": int((src == "derived_bank").sum())
                if src is not None
                else 0,
                "revenue_missing": int(g["revenue"].is_null().sum()),
                "financials_missing": int(
                    g.filter(pl.col("sector") == "Financials")["revenue"]
                    .is_null()
                    .sum()
                ),
            }
        )
    return pl.DataFrame(rows).sort("month")


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
