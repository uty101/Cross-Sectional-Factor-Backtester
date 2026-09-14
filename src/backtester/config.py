"""Load ``config.toml`` into one frozen ``Config``.

Every knob the pipeline reads lives in the TOML file (PLAN.md, invariant 9),
so a sensitivity table is a loop over ``Config`` values rather than an edit
to ``src/``. The loader validates the handful of fields where a bad value
would fail silently downstream.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

WEIGHTINGS = ("ew", "cw")
REBALANCES = ("M",)
SIMILARITIES = ("cosine", "jaccard")  # deterministic scorers only (invariant 10)


@dataclass(frozen=True, slots=True)
class Config:
    # window
    start: date
    end: date
    # universe
    index: str
    # portfolio
    n_deciles: int
    weighting: str
    rebalance: str
    lag_days: int
    holding_months: int
    # costs
    base_bps: float
    sensitivity_bps: tuple[float, ...]
    # signals
    winsor: tuple[float, float]
    momentum_window: tuple[int, int]
    vol_window: int
    beta_window: int
    # fundamentals
    asof_buffer_days: int
    # text
    text_similarity: str
    text_min_words: int
    # paths
    data: Path
    reports: Path
    specifications: Path

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"end {self.end} is not after start {self.start}")
        if self.weighting not in WEIGHTINGS:
            raise ValueError(f"weighting {self.weighting!r} not in {WEIGHTINGS}")
        if self.rebalance not in REBALANCES:
            raise ValueError(f"rebalance {self.rebalance!r} not in {REBALANCES}")
        if self.text_similarity not in SIMILARITIES:
            raise ValueError(
                f"text similarity {self.text_similarity!r} not in {SIMILARITIES}"
            )
        if self.text_min_words < 0:
            raise ValueError("text min_words cannot be negative")
        if self.n_deciles < 2:
            raise ValueError(f"n_deciles must be at least 2, got {self.n_deciles}")
        if self.lag_days < 0 or self.asof_buffer_days < 0:
            raise ValueError("lag_days and asof_buffer_days cannot be negative")
        lo, hi = self.winsor
        if not 0.0 <= lo < hi <= 1.0:
            raise ValueError(
                f"winsor must satisfy 0 <= lo < hi <= 1, got {self.winsor}"
            )
        back, skip = self.momentum_window
        if not 0 <= skip < back:
            raise ValueError(
                f"momentum_window needs 0 <= skip < back, got {back, skip}"
            )

    def with_(self, **changes: object) -> Config:
        """Return a copy with ``changes`` applied; used by the sensitivity loops."""
        from dataclasses import replace

        return replace(self, **changes)  # type: ignore[arg-type]


def config_hash(cfg: Config) -> str:
    """First 12 hex digits of the sha256 of the sorted JSON of every field.

    Two runs with the same hash ran under the same knobs; the spec log
    records it next to the factor and the commit (BUILD_PLAN step 0.3).
    """
    payload = json.dumps(asdict(cfg), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def load(path: str | Path = "config.toml") -> Config:
    """Read ``path`` and return a validated ``Config``."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    window, universe = raw["window"], raw["universe"]
    portfolio, costs = raw["portfolio"], raw["costs"]
    signals, fundamentals, paths = raw["signals"], raw["fundamentals"], raw["paths"]
    text = raw["text"]

    return Config(
        start=date.fromisoformat(window["start"]),
        end=date.fromisoformat(window["end"]),
        index=universe["index"],
        n_deciles=int(portfolio["n_deciles"]),
        weighting=portfolio["weighting"],
        rebalance=portfolio["rebalance"],
        lag_days=int(portfolio["lag_days"]),
        holding_months=int(portfolio["holding_months"]),
        base_bps=float(costs["base_bps"]),
        sensitivity_bps=tuple(float(c) for c in costs["sensitivity_bps"]),
        winsor=(float(signals["winsor"][0]), float(signals["winsor"][1])),
        momentum_window=(
            int(signals["momentum_window"][0]),
            int(signals["momentum_window"][1]),
        ),
        vol_window=int(signals["vol_window"]),
        beta_window=int(signals["beta_window"]),
        asof_buffer_days=int(fundamentals["asof_buffer_days"]),
        text_similarity=text["similarity"],
        text_min_words=int(text["min_words"]),
        data=Path(paths["data"]),
        reports=Path(paths["reports"]),
        specifications=Path(paths["specifications"]),
    )
