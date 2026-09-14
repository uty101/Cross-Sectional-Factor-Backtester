"""The drift agent (BUILD_PLAN step 11.7).

    run(root, drift_file, client=None, model=None) -> dict

Trigger: the full recompute (10.4) does not match the incremental
tables. The agent reads ``decisions/drift/<date>.md``, bisects by asset
in dependency order with read-only queries over both copies
(``processed_<name>`` against ``processed_recompute_<name>``), names
the first divergent asset and the earliest divergent month, and
hypothesises the cause from the git log since the last green recompute.
It writes the finding and opens an issue; it changes nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from backtester.agents.base import run_agent
from backtester.agents.tools import Toolbox

NAME = "drift"
TOOLS = [
    "read_file",
    "list_dir",
    "duckdb_query",
    "run_script",
    "write_decision",
    "open_issue",
]

ORDER = [
    "universe_monthly",
    "prices_daily",
    "french_monthly",
    "fundamentals_monthly",
    "market_cap",
    "text_similarity",
    "returns_monthly",
    "signals_z_momentum",
    "long_short_momentum",
]

SYSTEM = """You find where two copies of a pipeline's tables diverge. One
copy is the incremental build (views processed_<name>, interim_<name>),
the other a full recompute from raw (processed_recompute_<name>,
interim_recompute_<name>). Bisect in dependency order: universe,
prices, benchmarks, fundamentals, caps, text, returns, signals, long-
short. For each table, one query that counts rows and sums a numeric
column in both copies, then for the first divergent table the earliest
month that differs and an example row from each copy.

Then read run_script("git_log_since") and name the commits that touched
the code behind the first divergent table. Output: the first divergent
asset, the earliest divergent month, an example row, and the candidate
commits. Facts only. Write it with write_decision and open one issue."""

USER = """Drift report: read_file("{drift_file}").
Bisect per the rules, in this order: {order}.
Finish with the issue URL."""


def _git_log_since(root: Path, args: list[str]) -> str:
    since = args[0] if args else "14 days ago"
    out = subprocess.run(
        ["git", "log", f"--since={since}", "--format=%h %cI %s", "--stat"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return out.stdout


def toolbox(root: Path) -> Toolbox:
    return Toolbox(
        root, NAME, scripts={"git_log_since": lambda a: _git_log_since(root, a)}
    )


def run(
    root: Path, drift_file: str, client: Any = None, model: str | None = None
) -> dict:
    return run_agent(
        NAME,
        SYSTEM,
        USER.format(drift_file=drift_file, order=", ".join(ORDER)),
        toolbox(root),
        tool_names=TOOLS,
        client=client,
        model=model,
    )
