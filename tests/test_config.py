"""config.toml is the single source of truth; the loader must read it and
refuse values that would fail silently downstream."""

from datetime import date
from pathlib import Path

import pytest

from backtester import config


def test_repo_config_loads(repo_root: Path) -> None:
    cfg = config.load(repo_root / "config.toml")
    assert cfg.start == date(2010, 1, 31)
    assert cfg.end > cfg.start
    assert cfg.weighting in config.WEIGHTINGS
    assert cfg.base_bps in cfg.sensitivity_bps
    assert cfg.momentum_window == (12, 1)
    assert cfg.lag_days == 1
    assert cfg.asof_buffer_days == 1


def test_with_returns_modified_copy(repo_root: Path) -> None:
    cfg = config.load(repo_root / "config.toml")
    cw = cfg.with_(weighting="cw", base_bps=25.0)
    assert cw.weighting == "cw" and cw.base_bps == 25.0
    assert cfg.weighting == "ew" and cfg.base_bps == 10.0


@pytest.mark.parametrize(
    "changes",
    [
        {"weighting": "vw"},
        {"end": date(2009, 12, 31)},
        {"winsor": (0.99, 0.01)},
        {"momentum_window": (1, 12)},
        {"n_deciles": 1},
        {"lag_days": -1},
    ],
)
def test_invalid_values_are_refused(repo_root: Path, changes: dict) -> None:
    cfg = config.load(repo_root / "config.toml")
    with pytest.raises(ValueError):
        cfg.with_(**changes)


def test_config_hash_is_stable_and_sensitive(repo_root: Path) -> None:
    a = config.load(repo_root / "config.toml")
    b = config.load(repo_root / "config.toml")
    assert config.config_hash(a) == config.config_hash(b)
    assert len(config.config_hash(a)) == 12
    assert config.config_hash(a) != config.config_hash(a.with_(base_bps=25.0))


def test_validation_thresholds_come_from_config(repo_root: Path) -> None:
    cfg = config.load(repo_root / "config.toml")
    v = dict(cfg.validation)
    assert v["momentum"] == 0.70 and v["beta"] == 0.50
    assert set(v) >= {"momentum", "value", "quality", "hml_replica", "rmw_replica"}
