"""The tag-map agent (BUILD_PLAN step 11.4).

    run(root, concepts, client=None, model=None) -> dict

Trigger: the fundamentals coverage check fails, or a new quarter brings
tags that match a concept's keywords. For each under-covered concept it
queries the ingested SEC rows for the universe CIKs that report nothing
under the mapped tags, finds what they report the concept under, and
proposes additions to ``tag_map.toml``, one line of rationale each,
as a pull request. It is the one agent allowed to put a file under
``src/`` in a PR, and only that file; CI reruns coverage on the PR and
fails it if any concept's coverage fell (11.8).

A tag addition changes the fundamentals and therefore reported returns.
The merge is a human decision, and the run that follows is a
specification row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backtester.agents.base import run_agent
from backtester.agents.tools import Toolbox

NAME = "tag_map"
TOOLS = ["read_file", "duckdb_query", "run_script", "write_decision", "open_pr"]
TAG_MAP = "src/backtester/tag_map.toml"

SYSTEM = """You maintain the XBRL tag map of a factor backtester. A concept
maps to an ordered list of tags; the first present wins. Your job is to
find, for an under-covered concept, which tags the filers that report
nothing under the mapped tags actually use, and to propose additions.

Rules:
1. Evidence for every proposed tag: the count of universe CIKs and the
   fiscal years in which it appears, from duckdb_query. No tag without a
   query result behind it.
2. Never remove or reorder an existing tag. Append only.
3. A proposed tag must measure the same thing. Say in one line why, in
   terms of the tag's name and the concept's definition; if unsure, list
   it under "not proposed" with the reason.
4. Output: the full new tag_map.toml (existing content byte for byte
   plus appended tags) in a pull request touching that one file, and a
   decision file with the evidence table.

Tables: interim_sec_num has adsh, cik, concept, tag, ddate, qtrs, value,
filed, form, fy, fp, sic, name for the mapped tags only. Use it to find
the universe CIKs with no row for the concept in a fiscal year, then
run_script("candidate_tags", [concept, fy, "cik1,cik2,..."]) to see
every USD tag those CIKs did report that year, from the raw filings."""

USER = """Concepts under-covered: {concepts}.
Steps:
1. read_file("src/backtester/tag_map.toml") and
   read_file("data/checks/tag_coverage.csv").
2. For each concept, duckdb_query the universe CIKs (interim_sectors) with
   no interim_sec_num row for it in the latest full fiscal year, then
   run_script("candidate_tags", [concept, fy, <their ciks>]).
3. Propose appended tags with evidence, per the rules.
4. write_decision("tag_map_proposal.md", <evidence and rationale>).
5. open_pr(branch="tag-map-proposal", title="Tag map: proposed additions for
   {concepts}", body=<one paragraph>,
   files={{"src/backtester/tag_map.toml": <full file>}}).
Finish with the PR URL, or "nothing to propose" and why."""


def _candidates(root: Path, args: list[str]) -> str:
    from backtester import config, fundamentals

    concept, fy, ciks = args[0], int(args[1]), [int(c) for c in args[2].split(",")]
    cfg = config.load(root / "config.toml")
    return fundamentals.candidate_tags(cfg, concept, fy, ciks).write_csv()


def toolbox(root: Path) -> Toolbox:
    return Toolbox(
        root,
        NAME,
        scripts={"candidate_tags": lambda a: _candidates(root, a)},
        allow_pr=(TAG_MAP,),
    )


def run(
    root: Path, concepts: list[str], client: Any = None, model: str | None = None
) -> dict:
    return run_agent(
        NAME,
        SYSTEM,
        USER.format(concepts=", ".join(concepts)),
        toolbox(root),
        tool_names=TOOLS,
        client=client,
        model=model,
    )
