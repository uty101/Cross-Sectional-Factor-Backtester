"""10-K text as a point-in-time signal, from EDGAR and nothing else.

    filings      the 10-K index from sub.txt of the FSDS zips already on
                 disk: adsh, cik, period, filed, accepted. The SEC stamps
                 the filing date; this code never assigns one
    fetch        the primary document of every original 10-K of every
                 universe CIK, one gzip per filing under data/raw/edgar,
                 never overwritten, every one in the manifest (invariant 7)
    to_words     HTML or plain text -> lower-case alphabetic words
    similarity   cosine on term counts and Jaccard on word sets between a
                 filing and the prior 10-K of the same CIK (Cohen, Malloy
                 and Nguyen 2020, "Lazy Prices")
    build        -> data/interim/text_similarity.parquet and the checks
    signal       doc_similarity: Frame[month, ticker, value], as-of filed

Three choices, each made because the alternative leaks:

- Source. EDGAR, not company websites. The SEC stamps the acceptance
  time, keeps an amendment as a separate filing next to the original, and
  keeps the filings of names that were acquired or delisted. An investor
  relations page has none of those: a restated PDF replaces the original
  in place, and a removed member's site is gone. Earnings-call
  transcripts are not filed and have no point-in-time archive without a
  vendor, so they are not used; the 8-K earnings release is filed and is
  the next thing to add.
- Timestamp. A document is usable at month-end t only if filed on or
  before t - asof_buffer_days, through the same ``asof_join`` as every
  fundamental (invariant 1). Only original 10-K and 10-KT filings are
  compared; for a fiscal year filed twice the first filing wins
  (invariant 2).
- Scorer. Term-count cosine and word-set Jaccard, pure functions of the
  two documents. No language model scores a filing: a model trained after
  2015 knows what happened to the company after 2015, and that lookahead
  passes every other test in this repo (invariant 10).

The whole primary document is compared, as the paper does. Pulling out
Item 1A and Item 7 needs a parser that fails quietly on a share of
filings, and the check table for that is not built. Some 10-Ks are a
wrapper with the annual report in Exhibit 13; those come out short and
are dropped by ``min_words`` and listed in ``text_short_documents.csv``.
"""

from __future__ import annotations

import gzip
import html
import json
import math
import re
import time
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config
from backtester.fundamentals import SEC_USER_AGENT, asof_join

SUBMISSIONS = "https://data.sec.gov/submissions/"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/"
FORMS = ("10-K", "10-KT")  # originals only; amendments never enter the pairs
MAX_AGE_MONTHS = 18  # a 10-K is stale once the next one is overdue
MAX_PAIR_GAP_MONTHS = 18  # do not compare across a missed year
REQUEST_INTERVAL = 0.12  # seconds; the SEC allows 10 requests a second

FILINGS_SCHEMA = {
    "adsh": pl.Utf8,
    "cik": pl.Int64,
    "form": pl.Utf8,
    "period": pl.Date,
    "fy": pl.Int32,
    "filed": pl.Date,
    "accepted": pl.Datetime,
    "instance": pl.Utf8,
}
SIMILARITY_SCHEMA = {
    "cik": pl.Int64,
    "adsh": pl.Utf8,
    "prev_adsh": pl.Utf8,
    "period": pl.Date,
    "prev_period": pl.Date,
    "filed": pl.Date,
    "n_words": pl.Int64,
    "prev_n_words": pl.Int64,
    "cosine": pl.Float64,
    "jaccard": pl.Float64,
}

# A fixed list rather than a library's: the scorer must give the same
# number on every machine, forever.
STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be
    because been before being below between both but by can could did do does
    doing down during each few for from further had has have having he her here
    hers herself him himself his how i if in into is it its itself just may me
    might more most must my myself no nor not of off on once only or other our
    ours ourselves out over own same shall she should so some such than that the
    their theirs them themselves then there these they this those through to too
    under until up very was we were what when where which while who whom why will
    with would you your yours yourself yourselves""".split()
)
WORD = re.compile(r"[a-z][a-z'-]*[a-z]|[a-z]")
TAG = re.compile(r"<[^>]+>")
DROP_BLOCKS = re.compile(
    r"<(script|style|ix:header|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
HTML_HINT = re.compile(r"<\s*(html|body|div|p|table|font)\b", re.IGNORECASE)


# --- the filing index ---------------------------------------------------


def filings(cfg: Config) -> pl.DataFrame:
    """Every original 10-K and 10-KT in the FSDS zips on disk, one row per
    filing, with the SEC's own filing date and acceptance time."""
    frames = []
    for z in sorted((cfg.data / "raw" / "sec").glob("*.zip")):
        with zipfile.ZipFile(z) as zf:
            sub = zf.read("sub.txt")
        frames.append(_parse_sub(sub))
    if not frames:
        return pl.DataFrame(schema=FILINGS_SCHEMA)
    return pl.concat(frames).unique(subset=["adsh"]).sort("cik", "period", "filed")


