"""The research-log agent (BUILD_PLAN step 11.2).

    run(root, client=None, model=None) -> dict

Trigger: after a pipeline run. It runs the deterministic generator to get
the table of superseded and abandoned specifications, reads the bodies
of the commits that superseded them, and writes the section below the
marker in ``reports/what_did_not_work.md``: for each superseding commit,
one factual line on what changed, quoted or paraphrased from the commit
body, no interpretation. Its draft goes to ``decisions/research_log/``
and the file update goes up as a pull request; it never edits the
generated table above the marker, and the generator never touches the
section below it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backtester import research_log
from backtester.agents.base import run_agent
from backtester.agents.tools import Toolbox

NAME = "research_log"
TOOLS = ["read_file", "run_script", "write_decision", "open_pr"]

SYSTEM = """You maintain the research log of a factor backtester whose rule is
that every specification ever run is a row in reports/specifications.csv
and none is deleted. A generator lists the rows that were superseded or
abandoned and names the first commit after each. Your job is the part
the generator cannot do: read those commits' bodies and say, for each
superseding commit, what changed between the superseded run and the one
that replaced it.

Rules, in order of precedence:
1. Facts only. Quote or paraphrase the commit body. Never say why a
   result is good or bad, never suggest a change, never forecast.
2. One short paragraph per superseding commit, headed by its short sha
   and subject, listing the specifications it superseded by note.
3. Do not touch anything above the marker line in
   reports/what_did_not_work.md; reproduce it byte for byte.
4. Write your draft with write_decision first, then open one pull
   request that replaces reports/what_did_not_work.md with the full file
   (generated table, marker, then your section).
5. If the generator output has no superseded or abandoned rows, write a
   one-line decision saying so and open no pull request."""

USER = """Steps:
1. run_script("research_log") — the generated table with the marker at the end.
2. run_script("git_log") — the last 200 commits with bodies.
3. read_file("reports/what_did_not_work.md") — the current file, to keep
   anything already below the marker that is still accurate.
4. Write the section below the marker per the rules.
5. write_decision("what_did_not_work_draft.md", <full file>).
6. open_pr(branch="research-log-<YYYYMMDD>", title="The research log says what
   changed between superseded runs", body=<two sentences>, files={
   "reports/what_did_not_work.md": <full file>}).
Finish with one line: the PR URL, or "no changes"."""


def toolbox(root: Path) -> Toolbox:
    def gen(_args: list[str]) -> str:
        return research_log.build(root).read_text(encoding="utf-8")

    def log(_args: list[str]) -> str:
        return research_log.git_log_with_bodies(root)

    return Toolbox(root, NAME, scripts={"research_log": gen, "git_log": log})


def run(root: Path, client: Any = None, model: str | None = None) -> dict:
    return run_agent(
        NAME,
        SYSTEM,
        USER,
        toolbox(root),
        tool_names=TOOLS,
        client=client,
        model=model,
    )
