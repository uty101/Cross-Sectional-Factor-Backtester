"""The full recompute check (BUILD_PLAN 10.4).

    full(cfg) -> (matched: bool, report: str)

Rebuilds every interim and processed table from ``data/raw`` into
``data/recompute/`` and compares each with the incremental copy: numeric
columns within 1e-10, everything else exactly, after sorting both by
every column. Stamp columns (``as_of``, ``fetched_at``) are excluded:
they record when a build ran, not what it computed. A difference is
written to ``decisions/drift/<date>.md`` and is what the drift agent
reads (11.7).

The recompute's backtests log to ``data/recompute/specifications.csv``,
not the real log: they are a determinism check of the same
specifications, not new trials, and the deflated Sharpe must not count
them. The raw store is reached through a directory junction so nothing
is copied.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from backtester.config import Config

STAMPS = {"as_of", "fetched_at"}
HAND_WRITTEN = (
    "membership_overrides.csv",
    "membership_spotcheck.csv",
    "cik_overrides.csv",
    "shares_overrides.csv",
)
TOLERANCE = 1e-10


def _link_raw(real: Path, link: Path) -> None:
    if link.exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(real)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(real, target_is_directory=True)


def rebuild(cfg: Config) -> Config:
    """Run every build and every base run under data/recompute/."""
    from backtester import benchmarks, fundamentals, prices, run, shares, text, universe

    root = cfg.data / "recompute"
    _link_raw((cfg.data / "raw").resolve(), root / "raw")
    (root / "interim").mkdir(parents=True, exist_ok=True)
    (root / "processed").mkdir(parents=True, exist_ok=True)
    (root / "checks").mkdir(parents=True, exist_ok=True)
    # The hand-written evidence files are inputs to the builds, not
    # outputs (data/checks/README.md): the universe walk applies the
    # override rows. Without them the recompute lost four intervals.
    for name in HAND_WRITTEN:
        src = cfg.data / "checks" / name
        if src.exists():
            (root / "checks" / name).write_bytes(src.read_bytes())
    c = cfg.with_(data=root, specifications=root / "specifications.csv")
    universe.build(c)
    prices.build(c)
    benchmarks.build(c)
    # shares.build regenerates the CIK map from the (tag-map-stamped) num
    # cache before it lists the universe, so the map, the cover counts
    # and the panel are one consistent build.
    shares.build(c)
    fundamentals.build(c)
    text.build(c)
    run.run_all(c, note="recompute check")
    return c


def compare(a_dir: Path, b_dir: Path) -> list[str]:
    """One line per table that differs, empty when every shared table matches."""
    problems = []
    for a in sorted(a_dir.glob("*.parquet")):
        b = b_dir / a.name
        if not b.exists():
            continue
        x, y = pl.read_parquet(a), pl.read_parquet(b)
        cols = [c for c in x.columns if c not in STAMPS]
        if cols != [c for c in y.columns if c not in STAMPS]:
            problems.append(f"{a.name}: columns differ")
            continue
        x, y = x.select(cols).sort(cols), y.select(cols).sort(cols)
        if x.height != y.height:
            problems.append(f"{a.name}: {x.height} rows against {y.height}")
            continue
        for c in cols:
            if x[c].dtype.is_numeric():
                d = (x[c].cast(pl.Float64) - y[c].cast(pl.Float64)).abs()
                both_null = x[c].is_null() & y[c].is_null()
                bad = (
                    (d > TOLERANCE) | (x[c].is_null() != y[c].is_null())
                ) & ~both_null
            else:
                bad = x[c].ne_missing(y[c])
            n = int(bad.sum())
            if n:
                i = int(bad.arg_max())
                problems.append(
                    f"{a.name}.{c}: {n} rows differ, first at row {i}: "
                    f"{x[c][i]!r} against {y[c][i]!r}"
                )
                break
    return problems


def full(cfg: Config) -> tuple[bool, str]:
    c = rebuild(cfg)
    problems = compare(cfg.data / "interim", c.data / "interim") + compare(
        cfg.data / "processed", c.data / "processed"
    )
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [f"# Full recompute against the incremental tables, {stamp}", ""]
    if problems:
        lines += ["Tables that differ (incremental against recompute):", ""]
        lines += [f"- {p}" for p in problems]
    else:
        lines.append("Every shared table matches within 1e-10.")
    report = "\n".join(lines) + "\n"
    out = Path("decisions") / "drift" / f"{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8", newline="\n")
    return not problems, report
