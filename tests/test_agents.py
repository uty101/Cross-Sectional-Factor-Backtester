"""The agent harness: every tool call is executed through the allowlists
and logged; nothing an agent does can reach data/, src/ or the config."""

import json
from pathlib import Path
from types import SimpleNamespace as NS

import polars as pl
import pytest

from backtester.agents import base, tools


class FakeClient:
    """Scripted responses; records every request it received."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _text(t: str, stop: str = "end_turn"):
    return NS(content=[NS(type="text", text=t)], stop_reason=stop)


def _use(name: str, inputs: dict, uid: str = "tu_1"):
    return NS(
        content=[NS(type="tool_use", id=uid, name=name, input=inputs)],
        stop_reason="tool_use",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "interim").mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_bytes(b"hello\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / "config.toml").write_text("x = 1\n")
    (tmp_path / "reports" / "specifications.csv").write_text(
        "timestamp,factor,note\n2026-01-01,momentum,base\n2026-01-02,value,base\n"
    )
    pl.DataFrame(
        {"month": ["2026-01-31"], "ticker": ["A"], "ret": [0.1]}
    ).write_parquet(tmp_path / "data" / "processed" / "returns_monthly.parquet")
    return tmp_path


def test_harness_executes_tool_and_logs_every_field(repo: Path) -> None:
    client = FakeClient([_use("read_file", {"path": "README.md"}), _text("done")])
    box = tools.Toolbox(repo, "unit")
    rec = base.run_agent("unit", "sys", "go", box, client=client, model="m")

    assert rec["tool_calls"] == [
        {
            "tool": "read_file",
            "input": {"path": "README.md"},
            "output": "hello\n",
            "is_error": False,
        }
    ]
    assert rec["final_output"] == "done" and rec["stop_reason"] == "end_turn"
    assert rec["model"] == "m" and len(rec["system_prompt_sha"]) == 64
    # The tool result went back to the model with the matching id.
    second = client.requests[1]["messages"]
    assert second[-1]["content"][0]["tool_use_id"] == "tu_1"
    assert second[-1]["content"][0]["content"] == "hello\n"
    # And the log file on disk has every field.
    logs = list((repo / "decisions" / "unit").glob("*.json"))
    assert len(logs) == 1
    on_disk = json.loads(logs[0].read_text())
    for k in (
        "agent",
        "timestamp",
        "model",
        "system_prompt_sha",
        "user_prompt",
        "tool_calls",
        "final_output",
    ):
        assert k in on_disk
    assert on_disk["user_prompt"] == "go"


def test_tool_error_is_returned_to_the_model_not_raised(repo: Path) -> None:
    client = FakeClient([_use("read_file", {"path": ".env"}), _text("ok")])
    rec = base.run_agent(
        "unit", "s", "u", tools.Toolbox(repo, "unit"), client=client, model="m"
    )
    call = rec["tool_calls"][0]
    assert call["is_error"] and "not readable" in call["output"]
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_max_turns_ends_the_loop(repo: Path) -> None:
    client = FakeClient([_use("list_dir", {"path": "."})] * 3)
    rec = base.run_agent(
        "unit",
        "s",
        "u",
        tools.Toolbox(repo, "unit"),
        client=client,
        model="m",
        max_turns=2,
    )
    assert rec["stop_reason"] == "max_turns" and len(rec["tool_calls"]) == 2


def test_read_guards(repo: Path) -> None:
    box = tools.Toolbox(repo, "unit")
    with pytest.raises(PermissionError):
        box.read_file("../outside.txt")
    with pytest.raises(PermissionError):
        box.read_file(".env")
    assert "f README.md" in box.list_dir(".")
    assert ".env" not in box.list_dir(".")


def test_write_guards_cover_data_src_config_and_the_spec_log(repo: Path) -> None:
    box = tools.Toolbox(repo, "unit")
    for bad in (
        "data/x.parquet",
        "src/backtester/x.py",
        "config.toml",
        "reports/specifications.csv",
    ):
        with pytest.raises(PermissionError):
            box._writable(bad)
        with pytest.raises(PermissionError):
            box.open_pr("b", "t", "b", {bad: "x"})
    with pytest.raises(PermissionError):
        box.write_decision("../escape.md", "x")
    rel = box.write_decision("note.md", "content")
    assert rel == "decisions/unit/note.md"
    assert (repo / rel).read_text() == "content"


def test_duckdb_query_is_select_only_over_views(repo: Path) -> None:
    box = tools.Toolbox(repo, "unit")
    out = json.loads(
        box.duckdb_query("SELECT ticker, ret FROM processed_returns_monthly")
    )
    assert out["columns"] == ["ticker", "ret"] and out["rows"] == [["A", 0.1]]
    n = json.loads(box.duckdb_query("SELECT count(*) AS n FROM specifications"))
    assert n["rows"] == [[2]]
    for bad in (
        "DROP VIEW specifications",
        "COPY specifications TO 'x.csv'",
        "INSERT INTO x VALUES (1)",
    ):
        with pytest.raises(PermissionError):
            box.duckdb_query(bad)


def test_run_script_is_allowlisted(repo: Path) -> None:
    box = tools.Toolbox(repo, "unit", scripts={"echo": lambda args: " ".join(args)})
    assert box.run_script("echo", ["a", "b"]) == "a b"
    with pytest.raises(PermissionError):
        box.run_script("rm", ["-rf"])


def test_tool_specs_are_valid_and_web_search_is_opt_in(repo: Path) -> None:
    box = tools.Toolbox(repo, "unit")
    names = [t.name for t in box.tools()]
    assert names == [
        "read_file",
        "list_dir",
        "duckdb_query",
        "run_script",
        "write_decision",
        "open_pr",
        "open_issue",
    ]
    for t in box.tools():
        assert t.spec()["input_schema"]["type"] == "object"
    client = FakeClient([_text("x")])
    base.run_agent(
        "unit",
        "s",
        "u",
        box,
        client=client,
        model="m",
        web_search=True,
        tool_names=["read_file"],
    )
    sent = client.requests[0]["tools"]
    assert [t["name"] for t in sent] == ["read_file", "web_search"]
    assert sent[-1]["type"] == "web_search_20260209"
