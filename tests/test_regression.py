"""The momentum-UMD correlation must not drift as the pipeline changes
(BUILD_PLAN 6.3): the value at the last base run is a fixture, and a
rebuild has to land within its tolerance and above the brief's bar."""

import json
from pathlib import Path

import polars as pl
import pytest

from backtester import run


def test_momentum_umd_correlation_matches_the_stored_baseline(repo_root: Path) -> None:
    base = json.loads((repo_root / "tests/fixtures/momentum_baseline.json").read_text())
    ls_path = repo_root / "data/processed/long_short_momentum.parquet"
    fr_path = repo_root / "data/interim/french_monthly.parquet"
    if not (ls_path.exists() and fr_path.exists()):
        pytest.skip("processed data not on this machine")
    v = run.validate(
        pl.read_parquet(ls_path), pl.read_parquet(fr_path), base["benchmark"]
    )
    assert v["corr"] is not None
    assert abs(v["corr"] - base["corr"]) <= base["tolerance"], (v["corr"], base["corr"])
    assert v["corr"] > base["threshold"]
