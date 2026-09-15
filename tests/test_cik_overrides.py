"""FIX_PLAN F1b: the hand-written CIK overrides and how the map applies them."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from backtester import sectors
from backtester.universe import members_at, month_ends

REPO = Path(__file__).resolve().parents[1]
OVERRIDES = REPO / "data" / "checks" / "cik_overrides.csv"
SUB = REPO / "data" / "interim" / "sec_sub.parquet"
MEMBERSHIP = REPO / "data" / "interim" / "membership.parquet"
CIK_MAP = REPO / "data" / "checks" / "cik_map.csv"
RENAMES = REPO / "data" / "checks" / "ticker_renames.csv"


def _overrides() -> pl.DataFrame:
    return pl.read_csv(OVERRIDES, schema_overrides=sectors.OVERRIDE_SCHEMA)


# --- the file -----------------------------------------------------------


def test_override_rows_carry_edgar_evidence_and_do_not_overlap() -> None:
    o = _overrides()
    assert o.columns == list(sectors.OVERRIDE_SCHEMA)
    assert o["cik"].is_not_null().all() and (o["cik"] > 0).all()
    for r in o.iter_rows(named=True):
        assert r["source_url"].startswith("https://www.sec.gov/"), r["ticker"]
        assert f"CIK={r['cik']:010d}" in r["source_url"], r["ticker"]
        assert r["note"], r["ticker"]
        if r["start"] and r["end"]:
            assert r["start"] <= r["end"], r["ticker"]
    # Two ranges for one ticker never cover the same month: cik_at raises.
    months = month_ends(date(2009, 1, 31), date(2026, 12, 31))
    sectors.cik_at(o.select("ticker", "cik", "start", "end"), months)


@pytest.mark.skipif(not SUB.exists(), reason="needs data/interim/sec_sub.parquet")
def test_every_override_cik_has_filings_in_the_sec_index() -> None:
    o = _overrides()
    sub = pl.read_parquet(SUB).filter(pl.col("form").is_in(["10-K", "10-Q"]))
    filed = set(sub["cik"].unique().to_list())
    missing = [r for r in o.iter_rows(named=True) if r["cik"] not in filed]
    assert not missing, [(r["ticker"], r["cik"]) for r in missing]


@pytest.mark.skipif(
    not (MEMBERSHIP.exists() and CIK_MAP.exists()),
    reason="needs the built membership and cik_map.csv",
)
def test_no_cik_is_two_members_at_once_unless_share_classes() -> None:
    """The plan's rule: no two tickers share a CIK unless one is a
    share-class alias. Checked month by month on the resolved map, so a
    rename (AA -> ARNC, KFT -> MDLZ) or a symbol handed to an acquirer
    (CB) is fine as long as the two tickers are never members together
    on the same CIK. Share classes are the tickers whose security names
    share a stem (Alphabet Inc. (Class A) / (Class C), Comcast / Comcast
    Series K) or that ticker_renames.csv pairs."""
    log = pl.read_csv(CIK_MAP, schema_overrides={"start": pl.Date, "end": pl.Date})
    ciks = log.filter(pl.col("cik").is_not_null()).select(
        "ticker", "cik", "start", "end"
    )
    membership = pl.read_parquet(MEMBERSHIP)
    names = dict(zip(membership["ticker"], membership["security"], strict=True))
    renames = pl.read_csv(RENAMES)
    paired = set(zip(renames["old_ticker"], renames["new_ticker"], strict=True))
    months = month_ends(date(2010, 1, 31), date(2026, 8, 31))
    at = sectors.cik_at(ciks, months)

    def stem(t: str) -> str:
        return names.get(t, t).split(" (")[0].split(" Series")[0].split(" Class")[0]

    def alias(a: str, b: str) -> bool:
        return (
            (a, b) in paired
            or (b, a) in paired
            or stem(a) == stem(b)
            or stem(a).startswith(stem(b))
            or stem(b).startswith(stem(a))
        )

    clashes = []
    for m in months:
        members = set(members_at(membership, m))
        here = at.filter((pl.col("month") == m) & pl.col("ticker").is_in(members))
        dup = (
            here.group_by("cik")
            .agg(pl.col("ticker").sort().alias("t"))
            .filter(pl.col("t").list.len() > 1)
        )
        for ts in dup["t"].to_list():
            for i, a in enumerate(ts):
                for b in ts[i + 1 :]:
                    if not alias(a, b):
                        clashes.append((m, a, b))
    assert not clashes, sorted(set((a, b) for _, a, b in clashes))


# --- how the map applies them ------------------------------------------


def _frames():
    membership = pl.DataFrame(
        {
            "ticker": ["DIS", "OLDCO", "NAMED"],
            "security": ["Walt Disney", "Old Company", "Named Widgets"],
            "end": [None, date(2015, 1, 1), date(2015, 1, 1)],
        }
    )
    constituents = pl.DataFrame({"ticker": ["DIS"], "cik": ["0001744489"]})
    num = pl.DataFrame(
        {
            "cik": [1744489, 1001039, 555, 777],
            "name": ["WALT DISNEY CO", "WALT DISNEY CO/", "OLD CO", "NAMED WIDGETS"],
            "filed": [date(2020, 1, 1)] * 4,
        }
    )
    overrides = pl.DataFrame(
        {
            "ticker": ["DIS", "OLDCO"],
            "cik": [1001039, 555],
            "start": [None, None],
            "end": [date(2019, 3, 31), None],
            "source_url": ["https://www.sec.gov/x", "https://www.sec.gov/y"],
            "note": ["pre-2019 registrant", "hand-placed"],
        },
        schema=sectors.OVERRIDE_SCHEMA,
    )
    return membership, constituents, num, overrides


def test_overrides_apply_after_the_sec_map_and_instead_of_name_matching() -> None:
    membership, constituents, num, overrides = _frames()
    sec = {"DIS": 1744489}
    ciks, log = sectors.cik_map(membership, constituents, num, sec, overrides)
    methods = {(r["ticker"], r["cik"]): r["method"] for r in log.iter_rows(named=True)}
    assert methods[("DIS", 1744489)] == "sec company_tickers"
    assert methods[("DIS", 1001039)] == "override"
    assert methods[("OLDCO", 555)] == "override"
    assert methods[("NAMED", 777)] == "name exact"  # no override: still matched
    # The ranged row wins inside its range; the SEC CIK applies outside.
    at = sectors.cik_at(ciks, [date(2019, 3, 31), date(2019, 4, 30)])
    got = {(r["month"], r["ticker"]): r["cik"] for r in at.iter_rows(named=True)}
    assert got[(date(2019, 3, 31), "DIS")] == 1001039
    assert got[(date(2019, 4, 30), "DIS")] == 1744489
    assert got[(date(2019, 3, 31), "OLDCO")] == 555


def test_cik_at_refuses_two_ranges_on_one_month() -> None:
    ciks = pl.DataFrame(
        {
            "ticker": ["X", "X"],
            "cik": [1, 2],
            "start": [None, date(2015, 1, 31)],
            "end": [date(2015, 6, 30), None],
        },
        schema={
            "ticker": pl.Utf8,
            "cik": pl.Int64,
            "start": pl.Date,
            "end": pl.Date,
        },
    )
    with pytest.raises(ValueError, match="X has 2 CIK ranges"):
        sectors.cik_at(ciks, [date(2015, 3, 31)])
