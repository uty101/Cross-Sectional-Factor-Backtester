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
    # An explicit per-agent allowance covers pull requests only, one path.
    allowed = tools.Toolbox(repo, "tagmap", allow_pr=("src/backtester/tag_map.toml",))
    assert allowed._writable("src/backtester/tag_map.toml", via_pr=True)
    with pytest.raises(PermissionError):
        allowed._writable("src/backtester/tag_map.toml")  # not a direct write
    with pytest.raises(PermissionError):
        allowed._writable("src/backtester/run.py", via_pr=True)  # not that path
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


def test_research_log_agent_wiring(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    # The agent gets exactly its four tools and two scripts; the scripts
    # run the real generator and git log; a scripted model writes a draft.
    import shutil

    from backtester.agents import research_log as agent

    (tmp_path / "reports").mkdir()
    shutil.copy(repo_root / "reports" / "specifications.csv", tmp_path / "reports")
    box = agent.toolbox(tmp_path)
    assert sorted(box.scripts) == ["git_log", "research_log"]
    assert [t.name for t in box.tools(agent.TOOLS)] == agent.TOOLS

    client = FakeClient(
        [
            _use("run_script", {"name": "research_log"}, "t1"),
            _use("write_decision", {"filename": "draft.md", "content": "x"}, "t2"),
            _text("no changes"),
        ]
    )
    # git_log needs a repository; point the generator's git at the real one.
    from backtester import research_log as rl

    real = rl.git_log
    monkeypatch.setattr(rl, "git_log", lambda root: real(repo_root))
    rec = agent.run(tmp_path, client=client, model="m")
    assert rec["agent"] == "research_log" and rec["final_output"] == "no changes"
    gen = rec["tool_calls"][0]
    assert not gen["is_error"] and rl.MARKER in gen["output"]
    assert (tmp_path / "decisions" / "research_log" / "draft.md").read_text() == "x"
    assert client.requests[0]["system"] == agent.SYSTEM


def test_reporting_agent_is_blocked_when_a_check_failed(repo: Path) -> None:
    from backtester.agents import reporting

    with pytest.raises(PermissionError, match="blocked"):
        reporting.run(repo, checks_passed=False, client=FakeClient([]), model="m")
    client = FakeClient([_text("note")])
    rec = reporting.run(repo, checks_passed=True, client=client, model="m")
    assert rec["agent"] == "reporting"
    assert [t["name"] for t in client.requests[0]["tools"]] == reporting.TOOLS
    assert sorted(reporting.toolbox(repo).scripts) == [
        "previous_results",
        "spec_rows_since",
    ]


def test_tag_map_agent_may_pr_only_the_tag_map(repo: Path) -> None:
    from backtester.agents import tag_map

    box = tag_map.toolbox(repo)
    assert box.allow_pr == ("src/backtester/tag_map.toml",)
    assert box._writable("src/backtester/tag_map.toml", via_pr=True)
    with pytest.raises(PermissionError):
        box._writable("src/backtester/fundamentals.py", via_pr=True)
    client = FakeClient([_text("nothing to propose")])
    rec = tag_map.run(repo, ["revenue"], client=client, model="m")
    assert "revenue" in rec["user_prompt"] and "candidate_tags" in rec["user_prompt"]


def test_triage_agent_flags_a_four_sigma_month(repo: Path, monkeypatch) -> None:
    from datetime import date

    from backtester import config
    from backtester.agents import triage

    cfg = config.load(Path(__file__).resolve().parent.parent / "config.toml")
    cfg = cfg.with_(data=repo / "data")
    months = [date(2020, m, 28) for m in range(1, 13)]
    rets = [0.01, -0.01] * 5 + [0.01, 0.50]  # the last month is the outlier
    pl.DataFrame({"month": months, "ret_gross": rets}).write_parquet(
        repo / "data" / "processed" / "long_short_momentum.parquet"
    )
    hits = triage.anomalous_months(cfg, ["momentum"])
    assert hits["month"].to_list() == [date(2020, 12, 28)] and hits["sigma"][0] > 3
    client = FakeClient([_text("issue url")])
    rec = triage.run(repo, "momentum 2020-12 +50%", client=client, model="m")
    assert "open_issue" in [t["name"] for t in client.requests[0]["tools"]]
    assert "open_pr" not in [t["name"] for t in client.requests[0]["tools"]]
    assert rec["final_output"] == "issue url"


def test_universe_change_agent_has_web_search_and_the_parser_allowance(
    repo: Path,
) -> None:
    from backtester.agents import universe_change

    client = FakeClient([_text("pr")])
    universe_change.run(
        repo, "KeyError: 'Date'", "data/raw/x.html", client=client, model="m"
    )
    sent = client.requests[0]["tools"]
    assert sent[-1]["type"] == "web_search_20260209"
    assert universe_change.toolbox(repo).allow_pr == ("src/backtester/universe.py",)


def test_drift_agent_sees_recompute_views(repo: Path) -> None:
    from backtester.agents import drift

    rec_dir = repo / "data" / "processed" / "recompute"
    rec_dir.mkdir()
    pl.DataFrame(
        {"month": ["2026-01-31"], "ticker": ["A"], "ret": [0.2]}
    ).write_parquet(rec_dir / "returns_monthly.parquet")
    box = drift.toolbox(repo)
    out = json.loads(
        box.duckdb_query(
            "SELECT a.ret AS inc, b.ret AS full FROM processed_returns_monthly a "
            "JOIN processed_recompute_returns_monthly b USING (month, ticker)"
        )
    )
    assert out["rows"] == [[0.1, 0.2]]
    client = FakeClient([_text("issue")])
    rec = drift.run(repo, "decisions/drift/2026-09-14.md", client=client, model="m")
    assert "universe_monthly" in rec["user_prompt"]