def _parse_sub(sub: bytes) -> pl.DataFrame:
    df = pl.read_csv(
        sub,
        separator="\t",
        quote_char=None,
        infer_schema_length=0,
        columns=list(FILINGS_SCHEMA),
    )
    return (
        df.filter(pl.col("form").is_in(FORMS))
        .select(
            "adsh",
            pl.col("cik").cast(pl.Int64),
            "form",
            pl.col("period").str.strptime(pl.Date, "%Y%m%d", strict=False),
            pl.col("fy").cast(pl.Int32, strict=False),
            pl.col("filed").str.strptime(pl.Date, "%Y%m%d", strict=False),
            pl.col("accepted")
            .str.slice(0, 19)
            .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False),
            "instance",
        )
        .drop_nulls(["cik", "period", "filed"])
    )


def first_filed(index: pl.DataFrame) -> pl.DataFrame:
    """One original filing per (cik, period): the earliest (invariant 2)."""
    return (
        index.filter(pl.col("form").is_in(FORMS))
        .sort("filed", "accepted", "adsh")
        .unique(subset=["cik", "period"], keep="first")
        .sort("cik", "period")
    )


# --- fetch --------------------------------------------------------------


def doc_path(cik: int, adsh: str, name: str) -> str:
    """Raw-store path of one primary document, gzipped."""
    ext = Path(name).suffix.lower() or ".htm"
    return f"edgar/10k/{cik}/{adsh}{ext}.gz"


def doc_url(cik: int, adsh: str, name: str) -> str:
    return f"{ARCHIVES}{cik}/{adsh.replace('-', '')}/{name}"


def primary_documents(submissions: list[dict]) -> dict[str, str]:
    """adsh -> primary document name from the submissions API pages.

    The main page nests the arrays under ``filings.recent``; the overflow
    pages it names under ``filings.files`` carry the same arrays at the
    top level.
    """
    out: dict[str, str] = {}
    for page in submissions:
        recent = page.get("filings", {}).get("recent", page)
        for adsh, doc in zip(
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            strict=True,
        ):
            if doc:
                out[adsh] = doc
    return out


def _get(session, url: str, timeout: int = 120):
    time.sleep(REQUEST_INTERVAL)
    r = session.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout)
    return r


def _submissions(session, root: Path, cik: int, stamp: str) -> list[dict]:
    """The submissions JSON for one CIK, and its overflow pages, stored
    date-stamped because the file grows with every new filing."""
    pages = []
    name = f"CIK{cik:010d}.json"
    rel = f"edgar/submissions/{stamp}/{name}"
    if not (root / rel).exists():
        r = _get(session, SUBMISSIONS + name)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        raw.store_raw(root, rel, r.content, SUBMISSIONS + name)
    main = json.loads((root / rel).read_bytes())
    pages.append(main)
    for extra in main.get("filings", {}).get("files", []):
        rel_x = f"edgar/submissions/{stamp}/{extra['name']}"
        if not (root / rel_x).exists():
            r = _get(session, SUBMISSIONS + extra["name"])
            r.raise_for_status()
            raw.store_raw(root, rel_x, r.content, SUBMISSIONS + extra["name"])
        pages.append(json.loads((root / rel_x).read_bytes()))
    return pages


