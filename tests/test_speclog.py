"""FIX_PLAN_2 G2: a trial is a distinct specification key, not a row."""

from pathlib import Path

import polars as pl

from backtester import config, speclog

BASE = {
    "factor": "value",
    "signal": "book_to_price+earnings_yield",
    "weighting": "ew",
    "cost_bps": "10.0",
    "lag_days": "1",
    "rebalance": "M",
    "holding_months": "1",
    "winsor_lo": "0.01",
    "winsor_hi": "0.99",
    "n_deciles": "10",
    "start": "2010-01-31",
    "end": "2026-08-31",
    "sharpe_gross": "0.1",
    "sharpe_net": "0.0",
    "config_hash": "",
    "kind": "",
    "sector_neutral": "",
    "variant": "",
    "spec_key": "",
}


def _write(path: Path, rows: list[dict]) -> None:
    cols = [c for c in speclog.SPEC_COLUMNS if c != "spec_key"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(r.get(c, "") for c in cols) + "\n")


def test_five_rows_two_keys_one_candidate(tmp_path: Path) -> None:
    log = tmp_path / "specifications.csv"
    rows = [
        # the same base spec three times, under three commits
        {**BASE, "timestamp": "t1", "note": "base", "git_commit": "aaa"},
        {**BASE, "timestamp": "t2", "note": "base post-F3", "git_commit": "bbb"},
        {**BASE, "timestamp": "t3", "note": "base post-F3 tie", "git_commit": "ccc"},
        # one sensitivity, twice
        {**BASE, "timestamp": "t4", "note": "sensitivity cw", "weighting": "cw"},
        {
            **BASE,
            "timestamp": "t5",
            "note": "sensitivity cw post-F3",
            "weighting": "cw",
        },
    ]
    _write(log, rows)
    assert speclog.count_specifications(log) == 5
    assert speclog.count_trials(log) == 2
    assert speclog.count_trials(log, "candidate") == 1
    assert speclog.count_trials(log, "diagnostic") == 1
    latest = speclog.latest_per_key(log)
    assert [r["timestamp"] for r in latest] == ["t3", "t5"]


def test_same_spec_under_two_commits_is_one_trial() -> None:
    a = {**BASE, "git_commit": "aaa", "note": "base", "timestamp": "t1"}
    b = {**BASE, "git_commit": "bbb", "note": "base post-F3", "timestamp": "t2"}
    assert speclog.spec_key(a) == speclog.spec_key(b)
    # and the key is blind to how a number is spelt
    assert speclog.spec_key({**a, "cost_bps": "10"}) == speclog.spec_key(a)
    assert speclog.spec_key({**a, "cost_bps": "20"}) != speclog.spec_key(a)


def test_sector_flag_and_variant_are_backfilled_from_the_note(tmp_path: Path) -> None:
    log = tmp_path / "specifications.csv"
    rows = [
        {**BASE, "timestamp": "t1", "note": "base"},
        {**BASE, "timestamp": "t2", "note": "sensitivity nosector no-sector"},
        {**BASE, "timestamp": "t3", "note": "sensitivity terminal"},
        {**BASE, "timestamp": "t4", "note": "base", "signal": "doc_similarity"},
        {
            **BASE,
            "timestamp": "t5",
            "note": "sensitivity jaccard",
            "signal": "doc_similarity",
        },
    ]
    _write(log, rows)
    read = speclog.read(log)
    assert [r["sector_neutral"] for r in read] == ["1", "0", "1", "1", "1"]
    assert [r["variant"] for r in read] == ["", "", "terminal", "cosine", "jaccard"]
    assert speclog.count_trials(log) == 5
    # upgrading writes the columns to disk without touching a row's values
    speclog.upgrade(log)
    disk = pl.read_csv(log, infer_schema_length=0)
    assert disk.columns == speclog.SPEC_COLUMNS
    assert disk.height == 5
    assert disk["note"].to_list() == [r["note"] for r in rows]
    assert disk["spec_key"].n_unique() == 5


def test_logging_writes_the_key_from_the_run_arguments(tmp_path: Path) -> None:
    cfg = config.load("config.toml").with_(specifications=tmp_path / "s.csv")
    log = cfg.specifications
    speclog.log_specification(log, cfg, factor="value", signal="bp", note="base")
    speclog.log_specification(
        log, cfg, factor="value", signal="bp", note="base", sector_neutral=False
    )
    speclog.log_specification(
        log, cfg, factor="text_change", signal="doc_similarity", note="base"
    )
    rows = speclog.read(log)
    assert [r["sector_neutral"] for r in rows] == ["1", "0", "1"]
    assert rows[2]["variant"] == cfg.text_similarity
    assert speclog.count_trials(log) == 3
    assert rows[0]["spec_key"] == speclog.spec_key(rows[0])


def test_the_real_log_has_far_fewer_trials_than_rows() -> None:
    """The reason for G2: 335 rows were 12 config hashes."""
    log = Path("reports/specifications.csv")
    if not log.exists():
        return
    rows, trials = speclog.count_specifications(log), speclog.count_trials(log)
    assert 0 < trials < rows
    assert speclog.count_trials(log, "candidate") <= trials


def test_the_same_run_twice_is_one_row(tmp_path: Path, monkeypatch) -> None:
    # FIX_PLAN_3 H4: same key, same commit, same note -> the existing row
    # comes back and nothing is appended. A new note or a new commit is a
    # new row, as before.
    cfg = config.load("config.toml").with_(specifications=tmp_path / "s.csv")
    log = cfg.specifications
    monkeypatch.setattr(speclog, "git_commit", lambda: "abc1234")
    first = speclog.log_specification(log, cfg, factor="value", signal="bp", note="x")
    again = speclog.log_specification(log, cfg, factor="value", signal="bp", note="x")
    assert again == first and speclog.count_specifications(log) == 1
    speclog.log_specification(log, cfg, factor="value", signal="bp", note="x again")
    assert speclog.count_specifications(log) == 2
    monkeypatch.setattr(speclog, "git_commit", lambda: "def5678")
    speclog.log_specification(log, cfg, factor="value", signal="bp", note="x")
    assert speclog.count_specifications(log) == 3
    assert speclog.count_trials(log) == 1
