"""What did not work is generated from the log: superseded rows and
abandoned diagnostics are listed with the commit that replaced them;
the current row of every key is not."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from backtester import research_log as rl

COLS = ["timestamp", "factor", "signal", "weighting", "holding_months", "n_deciles"]


def _spec(path: Path, rows: list[tuple]) -> Path:
    df = pl.DataFrame(
        [
            {
                **dict(zip(COLS, r[:6], strict=True)),
                "sharpe_net": r[6],
                "note": r[7],
            }
            for r in rows
        ]
    )
    df.write_csv(path)
    return path


def _t(h: int, m: int = 0) -> str:
    return f"2026-09-11T{h:02d}:{m:02d}:00+00:00"


def test_superseded_and_abandoned_rows_are_listed_with_their_commit(
    tmp_path: Path,
) -> None:
    spec = _spec(
        tmp_path / "spec.csv",
        [
            (_t(12, 3), "momentum", "m", "ew", 1, 10, 0.37, "first run no-sector"),
            (
                _t(12, 8),
                "momentum",
                "m",
                "ew",
                1,
                10,
                -0.05,
                "after cleaning no-sector",
            ),
            (_t(12, 36), "bp", "book_to_price", "ew", 1, 10, 0.44, "diagnostic bp"),
            (_t(12, 45), "momentum", "m", "ew", 1, 10, 0.04, "base"),
            (_t(12, 46), "momentum", "m", "ew", 1, 10, -0.05, "sensitivity no-sector"),
        ],
    )
    commits = [
        rl.Commit(
            "aaa1111", datetime(2026, 9, 11, 12, 5, tzinfo=UTC), "Prices cleaned"
        ),
        rl.Commit("bbb2222", datetime(2026, 9, 11, 13, 0, tzinfo=UTC), "Phase 6 done"),
    ]
    text = rl.build_what_did_not_work(spec, commits)

    # The first no-sector momentum run was superseded by the second; the
    # commit right after it is the price-cleaning one.
    assert '"first run no-sector" → aaa1111 "Prices cleaned"' in text
    # The diagnostic factor never became reported: abandoned.
    assert "## Abandoned" in text and '"diagnostic bp" → bbb2222' in text
    # The second no-sector run is superseded too, by the 12:46 sensitivity.
    assert '"after cleaning no-sector" → bbb2222' in text
    # Current rows (the last of each key) are not listed.
    assert '"base"' not in text and '"sensitivity no-sector"' not in text


def test_current_row_of_each_key_is_kept_and_counts_are_right(tmp_path: Path) -> None:
    spec = _spec(
        tmp_path / "spec.csv",
        [
            (_t(12, 3), "momentum", "m", "ew", 1, 10, 0.37, "first no-sector"),
            (_t(12, 8), "momentum", "m", "ew", 1, 10, -0.05, "second no-sector"),
            (_t(12, 45), "value", "v", "ew", 1, 10, 0.50, "base"),
        ],
    )
    c = rl.classify(pl.read_csv(spec, infer_schema_length=0))
    assert c["status"].to_list() == ["superseded", "current", "current"]
    text = rl.build_what_did_not_work(spec, [])
    assert "3 logged specifications; 1 were superseded or abandoned" in text
    assert "no commit after it yet" in text


def test_git_log_reads_the_real_repo(repo_root: Path) -> None:
    commits = rl.git_log(repo_root)
    assert commits and commits[0].when < commits[-1].when
    assert all(len(c.sha) >= 7 for c in commits)


def test_build_keeps_the_agent_section_below_the_marker(
    tmp_path: Path, repo_root: Path, monkeypatch
) -> None:
    (tmp_path / "reports").mkdir()
    spec = _spec(
        tmp_path / "reports" / "specifications.csv",
        [(_t(12, 3), "bp", "book_to_price", "ew", 1, 10, 0.44, "diagnostic bp")],
    )
    out = tmp_path / "reports" / "what_did_not_work.md"
    out.write_bytes(b"old table\n" + rl.MARKER.encode() + b"\n\n## Agent notes\nkept\n")
    # The generated part comes from the tmp spec; the git log from the real repo.
    real = rl.git_log
    monkeypatch.setattr(rl, "git_log", lambda root: real(repo_root))
    rl.build(tmp_path, spec)
    text = out.read_text(encoding="utf-8")
    assert "old table" not in text and '"diagnostic bp"' in text
    assert text.endswith(rl.MARKER + "\n\n## Agent notes\nkept\n")