def fetch(cfg: Config, as_of: date, limit: int | None = None) -> list[Path]:
    """The primary document of every original 10-K of every universe CIK.

    Resumable: a document already on disk is never requested again. The
    document name comes from the submissions API (one page per CIK, plus
    overflow pages for heavy filers), stored alongside. Filings the API
    does not list are written to ``data/checks/text_fetch_missing.csv``.
    """
    import requests

    root = cfg.data / "raw"
    ciks = pl.read_parquet(cfg.data / "interim" / "sectors.parquet").select("cik")
    index = first_filed(filings(cfg)).join(ciks.unique(), on="cik", how="inner")
    stamp = as_of.isoformat()
    session = requests.Session()
    stored: list[Path] = []
    missing: list[dict] = []
    n = 0
    for (cik,), group in index.group_by("cik", maintain_order=True):
        rows = group.to_dicts()
        docs = None  # the submissions page is requested only when a document is missing
        for r in rows:
            if limit is not None and n >= limit:
                return stored
            existing = _existing(root, cik, r["adsh"])
            if existing is not None:
                stored.append(existing)
                continue
            if docs is None:
                docs = primary_documents(_submissions(session, root, cik, stamp))
            name = docs.get(r["adsh"])
            if not name:
                missing.append({**r, "reason": "not in submissions API"})
                continue
            url = doc_url(cik, r["adsh"], name)
            resp = _get(session, url)
            if resp.status_code != 200:
                missing.append({**r, "reason": f"HTTP {resp.status_code}"})
                continue
            body = gzip.compress(resp.content, mtime=0)
            rel = doc_path(cik, r["adsh"], name)
            stored.append(raw.store_raw(root, rel, body, url))
            n += 1
            if n % 100 == 0:
                print(f"fetched {n} documents ({datetime.now():%H:%M:%S})")
    if missing:
        checks = cfg.data / "checks"
        checks.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(missing).select(
            "adsh", "cik", "form", "period", "filed", "reason"
        ).write_csv(checks / "text_fetch_missing.csv")
    return stored


def _existing(root: Path, cik: int, adsh: str) -> Path | None:
    matches = list((root / "edgar" / "10k" / str(cik)).glob(f"{adsh}.*.gz"))
    return matches[0] if matches else None


# --- text ---------------------------------------------------------------


def to_words(content: bytes) -> list[str]:
    """Lower-case alphabetic words of a filing, markup and stop words removed.

    Inline-XBRL filings carry a hidden ``ix:header`` block of tagging
    metadata; it is dropped along with scripts and styles, so that a
    change in the taxonomy version does not read as a change in the text.
    Numbers are not words: a restated figure is not a rewritten sentence.
    """
    text = content.decode("utf-8", errors="replace")
    if HTML_HINT.search(text[:20000]) or "<" in text[:2000]:
        text = DROP_BLOCKS.sub(" ", text)
        text = TAG.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ").lower()
    return [w for w in WORD.findall(text) if w not in STOPWORDS]


def similarity(a: Counter, b: Counter) -> tuple[float, float]:
    """(cosine on term counts, Jaccard on word sets) of two documents.

    A pure function of its two arguments and nothing else: no corpus
    statistics, no model, no clock. Called with an empty document it
    returns (0, 0).
    """
    if not a or not b:
        return 0.0, 0.0
    dot = sum(c * b[w] for w, c in a.items() if w in b)
    norm_a = sum(c * c for c in a.values())
    norm_b = sum(c * c for c in b.values())
    cos = dot / math.sqrt(norm_a * norm_b)
    common = len(a.keys() & b.keys())
    jac = common / (len(a) + len(b) - common)
    return cos, jac


def pairs(index: pl.DataFrame) -> pl.DataFrame:
    """Each first-filed original with the previous one of the same CIK,
    provided the periods are at most MAX_PAIR_GAP_MONTHS apart."""
    ff = first_filed(index).sort("cik", "period")
    out = (
        ff.with_columns(
            pl.col("adsh").shift(1).over("cik").alias("prev_adsh"),
            pl.col("period").shift(1).over("cik").alias("prev_period"),
        )
        .filter(pl.col("prev_adsh").is_not_null())
        .filter(
            pl.col("prev_period")
            >= pl.col("period").dt.offset_by(f"-{MAX_PAIR_GAP_MONTHS}mo")
        )
    )
    return out.select("cik", "adsh", "prev_adsh", "period", "prev_period", "filed")


def _count(path: Path) -> tuple[str, Counter]:
    words = to_words(gzip.decompress(path.read_bytes()))
    return path.name.split(".")[0], Counter(words)


def word_counts(paths: list[Path], workers: int | None = None) -> dict[str, Counter]:
    """adsh -> term counts, one process per core."""
    if len(paths) < 50:
        return dict(_count(p) for p in paths)
    with ProcessPoolExecutor(workers) as pool:
        return dict(pool.map(_count, paths, chunksize=8))


