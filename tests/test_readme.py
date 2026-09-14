"""No number in the README is typed from memory: its results table is the
one in reports/results.md, which report.py writes (BUILD_PLAN ruling 4)."""

import re
from pathlib import Path

HEADER = "| Factor | Gross ann. |"


def _table(text: str) -> list[str]:
    """The results table rows that follow the header, minus-signs normalised."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(HEADER))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(re.sub(r"(?<=\s)-(?=\d)", "−", line.strip()))
    return rows


def test_readme_results_table_matches_results_md(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    results = (repo_root / "reports" / "results.md").read_text(encoding="utf-8")
    assert _table(readme) == _table(results)
