"""The specification log and the trial count it yields.

    log_specification(path, cfg, **fields)   append one row (invariant 8);
                                              the same run twice is one row
    spec_key(row) -> str                      what makes a row a distinct trial
    count_specifications(path, kind) -> int   rows logged
    count_trials(path, kind) -> int           distinct spec keys
    latest_per_key(path, kind) -> list[dict]  one row per key, the last run

Every backtest appends one row to ``reports/specifications.csv``; the
file is append-only and nothing here deletes from it. Two counts are
read off it. The row count is how many runs happened. The trial count
is how many *distinct specifications* were tried, and that is the N of
the deflated Sharpe (FIX_PLAN_2 G2): re-running the same specification
after a code fix, which the three post-F3 reruns did 48 times each, is
not a fresh draw from the space of strategies, so it must not deflate
the Sharpe further.

A specification is the tuple in ``KEY_FIELDS``. Two knobs the plan's
tuple did not name are included, because without them two logged
sensitivities collapse into their base runs: ``sector_neutral`` (the
plan names it; it was only in the note) and ``variant``, which is
``terminal`` for the delisting convention and the text scorer's
similarity for the 10-K factor. Both are written from the run's
arguments now and backfilled from the note for older rows.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from backtester.config import Config, config_hash

SPEC_COLUMNS = [
    "timestamp",
    "factor",
    "signal",
    "weighting",
    "cost_bps",
    "lag_days",
    "rebalance",
    "holding_months",
    "winsor_lo",
    "winsor_hi",
    "n_deciles",
    "start",
    "end",
    "sharpe_gross",
    "sharpe_net",
    "note",
    "config_hash",
    "git_commit",
    "kind",
    "sector_neutral",
    "variant",
    "spec_key",
]
KEY_FIELDS = (
    "factor",
    "signal",
    "weighting",
    "cost_bps",
    "lag_days",
    "rebalance",
    "holding_months",
    "winsor_lo",
    "winsor_hi",
    "n_deciles",
    "sector_neutral",
    "start",
    "end",
    "variant",
)
# A row is a candidate (something that could be reported) or a diagnostic
# (a sensitivity, a replication, a check). The deflated Sharpe is reported
# with both counts (FIX_PLAN F4); the kind is read off the note so the
# rows logged before the column existed are classified the same way.
DIAGNOSTIC_PREFIXES = ("diagnostic", "sensitivity", "french replication")
# The same specification, at the same commit, under the same note, is
# the same run: logged once (FIX_PLAN_3 H4).
DUPLICATE_FIELDS = ("spec_key", "git_commit", "note")
TEXT_SIGNAL = "doc_similarity"


def spec_kind(note: str | None) -> str:
    n = (note or "").strip().lower()
    return "diagnostic" if n.startswith(DIAGNOSTIC_PREFIXES) else "candidate"


def sector_neutral_of(note: str | None) -> str:
    """Backfill: ``run_factor`` appends " no-sector" to the note of every
    run without sector neutralisation, and always has."""
    return "0" if "no-sector" in (note or "") else "1"


def variant_of(note: str | None, signal: str | None) -> str:
    """Backfill: the delisting sensitivity is noted "sensitivity terminal";
    the Jaccard text run "sensitivity jaccard"; every other text row ran
    the cosine scorer. Row 94 is labelled jaccard and was cosine (see the
    README); it is keyed as labelled, and the correction is row 131."""
    n = (note or "").strip().lower()
    if n.startswith("sensitivity terminal"):
        return "terminal"
    if TEXT_SIGNAL in (signal or ""):
        return "jaccard" if "jaccard" in n else "cosine"
    return ""


def _norm(value: object) -> str:
    """One spelling per value, so "10" and "10.0" key the same."""
    s = "" if value is None else str(value).strip()
    try:
        return f"{float(s):g}"
    except ValueError:
        return s


def spec_key(row: Mapping[str, object]) -> str:
    """First 12 hex digits of the sha256 of the ``KEY_FIELDS`` tuple."""
    payload = "\x1f".join(_norm(row.get(k)) for k in KEY_FIELDS)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _fmt(x: object) -> str:
    if isinstance(x, float):
        return "" if math.isnan(x) else f"{x:.4f}"
    return "" if x is None else str(x)


def log_specification(path: Path, cfg: Config, **fields: object) -> dict[str, str]:
    """Append one row to the specifications log (invariant 8) and return
    it. A row whose ``spec_key``, ``git_commit`` and ``note`` all match
    one already in the log is the same run made twice (a diagnostic
    script run to completion twice, FIX_PLAN_3 H4); it is not appended
    and the existing row is returned instead. A rerun after a code change
    has a new commit and is appended, as before."""
    path.parent.mkdir(parents=True, exist_ok=True)
    note = str(fields.get("note", ""))
    signal = str(fields.get("signal", ""))
    variant = str(fields.get("variant") or "")
    if not variant and TEXT_SIGNAL in signal:
        variant = cfg.text_similarity
    row = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "factor": fields.get("factor", ""),
        "signal": signal,
        "weighting": cfg.weighting,
        "cost_bps": cfg.base_bps,
        "lag_days": cfg.lag_days,
        "rebalance": cfg.rebalance,
        "holding_months": cfg.holding_months,
        "winsor_lo": cfg.winsor[0],
        "winsor_hi": cfg.winsor[1],
        "n_deciles": cfg.n_deciles,
        "start": cfg.start,
        "end": cfg.end,
        "sharpe_gross": _fmt(fields.get("sharpe_gross")),
        "sharpe_net": _fmt(fields.get("sharpe_net")),
        "note": note,
        "config_hash": config_hash(cfg),
        "git_commit": git_commit(),
        "kind": fields.get("kind") or spec_kind(note),
        "sector_neutral": "1" if fields.get("sector_neutral", True) else "0",
        "variant": variant,
    }
    row["spec_key"] = spec_key(row)
    new = not path.exists() or path.stat().st_size == 0
    if not new:
        upgrade(path)
        for existing in read(path):
            if all(existing[k] == row[k] for k in DUPLICATE_FIELDS):
                return existing
    out = {k: "" if v is None else str(v) for k, v in row.items()}  # as csv writes
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SPEC_COLUMNS)
        if new:
            w.writeheader()
        w.writerow(out)
    return out


def git_commit() -> str:
    """Short hash of HEAD, or "nogit" outside a repository."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def upgrade(path: Path) -> None:
    """Bring a log written under an older header up to SPEC_COLUMNS.

    Columns are only ever appended, so every existing row keeps its
    values and gets blanks for the new ones; the row count is unchanged.
    Rows logged before a column existed are not backfilled, with the
    exceptions that are functions of what the row already holds:
    ``kind`` from the note (FIX_PLAN F4), ``sector_neutral`` and
    ``variant`` from the note and signal, and ``spec_key`` from all of
    those (FIX_PLAN_2 G2). The commit a 2026-09-11 run was made under is
    not known, and is not guessed.
    """
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == SPEC_COLUMNS:
            return
        if not set(reader.fieldnames or []) <= set(SPEC_COLUMNS):
            raise ValueError(f"{path} has columns outside SPEC_COLUMNS")
        rows = list(reader)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SPEC_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(_complete({c: r.get(c) or "" for c in SPEC_COLUMNS}))


