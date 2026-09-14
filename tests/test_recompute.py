"""The recompute comparison (BUILD_PLAN 10.4): equal tables pass, a
numeric difference beyond 1e-10 or a text difference is named, stamp
columns and row order are ignored."""

from pathlib import Path

import polars as pl

from backtester import recompute


def _write(d: Path, name: str, df: pl.DataFrame) -> None:
    d.mkdir(parents=True, exist_ok=True)
    df.write_parquet(d / f"{name}.parquet")


def test_compare_ignores_stamps_and_order_but_not_values(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    base = pl.DataFrame({"k": [1, 2, 3], "x": [0.1, 0.2, 0.3], "s": ["p", "q", "r"]})
    _write(a, "t", base.with_columns(pl.lit("2026-01-01").alias("as_of")))
    _write(b, "t", base.reverse().with_columns(pl.lit("2026-09-14").alias("as_of")))
    assert recompute.compare(a, b) == []

    _write(b, "t", base.with_columns(pl.col("x") + 1e-12))
    assert recompute.compare(a, b) == []  # within tolerance

    _write(b, "t", base.with_columns(pl.col("x") + 1e-6))
    (problem,) = recompute.compare(a, b)
    assert problem.startswith("t.parquet.x: 3 rows differ, first at row 0: 0.1 against")

    _write(b, "t", base.with_columns(pl.lit("z").alias("s")))
    (problem,) = recompute.compare(a, b)
    assert problem.startswith("t.parquet.s: 3 rows differ")

    _write(b, "t", base.head(2))
    assert recompute.compare(a, b) == ["t.parquet: 3 rows against 2"]
