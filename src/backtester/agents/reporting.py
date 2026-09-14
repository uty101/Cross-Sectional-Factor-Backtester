"""The reporting agent (BUILD_PLAN step 11.3).

    run(root, checks_passed, client=None, model=None) -> dict

Trigger: a pipeline run with every asset check green. Reads results.md
and validation.csv, and the results.md of the previous month from git,
and writes a 200-word ``reports/monthly_notes/<YYYY-MM>.md`` stating
what changed, numbers only, no forecasts. Refused by the harness, before
any model call, when a check failed: the note would describe a run that
did not pass.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backtester.agents.base import run_agent
from backtester.agents.tools import Toolbox

NAME = "reporting"
TOOLS = ["read_file", "list_dir", "run_script", "write_decision", "open_pr"]

SYSTEM = """You write the monthly note for a factor backtester. The note is
numbers only: what each reported factor's net Sharpe, deflated Sharpe,
turnover and validation correlation are this month and what they were
last month, and which specification rows were added between the two.
No forecasts, no recommendations, no adjectives. Two hundred words at
most. Cite the source line for every number (results.md or
validation.csv). If nothing changed, say so in one sentence."""

USER = """Steps:
1. read_file("reports/results.md") and read_file("reports/validation.csv").
2. run_script("previous_results") — results.md as it was about a month ago
   (empty if there is no earlier version).
3. run_script("spec_rows_since") — specification rows added since then.
4. Write the note per the rules.
5. write_decision("note_{ym}.md", <note>), then open_pr(
   branch="monthly-note-{ym}", title="Monthly note {ym}",
   body="Numbers only; see the note.",
   files={{"reports/monthly_notes/{ym}.md": <note>}}).
Finish with one line: the PR URL."""


def _previous_results(root: Path) -> str:
    """results.md at the last commit at least 28 days old, or ''."""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--before=28 days ago"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    sha = out.stdout.strip()
    if not sha:
        return ""
    show = subprocess.run(
        ["git", "show", f"{sha}:reports/results.md"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return show.stdout if show.returncode == 0 else ""


def _spec_rows_since(root: Path) -> str:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--before=28 days ago"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    since = out.stdout.strip()
    spec = (root / "reports" / "specifications.csv").read_text(encoding="utf-8")
    lines = spec.splitlines()
    if not since:
        return "\n".join(lines)
    return "\n".join([lines[0], *[ln for ln in lines[1:] if ln[:19] > since[:19]]])


def toolbox(root: Path) -> Toolbox:
    return Toolbox(
        root,
        NAME,
        scripts={
            "previous_results": lambda _a: _previous_results(root),
            "spec_rows_since": lambda _a: _spec_rows_since(root),
        },
    )


def run(
    root: Path,
    checks_passed: bool,
    client: Any = None,
    model: str | None = None,
) -> dict:
    if not checks_passed:
        raise PermissionError("reporting agent is blocked: an asset check failed")
    ym = datetime.now(UTC).strftime("%Y-%m")
    return run_agent(
        NAME,
        SYSTEM,
        USER.format(ym=ym),
        toolbox(root),
        tool_names=TOOLS,
        client=client,
        model=model,
    )
