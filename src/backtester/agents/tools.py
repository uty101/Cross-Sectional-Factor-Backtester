"""The tools an agent may call, each with its allowlist enforced here.

Every tool takes the repo root explicitly, so a test can point it at a
temporary directory. Paths are resolved and checked before anything is
read or written; a path that escapes the root, or lands in a forbidden
tree, raises rather than being silently ignored. The model sees the
error text and nothing else.

Forbidden for every tool that writes: ``data/``, ``src/``, ``config.toml``,
``reports/specifications.csv``, ``.env``. Those change what the pipeline
computes, and an agent proposes; it does not compute.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MAX_READ_BYTES = 200_000
MAX_QUERY_ROWS = 500
FORBIDDEN_WRITE = ("data", "src", "config.toml", "reports/specifications.csv", ".env")
FORBIDDEN_READ = (".env", ".git")
SELECT_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class Tool:
    """One tool: the schema the model sees and the function that runs."""

    name: str
    description: str
    input_schema: dict
    fn: Callable[..., str]

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class Toolbox:
    """The tools for one run, bound to a repo root and an agent name."""

    root: Path
    agent: str
    scripts: dict[str, Callable[[list[str]], str]] = field(default_factory=dict)

    # --- guards ---------------------------------------------------------

    def _inside(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise PermissionError(f"{rel} is outside the repository")
        return p

    def _readable(self, rel: str) -> Path:
        p = self._inside(rel)
        r = p.relative_to(self.root.resolve()).as_posix()
        if any(r == f or r.startswith(f + "/") for f in FORBIDDEN_READ):
            raise PermissionError(f"{rel} is not readable by an agent")
        return p

    def _writable(self, rel: str) -> Path:
        p = self._inside(rel)
        r = p.relative_to(self.root.resolve()).as_posix()
        if any(r == f or r.startswith(f + "/") for f in FORBIDDEN_WRITE):
            raise PermissionError(f"{rel} is not writable by an agent")
        return p

    # --- read -----------------------------------------------------------

    def read_file(self, path: str) -> str:
        p = self._readable(path)
        data = p.read_bytes()
        text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        if len(data) > MAX_READ_BYTES:
            text += f"\n... [truncated at {MAX_READ_BYTES} bytes of {len(data)}]"
        return text

    def list_dir(self, path: str = ".") -> str:
        p = self._readable(path)
        root = self.root.resolve()
        return "\n".join(
            f"{'d' if c.is_dir() else 'f'} {c.relative_to(root).as_posix()}"
            for c in sorted(p.iterdir())
            if c.name not in FORBIDDEN_READ
        )

    def duckdb_query(self, sql: str) -> str:
        """SELECT over views of every parquet under data/ and the spec log,
        in a fresh in-memory DuckDB with no write path to disk."""
        import duckdb

        if not SELECT_ONLY.match(sql):
            raise PermissionError("only SELECT / WITH statements are allowed")
        con = duckdb.connect()
        for sub in ("interim", "processed"):
            for f in sorted((self.root / "data" / sub).glob("*.parquet")):
                con.execute(
                    f"CREATE VIEW {sub}_{f.stem} AS SELECT * FROM "
                    f"read_parquet('{f.as_posix()}')"
                )
        spec = self.root / "reports" / "specifications.csv"
        if spec.exists():
            con.execute(
                "CREATE VIEW specifications AS SELECT * FROM "
                f"read_csv('{spec.as_posix()}', header=true, all_varchar=true)"
            )
        rel = con.execute(sql)
        cols = [d[0] for d in rel.description]
        rows = rel.fetchmany(MAX_QUERY_ROWS + 1)
        out = {"columns": cols, "rows": rows[:MAX_QUERY_ROWS]}
        if len(rows) > MAX_QUERY_ROWS:
            out["truncated"] = True
        return json.dumps(out, default=str)

    # --- run ------------------------------------------------------------

    def run_script(self, name: str, args: list[str] | None = None) -> str:
        if name not in self.scripts:
            raise PermissionError(
                f"{name} is not an allowed script: {sorted(self.scripts)}"
            )
        return self.scripts[name](list(args or []))

    # --- write ----------------------------------------------------------

    def write_decision(self, filename: str, content: str) -> str:
        if not SAFE_NAME.match(filename):
            raise PermissionError(f"decision filename {filename!r} must be a bare name")
        p = self._writable(f"decisions/{self.agent}/{filename}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        return p.relative_to(self.root.resolve()).as_posix()

    def open_pr(self, branch: str, title: str, body: str, files: dict[str, str]) -> str:
        """Commit ``files`` on a new branch in a temporary worktree, push,
        open a PR with gh. The main working tree is not touched."""
        if not SAFE_NAME.match(branch):
            raise PermissionError(f"branch {branch!r} must be a bare name")
        for rel in files:
            self._writable(rel)
        wt = self.root / ".agent-worktrees" / branch
        wt.parent.mkdir(exist_ok=True)
        try:
            _git(self.root, "worktree", "add", "-b", branch, str(wt), "HEAD")
            for rel, content in files.items():
                p = wt / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8", newline="\n")
            _git(wt, "add", "-A")
            _git(wt, "commit", "-q", "-m", f"{title}\n\n{body}\n\nAgent: {self.agent}")
            _git(wt, "push", "-q", "-u", "origin", branch)
            out = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--head",
                    branch,
                ],
                cwd=wt,
                capture_output=True,
                text=True,
                check=True,
            )
            return out.stdout.strip()
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=self.root,
                capture_output=True,
            )

    def open_issue(self, title: str, body: str) -> str:
        out = subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()

    # --- the set the model sees ----------------------------------------

    def tools(self, names: list[str] | None = None) -> list[Tool]:
        s = {"type": "string"}
        all_tools = [
            Tool(
                "read_file",
                "Read a file in the repository.",
                _schema(path=s),
                self.read_file,
            ),
            Tool(
                "list_dir",
                "List a directory in the repository.",
                _schema(path=s),
                self.list_dir,
            ),
            Tool(
                "duckdb_query",
                "Run one SELECT over the pipeline's tables: interim_<name> and "
                "processed_<name> for each parquet, and specifications. Returns "
                "JSON {columns, rows}, at most 500 rows.",
                _schema(sql=s),
                self.duckdb_query,
            ),
            Tool(
                "run_script",
                f"Run an allowed script by name: {sorted(self.scripts)}.",
                _schema(name=s, args={"type": "array", "items": s}, required=["name"]),
                self.run_script,
            ),
            Tool(
                "write_decision",
                f"Write a file under decisions/{self.agent}/. Bare filename only.",
                _schema(filename=s, content=s),
                self.write_decision,
            ),
            Tool(
                "open_pr",
                "Open a pull request with the given files (path -> full content). "
                "Never data/, src/, config.toml or the specification log.",
                _schema(
                    branch=s,
                    title=s,
                    body=s,
                    files={"type": "object", "additionalProperties": s},
                ),
                self.open_pr,
            ),
            Tool(
                "open_issue",
                "Open a GitHub issue.",
                _schema(title=s, body=s),
                self.open_issue,
            ),
        ]
        if names is None:
            return all_tools
        return [t for t in all_tools if t.name in names]


def _schema(required: list[str] | None = None, **props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required if required is not None else list(props),
        "additionalProperties": False,
    }


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return out.stdout


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
