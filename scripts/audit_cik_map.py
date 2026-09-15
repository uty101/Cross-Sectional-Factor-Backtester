"""FIX_PLAN F1: why does a member have no total assets in the panel?

    uv run python scripts/audit_cik_map.py [YYYY-MM-DD ...]

For each audit month-end (default 2011-12-31, 2015-12-31, 2022-12-31)
every index member with no ``assets`` value is listed with the CIK the
map assigned, how it was assigned, and the best CIK a name search over
the full filer index (``sec_sub.parquet``, every form) turns up. Each
row is then classified:

    map_wrong       a filer with 10-K/10-Q filings in the window exists
                    under a different (or no) CIK: the map missed it
    foreign_filer   the name's filings in the window are 20-F / 40-F only
    no_xbrl         no filer matches the name at all in the window
    other           the assigned CIK does file 10-K/10-Q in the window
                    and still has no assets value: a tag gap, not a map
                    problem (or the name search is ambiguous)

Writes data/checks/cik_audit_2015.csv (all months, ``month`` column) and
data/checks/cik_audit_summary.csv. The search window is the 18 months
before the month-end, the same staleness limit the panel applies to an
annual value, so "no filing in the window" means "no value could have
been carried" rather than "never filed".
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import polars as pl

from backtester import config
from backtester import fundamentals as fx
from backtester.sectors import normalise_name
from backtester.universe import members_at

DEFAULT_MONTHS = [date(2011, 12, 31), date(2015, 12, 31), date(2022, 12, 31)]
WINDOW_MONTHS = 18
DOMESTIC = ("10-K", "10-Q", "10-KT", "10-QT", "10-K/A", "10-Q/A")
FOREIGN = ("20-F", "40-F", "20-F/A", "40-F/A")
CLASSES = ["map_wrong", "foreign_filer", "no_xbrl", "other"]
# Leading words too common to identify a filer on their own.
GENERIC = {"AMERICAN", "GENERAL", "NATIONAL", "UNITED", "FIRST", "US", "NEW"}


def _filers_in_window(sub: pl.DataFrame, month: date) -> pl.DataFrame:
    """Frame[cik, name, norm, n_domestic, n_foreign] over the window."""
    lo = pl.lit(month).dt.offset_by(f"-{WINDOW_MONTHS}mo")
    w = sub.filter((pl.col("filed") > lo) & (pl.col("filed") <= month))
    return (
        w.group_by("cik")
        .agg(
            pl.col("name").sort_by("filed").last().alias("name"),
            pl.col("form").is_in(DOMESTIC).sum().alias("n_domestic"),
            pl.col("form").is_in(FOREIGN).sum().alias("n_foreign"),
        )
        .with_columns(
            pl.col("name")
            .map_elements(normalise_name, return_dtype=pl.Utf8)
            .alias("norm")
        )
    )


def best_cik(security: str, filers: pl.DataFrame) -> dict:
    """The filer whose name shares the longest leading run of words with
    the Wikipedia name, among those containing its first word; ties go
    to the one with more 10-K/10-Q filings. Returns an empty dict if the
    first word matches nobody."""
    words = normalise_name(security).split()
    if not words:
        return {}
    first = words[0]
    key = first if first not in GENERIC or len(words) == 1 else " ".join(words[:2])
    cand = filers.filter(pl.col("norm").str.contains(rf"\b{key}\b"))
    if cand.height == 0:
        return {}
    best, best_score = None, (-1, -1)
    for r in cand.iter_rows(named=True):
        fw = r["norm"].split()
        run = 0
        for a, b in zip(words, fw, strict=False):
            if a != b:
                break
            run += 1
        score = (run, r["n_domestic"] + r["n_foreign"])
        if score > best_score:
            best, best_score = r, score
    return {
        "best_cik": best["cik"],
        "best_name": best["name"],
        "best_domestic": best["n_domestic"],
        "best_foreign": best["n_foreign"],
        "best_run": best_score[0],
    }


def classify(row: dict) -> str:
    assigned_files = (row.get("assigned_domestic") or 0) > 0
    if assigned_files:
        return "other"
    if row.get("best_cik") is None:
        return "no_xbrl"
    if row["best_domestic"] > 0 and row["best_run"] >= 1:
        return "map_wrong"
    if row["best_foreign"] > 0 and row["best_domestic"] == 0:
        return "foreign_filer"
    return "other"


def audit(
    panel: pl.DataFrame,
    membership: pl.DataFrame,
    cik_log: pl.DataFrame,
    sub: pl.DataFrame,
    months: list[date],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(rows, summary). ``panel`` needs month, ticker, assets; ``cik_log``
    is data/checks/cik_map.csv; ``sub`` the full filer index."""
    log = {r["ticker"]: r for r in cik_log.iter_rows(named=True)}
    rows = []
    for month in months:
        members = members_at(membership, month)
        have = set(
            panel.filter((pl.col("month") == month) & pl.col("assets").is_not_null())
            .get_column("ticker")
            .to_list()
        )
        filers = _filers_in_window(sub, month)
        by_cik = {r["cik"]: r for r in filers.iter_rows(named=True)}
        interval = membership.filter(
            (pl.col("start") <= month)
            & (pl.col("end").is_null() | (pl.col("end") >= month))
        )
        names = {r["ticker"]: r for r in interval.iter_rows(named=True)}
        for t in members:
            if t in have:
                continue
            m = names[t]
            entry = log.get(t, {})
            assigned = entry.get("cik")
            method = entry.get("method") or "none"
            if method.startswith("sec company_tickers"):
                method = "company_tickers"
            elif method.endswith("unmatched"):
                method = "none"
            elif "name" in method:
                method = "name_match"
            a = by_cik.get(assigned, {}) if assigned is not None else {}
            row = {
                "month": month,
                "ticker": t,
                "security": m["security"],
                "removed": m["end"] is not None,
                "assigned_cik": assigned,
                "method": method,
                "assigned_domestic": a.get("n_domestic", 0),
                "assigned_foreign": a.get("n_foreign", 0),
            }
            row.update(best_cik(m["security"], filers))
            row["class"] = classify(row)
            rows.append(row)
    out = pl.DataFrame(
        rows,
        schema={
            "month": pl.Date,
            "ticker": pl.Utf8,
            "security": pl.Utf8,
            "removed": pl.Boolean,
            "assigned_cik": pl.Int64,
            "method": pl.Utf8,
            "assigned_domestic": pl.Int64,
            "assigned_foreign": pl.Int64,
            "best_cik": pl.Int64,
            "best_name": pl.Utf8,
            "best_domestic": pl.Int64,
            "best_foreign": pl.Int64,
            "best_run": pl.Int64,
            "class": pl.Utf8,
        },
    ).sort("month", "class", "ticker")
    counts = out.group_by("month", "class").agg(pl.len().alias("n"))
    grid = pl.DataFrame(
        [{"month": m, "class": c} for m in months for c in CLASSES],
        schema={"month": pl.Date, "class": pl.Utf8},
    )
    summary = (
        grid.join(counts, on=["month", "class"], how="left")
        .with_columns(pl.col("n").fill_null(0).cast(pl.Int64))
        .sort("month", "class")
    )
    return out, summary


def main(argv: list[str]) -> int:
    cfg = config.load()
    months = [date.fromisoformat(a) for a in argv] or DEFAULT_MONTHS
    panel = pl.read_parquet(cfg.data / "processed" / "fundamentals_monthly.parquet")
    membership = pl.read_parquet(cfg.data / "interim" / "membership.parquet")
    cik_log = pl.read_csv(cfg.data / "checks" / "cik_map.csv")
    sub = fx.load_sub(cfg)
    rows, summary = audit(panel, membership, cik_log, sub, months)
    checks = cfg.data / "checks"
    rows.write_csv(checks / "cik_audit_2015.csv")
    summary.write_csv(checks / "cik_audit_summary.csv")
    print(summary.pivot(on="class", index="month", values="n"))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.exit(main(sys.argv[1:]))