def score(
    pairs_df: pl.DataFrame, counts: dict[str, Counter], min_words: int
) -> pl.DataFrame:
    """One row per pair: word counts and both similarities. A document
    shorter than ``min_words`` is treated as missing, and so is its pair."""
    rows = []
    for r in pairs_df.to_dicts():
        a, b = counts.get(r["adsh"]), counts.get(r["prev_adsh"])
        if a is None or b is None:
            continue
        na, nb = sum(a.values()), sum(b.values())
        if na < min_words or nb < min_words:
            continue
        cos, jac = similarity(a, b)
        rows.append(
            {**r, "n_words": na, "prev_n_words": nb, "cosine": cos, "jaccard": jac}
        )
    return pl.DataFrame(rows, schema=SIMILARITY_SCHEMA)


# --- the signal ---------------------------------------------------------


def signal(
    cfg: Config,
    sim: pl.DataFrame,
    ciks: pl.DataFrame,
    months: list[date],
    measure: str | None = None,
) -> pl.DataFrame:
    """doc_similarity as Frame[month, ticker, value].

    The value at month-end t is the similarity of the latest 10-K filed on
    or before t - asof_buffer_days to the one before it; high similarity
    is the long leg. A value is carried for at most MAX_AGE_MONTHS after
    its period end.
    """
    measure = measure or cfg.text_similarity
    base = pl.DataFrame({"month": months}).join(
        ciks.select("ticker", "cik"), how="cross"
    )
    vals = sim.select("cik", pl.col("period").alias("ddate"), "filed", measure)
    j = asof_join(base, vals, cfg.asof_buffer_days, value_col=measure)
    j = j.filter(
        pl.col("value").is_not_null()
        & (pl.col("period_end") >= pl.col("month").dt.offset_by(f"-{MAX_AGE_MONTHS}mo"))
    )
    return (
        base.join(j, on=["month", "cik"], how="inner")
        .select("month", "ticker", "value")
        .sort("month", "ticker")
    )


# --- pipeline entry -----------------------------------------------------


def build(cfg: Config) -> pl.DataFrame:
    """Documents on disk -> text_similarity.parquet, with the checks."""
    root = cfg.data / "raw"
    sectors = pl.read_parquet(cfg.data / "interim" / "sectors.parquet")
    ciks = sectors.select("cik").unique()
    index = filings(cfg).join(ciks, on="cik", how="inner")
    ff = first_filed(index)
    paths = [p for p in (root / "edgar" / "10k").glob("*/*.gz")]
    on_disk = {p.name.split(".")[0] for p in paths}
    have = ff.filter(pl.col("adsh").is_in(list(on_disk)))
    wanted = set(have["adsh"])
    counts = word_counts([p for p in paths if p.name.split(".")[0] in wanted])
    pr = pairs(have)
    sim = score(pr, counts, cfg.text_min_words)

    interim = cfg.data / "interim"
    stamp = pl.lit(date.today().isoformat()).alias("as_of")
    sim.with_columns(stamp).write_parquet(interim / "text_similarity.parquet")

    checks = cfg.data / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    lengths = pl.DataFrame(
        {"adsh": list(counts), "n_words": [sum(c.values()) for c in counts.values()]},
        schema={"adsh": pl.Utf8, "n_words": pl.Int64},
    )
    coverage(ff, lengths, sim, cfg).write_csv(checks / "text_coverage.csv")
    (
        ff.join(lengths, on="adsh", how="inner")
        .filter(pl.col("n_words") < cfg.text_min_words)
        .select("adsh", "cik", "form", "period", "filed", "n_words")
        .sort("n_words")
        .write_csv(checks / "text_short_documents.csv")
    )
    return sim


def coverage(
    ff: pl.DataFrame, lengths: pl.DataFrame, sim: pl.DataFrame, cfg: Config
) -> pl.DataFrame:
    """Per filing year: universe 10-Ks in the index, fetched, long enough,
    and paired with a prior filing; the median document length."""
    year = pl.col("filed").dt.year().alias("year")
    idx = ff.with_columns(year).group_by("year").agg(pl.len().alias("filings"))
    fetched = (
        ff.join(lengths, on="adsh", how="inner")
        .with_columns(year)
        .group_by("year")
        .agg(
            pl.len().alias("fetched"),
            (pl.col("n_words") >= cfg.text_min_words).sum().alias("long_enough"),
            pl.col("n_words").median().alias("median_words"),
        )
    )
    paired = sim.with_columns(year).group_by("year").agg(pl.len().alias("paired"))
    return (
        idx.join(fetched, on="year", how="left")
        .join(paired, on="year", how="left")
        .fill_null(0)
        .sort("year")
    )
