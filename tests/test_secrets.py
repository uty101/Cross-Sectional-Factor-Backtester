"""FIX_PLAN_2 G1: keys load from ``.env``, ``require`` names the Part A
step, and the ``secrets`` command never prints a value."""

import pytest

from backtester import cli, config


def test_secret_reads_a_tmp_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("X", raising=False)
    (tmp_path / ".env").write_text("# comment\nX=1\n", encoding="utf-8")
    assert config.secret("X", tmp_path) == "1"
    assert config.secret("Y", tmp_path) is None


def test_require_names_the_part_a_step(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("Y", raising=False)
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Part A"):
        config.require("Y", tmp_path)
    with pytest.raises(RuntimeError, match="step A2"):
        config.require("TIINGO_API_KEY", tmp_path)
    (tmp_path / ".env").write_text("TIINGO_API_KEY=tok\n", encoding="utf-8")
    assert config.require("TIINGO_API_KEY", tmp_path) == "tok"


def test_secrets_command_prints_no_value(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "TIINGO_API_KEY=supersecrettoken\n", encoding="utf-8"
    )
    lines = cli.secrets_report(tmp_path)
    assert len(lines) == len(config.SECRET_NAMES) + 1
    for name in config.SECRET_NAMES:
        assert any(line.startswith(f"{name}: ") for line in lines)
    assert any(line.startswith("TIINGO_API_KEY: set") for line in lines)
    joined = "\n".join(lines)
    assert "=" not in joined
    assert "super" not in joined
    assert "gh auth status" in joined
    # and through the CLI, on the real cwd
    assert cli.main(["secrets"]) == 0
    assert "=" not in capsys.readouterr().out
