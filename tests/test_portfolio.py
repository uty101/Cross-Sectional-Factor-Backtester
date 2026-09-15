"""Invariants 5 (momentum skips the last month), 6 (turnover against drifted
weights) and 8 (every run is logged)."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from backtester import config, portfolio, signals

M1, M2, M3 = date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31)


@pytest.fixture
def cfg(repo_root: Path, tmp_path: Path) -> config.Config:
    return config.load(repo_root / "config.toml").with_(
        n_deciles=2,
        min_names=0,  # synthetic cross-sections of a handful of names
        specifications=tmp_path / "specs.csv",
        base_bps=10.0,
    )


def test_momentum_skips_most_recent_month() -> None:
    months = [date(2019, m, 28) for m in range(1, 13)] + [date(2020, 1, 28)]
    months = [pl.Series([d]).dt.month_end()[0] for d in months]
    px = [float(100 + i) for i in range(len(months))]
    monthly = pl.DataFrame(
        {"month": months, "ticker": ["X"] * len(months), "px_me": px}
    )
    mom = signals.momentum_12_1(monthly, back=12, skip=1)
    assert mom.height == 1
    r = mom.row(0, named=True)
    assert r["month"] == months[-1]
    # px(t-1) / px(t-12) - 1: months[11] / months[0]; month t (index 12) unused.
    assert abs(r["value"] - (px[11] / px[0] - 1)) < 1e-12
    assert r["value"] != px[12] / px[0] - 1


def test_turnover_against_hand_computed_case() -> None:
    w_prev = {"A": 0.5, "B": 0.5}
    rets = {"A": 0.10, "B": -0.10}
    w_minus = portfolio.drift(w_prev, rets)  # A: 0.55/1.0, B: 0.45/1.0
    assert abs(w_minus["A"] - 0.55) < 1e-12 and abs(w_minus["B"] - 0.45) < 1e-12
    w_new = {"A": 0.5, "C": 0.5}
    # |0.5-0.55| + |0-0.45| + |0.5-0| = 0.05 + 0.45 + 0.5 = 1.0 -> half = 0.5
    assert abs(portfolio.turnover(w_new, w_minus) - 0.5) < 1e-12
    # Rebalancing to the same drifted weights costs nothing.
    assert portfolio.turnover(w_minus, w_minus) == 0.0


def test_deciles_are_ordinal_and_balanced() -> None:
    z = pl.DataFrame(
        {
            "month": [M1] * 10,
            "ticker": list("ABCDEFGHIJ"),
            "z": [float(i) for i in range(10)],
        }
    )
    d = portfolio.assign_deciles(z, 5)
    assert d.sort("z")["decile"].to_list() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_run_logs_specification(cfg: config.Config) -> None:
    z = pl.DataFrame(
        {"month": [M1] * 4, "ticker": list("ABCD"), "z": [-1.0, -0.5, 0.5, 1.0]}
    )
    rets = pl.DataFrame(
        {"month": [M1] * 4, "ticker": list("ABCD"), "ret_fwd": [0.0, 0.02, 0.04, 0.06]}
    )
    assert portfolio.count_specifications(cfg.specifications) == 0
    res = portfolio.backtest(z, rets, cfg, factor="test", note="unit")
    assert portfolio.count_specifications(cfg.specifications) == 1
    portfolio.backtest(z, rets, cfg, factor="test", note="again")
    assert portfolio.count_specifications(cfg.specifications) == 2
    log = pl.read_csv(cfg.specifications)
    assert log.columns == portfolio.SPEC_COLUMNS
    assert log["note"].to_list() == ["unit", "again"]
    assert log["cost_bps"][0] == 10.0
    # Long-short: decile 2 (C, D) minus decile 1 (A, B) = 0.05 - 0.01.
    ls = res.long_short.row(0, named=True)
    assert abs(ls["ret_gross"] - 0.04) < 1e-12
    # First month builds both legs from cash: half-sum 0.5 per leg -> 1.0,
    # and every dollar traded (2.0 of notional) pays 10 bp.
    assert abs(ls["turnover"] - 1.0) < 1e-12
    assert abs(ls["ret_net"] - (0.04 - 0.001 * 2.0)) < 1e-12


def test_costs_scale_with_turnover_and_names_without_return_are_dropped(
    cfg: config.Config,
) -> None:
    z = pl.DataFrame(
        {
            "month": [M1] * 4 + [M2] * 4,
            "ticker": list("ABCD") * 2,
            "z": [-1.0, -0.5, 0.5, 1.0] * 2,  # same ranks both months
        }
    )
    rets = pl.DataFrame(
        {
            "month": [M1] * 4 + [M2] * 4,
            "ticker": list("ABCD") * 2,
            "ret_fwd": [0.0, 0.0, 0.10, 0.10, 0.0, 0.0, None, 0.10],
        }
    )
    res = portfolio.backtest(z, rets, cfg, factor="test")
    feb = res.long_short.filter(pl.col("month") == M2).row(0, named=True)
    # Long leg drifted from (C .5, D .5) with equal returns -> still (.5, .5);
    # target is (.5, .5): zero turnover in Feb.
    assert feb["turnover"] == 0.0
    # C has no forward return in Feb: long leg return is D's alone.
    assert abs(feb["ret_gross"] - 0.10) < 1e-12
    dec2 = res.deciles.filter((pl.col("month") == M2) & (pl.col("decile") == 2)).row(
        0, named=True
    )
    assert dec2["n_unpriced"] == 1


def test_holding_period_longer_than_a_month_only_rebalances_every_k(
    cfg: config.Config,
) -> None:
    cfg = cfg.with_(holding_months=2)
    months = [M1, M2, M3]
    z = pl.DataFrame(
        {
            "month": [m for m in months for _ in range(4)],
            "ticker": list("ABCD") * 3,
            "z": [-1.0, -0.5, 0.5, 1.0, 1.0, 0.5, -0.5, -1.0, -1.0, -0.5, 0.5, 1.0],
        }
    )
    rets = pl.DataFrame(
        {
            "month": z["month"],
            "ticker": z["ticker"],
            "ret_fwd": [0.01] * 12,
        }
    )
    res = portfolio.backtest(z, rets, cfg, factor="test")
    to = res.long_short.sort("month")["turnover"].to_list()
    assert to[0] == 1.0  # formed in Jan
    assert to[1] == 0.0  # Feb: held, though the signal flipped
    assert to[2] == 0.0  # Mar: re-formed, and the ranks match Jan's -> no trades


def test_cap_weighting_uses_caps_within_decile(cfg: config.Config) -> None:
    z = pl.DataFrame(
        {"month": [M1] * 4, "ticker": list("ABCD"), "z": [1.0, 2.0, 3.0, 4.0]}
    )
    caps = pl.DataFrame(
        {"month": [M1] * 4, "ticker": list("ABCD"), "cap": [1.0, 3.0, 1.0, 3.0]}
    )
    d = portfolio.assign_deciles(z, 2)
    w = portfolio.weights(d, caps, "cw").sort("ticker")
    assert w["w"].to_list() == [0.25, 0.75, 0.25, 0.75]
    ew = portfolio.weights(d, None, "ew").sort("ticker")
    assert ew["w"].to_list() == [0.5, 0.5, 0.5, 0.5]


def test_validation_compares_formation_month_with_the_month_earned() -> None:
    from backtester import run

    ls = pl.DataFrame(
        {
            "month": [M1, M2, M3],
            "ret_gross": [0.05, -0.05, 0.02],
            "ret_net": [0.05, -0.05, 0.02],
        }
    )
    m4 = date(2020, 4, 30)
    french = pl.DataFrame(
        {"month": [M1, M2, M3, m4], "umd": [-0.05, 0.05, -0.05, 0.02]}
    )
    v = run.validate(ls, french, "umd")
    # Row M1 earned in Feb pairs with umd(M2) = +0.05 and so on: correlation 1.
    assert v["months"] == 3 and abs(v["corr"] - 1.0) < 1e-12


def test_specification_row_carries_config_hash_and_commit(cfg: config.Config) -> None:
    z = pl.DataFrame({"month": [M1] * 2, "ticker": ["A", "B"], "z": [-1.0, 1.0]})
    rets = pl.DataFrame(
        {"month": [M1] * 2, "ticker": ["A", "B"], "ret_fwd": [0.0, 0.1]}
    )
    portfolio.backtest(z, rets, cfg, factor="test")
    log = pl.read_csv(cfg.specifications)
    assert log["config_hash"][0] == config.config_hash(cfg)
    assert log["git_commit"][0] and log["git_commit"][0] != ""


def test_older_log_is_widened_without_losing_rows(cfg: config.Config) -> None:
    # A log written before config_hash and git_commit existed: two rows
    # under the 16-column header. Appending a third must keep both, keep
    # their values, and leave the new columns blank for them.
    old_cols = portfolio.SPEC_COLUMNS[:-2]
    cfg.specifications.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.specifications, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(old_cols) + "\n")
        f.write(
            "t1,momentum,m,ew,10.0,1,M,1,0.01,0.99,10,2010-01-31,2026-08-31,0.1,0.0,first\n"
        )
        f.write(
            "t2,value,v,ew,10.0,1,M,1,0.01,0.99,10,2010-01-31,2026-08-31,0.5,0.4,second\n"
        )
    assert portfolio.count_specifications(cfg.specifications) == 2
    z = pl.DataFrame({"month": [M1] * 2, "ticker": ["A", "B"], "z": [-1.0, 1.0]})
    rets = pl.DataFrame(
        {"month": [M1] * 2, "ticker": ["A", "B"], "ret_fwd": [0.0, 0.1]}
    )
    portfolio.backtest(z, rets, cfg, factor="test")
    assert portfolio.count_specifications(cfg.specifications) == 3
    log = pl.read_csv(cfg.specifications)
    assert log.columns == portfolio.SPEC_COLUMNS
    assert log["note"].to_list()[:2] == ["first", "second"]
    assert log["config_hash"][0] is None and log["config_hash"][2] is not None


def test_a_month_below_min_names_forms_no_portfolio(cfg: config.Config) -> None:
    thin = cfg.with_(min_names=6, n_deciles=2)
    m2 = date(2020, 2, 29)
    z = pl.DataFrame(
        {
            "month": [M1] * 8 + [m2] * 4,
            "ticker": list("ABCDEFGH") + list("ABCD"),
            "z": [float(i) for i in range(8)] + [1.0, 2.0, 3.0, 4.0],
        }
    )
    rets = pl.DataFrame(
        {
            "month": [M1] * 8 + [m2] * 4,
            "ticker": list("ABCDEFGH") + list("ABCD"),
            "ret_fwd": [0.01] * 12,
        }
    )
    res = portfolio.backtest(z, rets, thin, factor="test")
    assert res.long_short["month"].to_list() == [M1]  # February had 4 names


def test_specification_kind_is_read_off_the_note_and_backfilled(
    cfg: config.Config,
) -> None:
    """FIX_PLAN F4: every row is a candidate or a diagnostic; a log written
    before the column existed is classified the same way when widened."""
    z = pl.DataFrame(
        {"month": [M1] * 4, "ticker": list("ABCD"), "z": [-1.0, -0.5, 0.5, 1.0]}
    )
    rets = pl.DataFrame(
        {"month": [M1] * 4, "ticker": list("ABCD"), "ret_fwd": [0.0, 0.02, 0.04, 0.06]}
    )
    for note in ("base", "sensitivity cw", "French replication", "diagnostic bp"):
        portfolio.backtest(z, rets, cfg, factor="test", note=note)
    log = pl.read_csv(cfg.specifications)
    assert log["kind"].to_list() == ["candidate"] + ["diagnostic"] * 3
    assert portfolio.count_specifications(cfg.specifications) == 4
    assert portfolio.count_specifications(cfg.specifications, "candidate") == 1
    # An old log without the column: the widening fills kind from the note.
    old = cfg.specifications.read_text(encoding="utf-8").splitlines()
    head = old[0].rsplit(",kind", 1)[0]
    body = [line.rsplit(",", 1)[0] for line in old[1:]]
    cfg.specifications.write_text("\n".join([head, *body]) + "\n", encoding="utf-8")
    portfolio.backtest(z, rets, cfg, factor="test", note="post-F3")
    log = pl.read_csv(cfg.specifications)
    assert log["kind"].to_list() == [
        "candidate",
        "diagnostic",
        "diagnostic",
        "diagnostic",
        "candidate",
    ]
