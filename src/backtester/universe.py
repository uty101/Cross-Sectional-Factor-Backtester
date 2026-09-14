"""Month-by-month S&P 500 membership, reconstructed from Wikipedia.

Two pages are used. The constituents list gives today's members and the
date each was added; the historical-components page gives the changes
table (effective date, ticker added, ticker removed, reason). Membership
is rebuilt by starting from today's members and walking the changes table
backwards: an addition on date *d* closes the interval's start at *d*, a
removal on *d* opens a new interval that ends the day before *d*.

A third, independent file (fja05680/sp500 on GitHub, daily snapshots since
1996) is a cross-check, not a source: it settles the handful of starts
Wikipedia cannot corroborate internally, and every month-end where the
two disagree is written down.

Membership is stored as closed intervals per ticker. A ticker is in the
cross-section at *t* only if *t* falls inside one of its intervals
(invariant 3). Tickers are the *current* ticker for current members and
the ticker at removal for former ones; renames the walk detects are kept
in ``ticker_renames`` for the price layer.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from backtester import raw
from backtester.config import Config
from backtester.tables import parse_table

CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
CROSSCHECK_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)

# Sentinel for "member since before the record begins". Any start earlier
# than the changes table's first row means the same thing.
UNKNOWN_START = date(1900, 1, 1)

# The brief (section 10) says the Wikipedia history has errors before 2010.
# In practice the failure is the other way round: the changes table is thin
# before 2010, and the constituents table's "Date added" is a fair substitute
# there; from 2010 the changes table is nearly complete, so a "Date added"
# with no matching changes row is usually a corporate-event date on a
# long-standing member, not an index addition. The cut is where date_added
# stops being trusted on its own.
CHANGES_RELIABLE_FROM = date(2010, 1, 1)
RENAME_TOLERANCE = timedelta(days=7)
MIN_ALIAS_MONTHS = 3

_MONTH_DATE = re.compile(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$")
_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}")
_SUFFIX = re.compile(r"-\d{6}$")

MEMBERSHIP_SCHEMA = {
    "ticker": pl.Utf8,
    "security": pl.Utf8,
    "start": pl.Date,
    "end": pl.Date,
    "start_source": pl.Utf8,
    "end_source": pl.Utf8,
}
INCONSISTENCY_SCHEMA = {
    "row": pl.Int64,
    "date": pl.Date,
    "ticker": pl.Utf8,
    "event": pl.Utf8,
    "problem": pl.Utf8,
}
RENAME_SCHEMA = {
    "old_ticker": pl.Utf8,
    "new_ticker": pl.Utf8,
    "date": pl.Date,
    "row": pl.Int64,
    "security_then": pl.Utf8,
    "security_now": pl.Utf8,
}


# --- parse --------------------------------------------------------------


def parse_date(text: str) -> date | None:
    """``"August 18, 2026"`` or ``"1957-03-04"`` (with any trailing note) -> date."""
    text = text.strip()
    if m := _ISO_DATE.search(text):
        return date.fromisoformat(m.group(1))
    if _MONTH_DATE.match(text):
        return datetime.strptime(text, "%B %d, %Y").date()
    return None


def clean_ticker(text: str | None) -> str | None:
    """The leading ticker token of a cell; Wikipedia leaves stray ``|`` in some."""
    if not text:
        return None
    m = _TICKER.match(text.strip())
    return m.group(0) if m else None


def parse_constituents(html: str) -> pl.DataFrame:
    """Today's members.

    Columns: ticker, security, gics_sector, gics_sub_industry, date_added, cik.
    """
    rows = parse_table(html, "constituents")
    header = [h.lower() for h in rows[0]]
    idx = {
        name: header.index(name)
        for name in (
            "symbol",
            "security",
            "gics sector",
            "gics sub-industry",
            "date added",
            "cik",
        )
    }
    out = []
    for r in rows[1:]:
        if len(r) < len(header):
            continue
        out.append(
            {
                "ticker": r[idx["symbol"]].strip(),
                "security": r[idx["security"]].strip(),
                "gics_sector": r[idx["gics sector"]].strip(),
                "gics_sub_industry": r[idx["gics sub-industry"]].strip(),
                "date_added": parse_date(r[idx["date added"]]),
                "cik": r[idx["cik"]].strip().zfill(10) or None,
            }
        )
    return pl.DataFrame(
        out,
        schema={
            "ticker": pl.Utf8,
            "security": pl.Utf8,
            "gics_sector": pl.Utf8,
            "gics_sub_industry": pl.Utf8,
            "date_added": pl.Date,
            "cik": pl.Utf8,
        },
    )


def parse_changes(html: str) -> pl.DataFrame:
    """The changes table.

    Columns: row, date, added, added_security, removed, removed_security, reason.
    ``row`` is the 0-based position in the source table, so an interval can
    be traced back to the line it came from. Empty tickers are null.
    """
    rows = parse_table(html, "changes")
    out = []
    for i, r in enumerate(rows):
        if len(r) < 6:
            continue
        d = parse_date(r[0])
        if d is None:
            continue  # header rows
        out.append(
            {
                "row": i,
                "date": d,
                "added": clean_ticker(r[1]),
                "added_security": r[2].strip() or None,
                "removed": clean_ticker(r[3]),
                "removed_security": r[4].strip() or None,
                "reason": r[5].strip() or None,
            }
        )
    return pl.DataFrame(
        out,
        schema={
            "row": pl.Int64,
            "date": pl.Date,
            "added": pl.Utf8,
            "added_security": pl.Utf8,
            "removed": pl.Utf8,
            "removed_security": pl.Utf8,
            "reason": pl.Utf8,
        },
    ).sort("date", "row", descending=[True, False])


def parse_crosscheck(text: str) -> dict[date, frozenset[str]]:
    """fja05680 daily snapshots: date -> tickers. ``XYZ-201503`` suffixes dropped."""
    out: dict[date, frozenset[str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        tickers = frozenset(
            _SUFFIX.sub("", t).strip().replace("-", ".")
            for t in row["tickers"].split(",")
        )
        out[date.fromisoformat(row["date"])] = tickers
    return out


def crosscheck_at(snaps: dict[date, frozenset[str]], d: date) -> frozenset[str]:
    keys = [k for k in snaps if k <= d]
    return snaps[max(keys)] if keys else frozenset()


# --- build --------------------------------------------------------------


@dataclass
class _Interval:
    ticker: str
    security: str | None
    start: date | None
    end: date | None  # None = still a member
    start_source: str | None
    end_source: str
    date_added: date | None = None


@dataclass
class Membership:
    intervals: pl.DataFrame
    inconsistencies: pl.DataFrame
    renames: pl.DataFrame


def build_membership(
    constituents: pl.DataFrame, changes: pl.DataFrame, as_of: date
) -> Membership:
    """Walk the changes backwards from today's members.

    intervals: ticker, security, start, end, start_source, end_source, as_of
    inconsistencies: rows the two tables cannot both be right about
    renames: additions matched to a current member by date_added
    """
    active: dict[str, _Interval] = {}
    done: list[_Interval] = []
    problems: list[dict] = []
    renames: list[dict] = []
    unmatched_adds: list[dict] = []

    for c in constituents.iter_rows(named=True):
        active[c["ticker"]] = _Interval(
            c["ticker"],
            c["security"],
            None,
            None,
            None,
            "constituents",
            c["date_added"],
        )

    # Newest first, one date at a time. Going backwards, the additions on a
    # date close the start of an open interval; the removals then open the
    # interval that was live before that date. Additions must go first so
    # that a same-day swap of a ticker for itself (21st Century Fox -> Fox
    # Corporation, both FOX/FOXA) closes the later interval before opening
    # the earlier one, rather than producing an empty one.
    ordered = changes.sort("date", "row", descending=[True, False])
    for (d,), day in ordered.group_by("date", maintain_order=True):
        rows = list(day.iter_rows(named=True))
        for ch in rows:
            if not (t := ch["added"]):
                continue
            if t in active:
                iv = active.pop(t)
                iv.start, iv.start_source = d, f"changes:{ch['row']}"
                done.append(iv)
            else:
                unmatched_adds.append(ch)
        for ch in rows:
            if not (t := ch["removed"]):
                continue
            row = ch["row"]
            if t in active:
                problems.append(
                    {
                        "row": row,
                        "date": d,
                        "ticker": t,
                        "event": "removed",
                        "problem": (
                            "removed while still a member going backwards: "
                            "a later addition row is missing"
                        ),
                    }
                )
                # Trust the removal: close the open interval here, open an earlier one.
                iv = active.pop(t)
                iv.start, iv.start_source = d, f"changes:{row}:inferred"
                done.append(iv)
            active[t] = _Interval(
                t,
                ch["removed_security"],
                None,
                d - timedelta(days=1),
                None,
                f"changes:{row}",
            )

    # An addition the walk could not place is usually a ticker that has since
    # been renamed: FB was added on 2013-12-23 and the constituents table says
    # META, date added 2013-12-23. Match on that date, within a few days, and
    # only inside the reliable window: before it a date coincidence is as
    # likely as a rename (CCR 1997-06-17 vs EFX 1997-06-19).
    for ch in unmatched_adds:
        d, t = ch["date"], ch["added"]
        candidates = [
            iv
            for iv in active.values()
            if d >= CHANGES_RELIABLE_FROM
            and iv.end is None
            and iv.date_added is not None
            and abs(iv.date_added - d) <= RENAME_TOLERANCE
        ]
        if len(candidates) == 1:
            iv = active.pop(candidates[0].ticker)
            iv.start, iv.start_source = d, f"changes:{ch['row']}:renamed_from:{t}"
            done.append(iv)
            renames.append(
                {
                    "old_ticker": t,
                    "new_ticker": iv.ticker,
                    "date": d,
                    "row": ch["row"],
                    "security_then": ch["added_security"],
                    "security_now": iv.security,
                }
            )
        else:
            problems.append(
                {
                    "row": ch["row"],
                    "date": d,
                    "ticker": t,
                    "event": "added",
                    "problem": (
                        "added but never removed and not a current member: "
                        f"{len(candidates)} rename candidates by date_added"
                    ),
                }
            )

    for iv in active.values():
        if iv.end is not None or iv.date_added is None:
            iv.start, iv.start_source = UNKNOWN_START, "unknown"
        elif iv.date_added < CHANGES_RELIABLE_FROM:
            iv.start, iv.start_source = iv.date_added, "constituents:date_added"
        else:
            iv.start, iv.start_source = iv.date_added, "unverified:date_added"
        done.append(iv)

    intervals = (
        pl.DataFrame(
            [
                {
                    "ticker": iv.ticker,
                    "security": iv.security,
                    "start": iv.start,
                    "end": iv.end,
                    "start_source": iv.start_source,
                    "end_source": iv.end_source,
                }
                for iv in done
            ],
            schema=MEMBERSHIP_SCHEMA,
        )
        .with_columns(pl.lit(as_of).alias("as_of"))
        .sort("ticker", "start")
    )
    return Membership(
        intervals,
        pl.DataFrame(problems, schema=INCONSISTENCY_SCHEMA).sort(
            "date", descending=True
        ),
        pl.DataFrame(renames, schema=RENAME_SCHEMA).sort("date", descending=True),
    )


# --- cross-check --------------------------------------------------------


def adjudicate(
    m: Membership, snaps: dict[date, frozenset[str]]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Settle the ``unverified:date_added`` starts with the cross-check.

    A current member whose Wikipedia date_added falls inside the reliable
    window with no changes row to back it is either a genuinely missing row
    (BRK.B, 2010-02-16) or a corporate-event date on a long-standing member
    (SRE "2017-03-17"). The cross-check tells them apart: if it has the
    ticker in the index at the day before date_added, the start is moved
    back to the cross-check's first sighting. Every decision is returned so
    it can be committed.
    """
    first_seen: dict[str, date] = {}
    for d in sorted(snaps):
        for t in snaps[d]:
            first_seen.setdefault(t, d)
    earliest = min(snaps)

    decisions = []
    rows = []
    for r in m.intervals.iter_rows(named=True):
        if r["start_source"] != "unverified:date_added":
            rows.append(r)
            continue
        t = r["ticker"].replace("-", ".")
        if t in crosscheck_at(snaps, r["start"] - timedelta(days=1)):
            fs = first_seen[t]
            new_start = UNKNOWN_START if fs == earliest else fs
            rows.append(
                {**r, "start": new_start, "start_source": "crosscheck:first_seen"}
            )
            verdict = "date_added rejected: cross-check has the ticker before it"
        else:
            rows.append({**r, "start_source": "date_added:crosscheck_agrees"})
            new_start = r["start"]
            verdict = "date_added kept: cross-check agrees it was not in before"
        decisions.append(
            {
                "ticker": r["ticker"],
                "wikipedia_date_added": r["start"],
                "crosscheck_first_seen": first_seen.get(t),
                "start_used": new_start,
                "verdict": verdict,
            }
        )
    intervals = pl.DataFrame(rows, schema={**MEMBERSHIP_SCHEMA, "as_of": pl.Date}).sort(
        "ticker", "start"
    )
    adj = pl.DataFrame(
        decisions,
        schema={
            "ticker": pl.Utf8,
            "wikipedia_date_added": pl.Date,
            "crosscheck_first_seen": pl.Date,
            "start_used": pl.Date,
            "verdict": pl.Utf8,
        },
    ).sort("wikipedia_date_added")
    return intervals, adj


