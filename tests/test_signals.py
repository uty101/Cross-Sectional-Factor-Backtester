from datetime import date

import polars as pl
import pytest

from backtester import signals

M = date(2020, 1, 31)


def test_normalise_is_sector_relative_and_winsorised() -> None:
    raw = pl.DataFrame(
        {
            "month": [M] * 12,
            "ticker": [f"T{i}" for i in range(12)],
            "value": [
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                10.0,
                20.0,
                30.0,
                40.0,
                50.0,
                600.0,
            ],
        }
    )
    sectors = pl.DataFrame(
        {"ticker": [f"T{i}" for i in range(12)], "sector": ["A"] * 6 + ["B"] * 6}
    )
    z = signals.normalise(raw, sectors, (0.0, 1.0))
    a = z.filter(pl.col("ticker").is_in([f"T{i}" for i in range(6)]))["z"]
    b = z.filter(pl.col("ticker").is_in([f"T{i}" for i in range(6, 12)]))["z"]
    assert abs(a.mean()) < 1e-12 and abs(b.mean()) < 1e-12
    assert abs(a.std() - 1) < 1e-12 and abs(b.std() - 1) < 1e-12
    # Winsorising at the 90th percentile pulls the 600 in.
    zw = signals.normalise(raw, None, (0.0, 0.9))
    assert (
        zw.filter(pl.col("ticker") == "T11")["z"][0]
        < z.filter(pl.col("ticker") == "T11")["z"][0] * 10
    )


def test_small_sectors_fall_back_to_the_cross_section() -> None:
    raw = pl.DataFrame(
        {
            "month": [M] * 8,
            "ticker": [f"T{i}" for i in range(8)],
            "value": [float(i) for i in range(8)],
        }
    )
    sectors = pl.DataFrame(
        {"ticker": [f"T{i}" for i in range(8)], "sector": ["A"] * 6 + ["B"] * 2}
    )
    z = signals.normalise(raw, sectors, (0.0, 1.0))
    plain = signals.normalise(raw, None, (0.0, 1.0))
    for t in ("T6", "T7"):
        assert (
            z.filter(pl.col("ticker") == t)["z"][0]
            == plain.filter(pl.col("ticker") == t)["z"][0]
        )


def test_composite_requires_every_component() -> None:
    z1 = pl.DataFrame(
        {"month": [M] * 3, "ticker": ["A", "B", "C"], "z": [1.0, 0.0, -1.0]}
    )
    z2 = pl.DataFrame({"month": [M] * 2, "ticker": ["A", "B"], "z": [-1.0, 1.0]})
    c = signals.composite([z1, z2])
    assert c["ticker"].sort().to_list() == ["A", "B"]
    assert abs(c["z"].mean()) < 1e-12


def test_volatility_is_negative_annualised_std_at_month_end() -> None:
    dates = [date(2020, 1, d) for d in range(1, 32) if date(2020, 1, d).weekday() < 5]
    dr = pl.DataFrame(
        {
            "date": dates,
            "ticker": ["X"] * len(dates),
            "ret": [0.01, -0.01] * (len(dates) // 2) + [0.01] * (len(dates) % 2),
        }
    )
    me = pl.DataFrame({"month": [M], "t": [dates[-1]]})
    v = signals.volatility(dr, me, window=10)
    assert v.height == 1
    assert v["value"][0] < 0


def test_normalise_refuses_a_value_available_after_its_month() -> None:

    raw = pl.DataFrame(
        {
            "month": [date(2020, 1, 31)] * 3,
            "ticker": ["A", "B", "C"],
            "value": [1.0, 2.0, 3.0],
            "available_from": [date(2020, 1, 2), date(2020, 1, 31), date(2020, 2, 1)],
        }
    )
    with pytest.raises(AssertionError, match="invariant 1"):
        signals.normalise(raw, None, (0.01, 0.99))
    ok = raw.filter(pl.col("ticker") != "C")
    assert signals.normalise(ok, None, (0.01, 0.99)).height == 2
