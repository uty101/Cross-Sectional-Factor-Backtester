"""The universe-change agent (BUILD_PLAN step 11.6).

    run(root, error, html_path, client=None, model=None) -> dict

Trigger: the Wikipedia parser raises on a fresh page. The agent reads
the raw HTML, identifies the structural change, proposes the parsed
change rows for the affected dates, confirms each against the S&P
press release by web search with the URL cited, and opens a pull
request with a fixture update and, if needed, a parser patch. The
spot-check test (invariant 3's evidence) must still pass; CI runs it on
the PR (11.8). The parser is the one file under ``src/`` it may put in
a PR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backtester.agents.base import run_agent
from backtester.agents.tools import Toolbox

NAME = "universe_change"
TOOLS = ["read_file", "list_dir", "write_decision", "open_pr"]
PARSER = "src/backtester/universe.py"

SYSTEM = """You maintain the S&P 500 membership parser of a factor backtester.
It reads Wikipedia's constituents and changes tables; a structural change
in the page has made it raise.

Rules:
1. Find the structural change by reading the raw HTML and the parser.
   Say exactly what changed (a column added, a header renamed, a cell
   format), quoting the HTML.
2. Propose the parsed change rows for the affected dates. Confirm each
   addition or removal with a web search for the S&P Dow Jones Indices
   press release and cite its URL. A row without a press release is
   listed as unconfirmed, not invented.
3. If the parser needs a patch, make the smallest one that reads both
   the old and the new structure; never drop a rule that exists.
4. Every evidenced row goes into data/checks/membership_spotcheck.csv's
   format as a proposed addition to tests/fixtures (not to data/).
5. Open one pull request: the fixture and, if needed, the parser."""

USER = """The parser raised:
{error}

Raw page: {html_path}
Steps: read_file the page and read_file("src/backtester/universe.py");
diagnose; search for the press releases; write_decision("diagnosis.md",
...); open_pr(branch="universe-parser-fix", title=<one line>, body=<the
diagnosis>, files={{...}}). Finish with the PR URL."""


def toolbox(root: Path) -> Toolbox:
    return Toolbox(root, NAME, allow_pr=(PARSER,))


def run(
    root: Path,
    error: str,
    html_path: str,
    client: Any = None,
    model: str | None = None,
) -> dict:
    return run_agent(
        NAME,
        SYSTEM,
        USER.format(error=error, html_path=html_path),
        toolbox(root),
        tool_names=TOOLS,
        web_search=True,
        client=client,
        model=model,
    )