@dataclass
class Reconciliation:
    """Month-end agreement with the cross-check, label differences removed."""

    per_year: pl.DataFrame
    aliases: pl.DataFrame
    residual: pl.DataFrame


def _compare(
    intervals: pl.DataFrame,
    snaps: dict[date, frozenset[str]],
    alias: dict[str, str],
    start: date,
    end: date,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    by_year: dict[int, list[int]] = {}
    diff: dict[str, list] = {}
    for me in month_ends(start, end):
        ours = {t.replace("-", ".") for t in members_at(intervals, me)}
        theirs = {alias.get(t, t) for t in crosscheck_at(snaps, me)}
        agree = ours & theirs
        y = by_year.setdefault(me.year, [0, 0, 0])
        y[0] += len(ours)
        y[1] += len(theirs)
        y[2] += len(agree)
        for t in ours - theirs:
            diff.setdefault(t, ["only_wikipedia", 0, me, me])[1] += 1
            diff[t][3] = me
        for t in theirs - ours:
            diff.setdefault(t, ["only_crosscheck", 0, me, me])[1] += 1
            diff[t][3] = me
    per_year = pl.DataFrame(
        [
            {
                "year": y,
                "universe_months": a,
                "crosscheck_months": b,
                "agree": c,
                "agree_pct": round(100 * c / b, 2),
            }
            for y, (a, b, c) in sorted(by_year.items())
        ]
    )
    tickers = pl.DataFrame(
        [
            {"ticker": t, "side": s, "months": n, "first": f, "last": la}
            for t, (s, n, f, la) in diff.items()
        ],
        schema={
            "ticker": pl.Utf8,
            "side": pl.Utf8,
            "months": pl.Int64,
            "first": pl.Date,
            "last": pl.Date,
        },
    ).sort("months", "ticker", descending=[True, False])
    return per_year, tickers


def reconcile(
    intervals: pl.DataFrame,
    snaps: dict[date, frozenset[str]],
    renames: pl.DataFrame,
    start: date,
    end: date,
) -> Reconciliation:
    """Month-end agreement with the cross-check, and the tickers that differ.

    The cross-check labels a security with the ticker of the day and this
    pipeline with the current one, so a member renamed without an index
    event (EQR -> VMRK) shows up on both sides of a raw comparison with the
    same month count and the same first and last month. Those pairs are
    the same security; they are paired as aliases and the comparison is
    run again, so the residual is membership disagreement, not labels.
    """
    alias = {
        r["old_ticker"].replace("-", "."): r["new_ticker"].replace("-", ".")
        for r in renames.iter_rows(named=True)
    }
    _, raw_diff = _compare(intervals, snaps, alias, start, end)

    ours: dict[tuple, list[str]] = {}
    theirs: dict[tuple, list[str]] = {}
    for r in raw_diff.iter_rows(named=True):
        side = ours if r["side"] == "only_wikipedia" else theirs
        side.setdefault((r["months"], r["first"], r["last"]), []).append(r["ticker"])
    pairs = []
    for k, w in ours.items():
        c = theirs.get(k, [])
        # One name each side with the same span, and a span long enough
        # that it is not a coincidence of one month at a removal boundary.
        if len(w) == 1 and len(c) == 1 and k[0] >= MIN_ALIAS_MONTHS:
            pairs.append(
                {
                    "crosscheck_ticker": c[0],
                    "wikipedia_ticker": w[0],
                    "months": k[0],
                    "first": k[1],
                    "last": k[2],
                }
            )
            alias[c[0]] = w[0]
    aliases = pl.DataFrame(
        pairs,
        schema={
            "crosscheck_ticker": pl.Utf8,
            "wikipedia_ticker": pl.Utf8,
            "months": pl.Int64,
            "first": pl.Date,
            "last": pl.Date,
        },
    ).sort("months", descending=True)

    per_year, residual = _compare(intervals, snaps, alias, start, end)
    return Reconciliation(per_year, aliases, residual)


# --- overrides ----------------------------------------------------------

OVERRIDES_SCHEMA = {
    "ticker": pl.Utf8,
    "security": pl.Utf8,
    "start": pl.Date,
    "end": pl.Date,
    "reason": pl.Utf8,
    "evidence": pl.Utf8,
}


def apply_overrides(intervals: pl.DataFrame, overrides: pl.DataFrame) -> pl.DataFrame:
    """Apply hand-verified intervals the two tables cannot express.

    Each row of ``data/checks/membership_overrides.csv`` is one interval
    with a reason and the evidence for it. A row whose (ticker, end)
    matches an existing interval corrects that interval's start, the case
    of a name added under an old ticker and removed under a new one, where
    the walk cannot place the addition and the start falls to unknown.
    Any other row is appended. Overrides never delete: they can only put
    back what the walk lost or pin down what it could not.
    """
    if overrides.height == 0:
        return intervals
    as_of = intervals["as_of"][0]
    keyed = overrides.with_columns(pl.lit(True).alias("_hit"))
    merged = intervals.join(keyed, on=["ticker", "end"], how="left", suffix="_ov")
    corrected = merged.select(
        "ticker",
        "security",
        pl.when(pl.col("_hit"))
        .then(pl.col("start_ov"))
        .otherwise("start")
        .alias("start"),
        "end",
        pl.when(pl.col("_hit"))
        .then(pl.lit("override"))
        .otherwise("start_source")
        .alias("start_source"),
        "end_source",
        "as_of",
    )
    hit = merged.filter(pl.col("_hit")).select("ticker", "end")
    extra = overrides.join(hit, on=["ticker", "end"], how="anti").select(
        "ticker",
        "security",
        "start",
        "end",
        pl.lit("override").alias("start_source"),
        pl.lit("override").alias("end_source"),
        pl.lit(as_of).alias("as_of"),
    )
    return pl.concat([corrected, extra]).sort("ticker", "start")


# --- query --------------------------------------------------------------


def members_at(membership: pl.DataFrame, d: date) -> list[str]:
    """Tickers whose interval contains ``d``: start <= d <= end (end null = open)."""
    return (
        membership.filter(
            (pl.col("start") <= d) & (pl.col("end").is_null() | (pl.col("end") >= d))
        )
        .get_column("ticker")
        .unique()
        .sort()
        .to_list()
    )


def month_ends(start: date, end: date) -> list[date]:
    out = []
    d = start.replace(day=1)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        me = nxt - timedelta(days=1)
        if start <= me <= end:
            out.append(me)
        d = nxt
    return out


def monthly_counts(membership: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    """Number of members at each month-end in [start, end]."""
    rows = [
        {"month": me, "n_members": len(members_at(membership, me))}
        for me in month_ends(start, end)
    ]
    return pl.DataFrame(rows, schema={"month": pl.Date, "n_members": pl.Int64})


# --- pipeline entry -----------------------------------------------------


def fetch(cfg: Config, as_of: date) -> tuple[Path, Path, Path]:
    """Download the two Wikipedia pages and the cross-check, stamped ``as_of``."""
    root = cfg.data / "raw"
    return (
        raw.fetch_to_raw(
            root, f"wikipedia/sp500_constituents_{as_of}.html", CONSTITUENTS_URL
        ),
        raw.fetch_to_raw(root, f"wikipedia/sp500_changes_{as_of}.html", CHANGES_URL),
        raw.fetch_to_raw(
            root, f"crosscheck/sp500_fja05680_{as_of}.csv", CROSSCHECK_URL
        ),
    )


def build(cfg: Config) -> pl.DataFrame:
    """Parse the latest raw files, write interim parquet and the check files."""
    root = cfg.data / "raw"
    cons_path = raw.latest(root, "wikipedia/sp500_constituents_*.html")
    chg_path = raw.latest(root, "wikipedia/sp500_changes_*.html")
    xc_path = raw.latest(root, "crosscheck/sp500_fja05680_*.csv")
    as_of = date.fromisoformat(cons_path.stem.rsplit("_", 1)[-1])

    constituents = parse_constituents(cons_path.read_text(encoding="utf-8"))
    changes = parse_changes(chg_path.read_text(encoding="utf-8"))
    snaps = parse_crosscheck(xc_path.read_text(encoding="utf-8"))

    checks = cfg.data / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    overrides_path = checks / "membership_overrides.csv"
    overrides = (
        pl.read_csv(overrides_path, schema=OVERRIDES_SCHEMA)
        if overrides_path.exists()
        else pl.DataFrame(schema=OVERRIDES_SCHEMA)
    )

    m = build_membership(constituents, changes, as_of)
    intervals, adjudications = adjudicate(m, snaps)
    intervals = apply_overrides(intervals, overrides)
    rec = reconcile(intervals, snaps, m.renames, cfg.start, cfg.end)

    interim = cfg.data / "interim"
    interim.mkdir(parents=True, exist_ok=True)
    stamp = pl.lit(as_of).alias("as_of")
    intervals.write_parquet(interim / "membership.parquet")
    changes.with_columns(stamp).write_parquet(interim / "sp500_changes.parquet")
    constituents.with_columns(stamp).write_parquet(
        interim / "sp500_constituents.parquet"
    )
    m.renames.with_columns(stamp).write_parquet(interim / "ticker_renames.parquet")

    m.inconsistencies.write_csv(checks / "membership_inconsistencies.csv")
    m.renames.write_csv(checks / "ticker_renames.csv")
    adjudications.write_csv(checks / "membership_adjudications.csv")
    rec.per_year.write_csv(checks / "membership_crosscheck_by_year.csv")
    rec.aliases.write_csv(checks / "membership_crosscheck_aliases.csv")
    rec.residual.write_csv(checks / "membership_crosscheck_residual.csv")
    monthly_counts(intervals, cfg.start, cfg.end).write_csv(
        checks / "membership_monthly_counts.csv"
    )
    _write_summary(
        checks / "membership_summary.csv", intervals, changes, rec.per_year, cfg
    )
    return intervals


def _write_summary(
    path: Path,
    membership: pl.DataFrame,
    changes: pl.DataFrame,
    per_year: pl.DataFrame,
    cfg: Config,
) -> None:
    counts = monthly_counts(membership, cfg.start, cfg.end)
    in_window = membership.filter(
        (pl.col("end").is_null() | (pl.col("end") >= cfg.start))
        & (pl.col("start") <= cfg.end)
    )
    src = membership["start_source"].str.split(":").list.first()
    rows = {
        "as_of": membership["as_of"][0],
        "intervals": membership.height,
        "unique_tickers_in_window": in_window["ticker"].n_unique(),
        "current_members": membership.filter(pl.col("end").is_null()).height,
        "start_from_changes": (src == "changes").sum(),
        "start_from_date_added_pre2010": (src == "constituents").sum(),
        "start_from_crosscheck": (src == "crosscheck").sum(),
        "start_date_added_crosscheck_agrees": (src == "date_added").sum(),
        "start_unknown": (src == "unknown").sum(),
        "overrides": (src == "override").sum(),
        "changes_rows": changes.height,
        "changes_in_window": changes.filter(pl.col("date") >= cfg.start).height,
        "months": counts.height,
        "n_members_min": counts["n_members"].min(),
        "n_members_median": counts["n_members"].median(),
        "n_members_max": counts["n_members"].max(),
        "crosscheck_agree_pct": round(
            100 * per_year["agree"].sum() / per_year["crosscheck_months"].sum(), 2
        ),
    }
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerows(rows.items())