def _complete(row: dict[str, str]) -> dict[str, str]:
    row["kind"] = row["kind"] or spec_kind(row["note"])
    row["sector_neutral"] = row["sector_neutral"] or sector_neutral_of(row["note"])
    row["variant"] = row["variant"] or variant_of(row["note"], row["signal"])
    row["spec_key"] = row["spec_key"] or spec_key(row)
    return row


def read(path: Path, kind: str | None = None) -> list[dict[str, str]]:
    """Every row, in file order, with the derived columns filled in
    memory for a log that has not been upgraded on disk yet."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = [
            _complete({c: r.get(c) or "" for c in SPEC_COLUMNS})
            for r in csv.DictReader(f)
        ]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return rows


def count_specifications(path: Path, kind: str | None = None) -> int:
    """Rows in the log, optionally of one kind: how many runs happened."""
    return len(read(path, kind))


def count_trials(path: Path, kind: str | None = None) -> int:
    """Distinct specification keys: the N of the deflated Sharpe. Never
    an argument (invariant 8)."""
    return len({r["spec_key"] for r in read(path, kind)})


def latest_per_key(path: Path, kind: str | None = None) -> list[dict[str, str]]:
    """One row per specification key, the last one logged, in first-seen
    order. The dispersion of Sharpe across trials is measured over these,
    not over every rerun of the same trial."""
    last: dict[str, dict[str, str]] = {}
    for r in read(path, kind):
        last[r["spec_key"]] = r
    return list(last.values())
