"""FIX_PLAN F1: the CIK audit classifies every member with no assets."""

import importlib.util
from datetime import date
from pathlib import Path

import polars as pl

_SPEC = importlib.util.spec_from_file_location(
    "audit_cik_map", Path(__file__).parents[1] / "scripts" / "audit_cik_map.py"
)
audit_cik_map = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_cik_map)

MONTH = date(2015, 12, 31)


def _sub(*rows: tuple[int, str, str, date]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"adsh": f"{c}-{f}-{d}", "cik": c, "name": n, "form": f, "filed": d}
            for c, n, f, d in rows
        ],
        schema={
            "adsh": pl.Utf8,
            "cik": pl.Int64,
            "name": pl.Utf8,
            "form": pl.Utf8,
            "filed": pl.Date,
        },
    )


def _fixture():
    membership = pl.DataFrame(
        {
            "ticker": ["OK", "WRONG", "FOR", "NONE", "OTH", "GONE"],
            "security": [
                "Okay Corp",
                "Wrongly Mapped Inc",
                "Foreign Filer plc",
                "Nowhere Bank",
                "Other Industries",
                "Gone Co",
            ],
            "start": [date(2000, 1, 1)] * 6,
            "end": [None, None, None, date(2020, 1, 1), None, date(2012, 1, 1)],
        },
        schema={
            "ticker": pl.Utf8,
            "security": pl.Utf8,
            "start": pl.Date,
            "end": pl.Date,
        },
    )
    panel = pl.DataFrame(
        {
            "month": [MONTH] * 5,
            "ticker": ["OK", "WRONG", "FOR", "NONE", "OTH"],
            "assets": [1.0, None, None, None, None],
        }
    )
    cik_log = pl.DataFrame(
        {
            "ticker": ["OK", "WRONG", "FOR", "NONE", "OTH"],
            "cik": [1, None, None, None, 5],
            "method": [
                "sec company_tickers",
                "unmatched",
                "unmatched",
                "unmatched",
                "name exact",
            ],
            "matched": ["OKAY", "WRONGLY MAPPED", "FOREIGN FILER", "NOWHERE", "OTHER"],
        },
        schema={
            "ticker": pl.Utf8,
            "cik": pl.Int64,
            "method": pl.Utf8,
            "matched": pl.Utf8,
        },
    )
    sub = _sub(
        (1, "OKAY CORP", "10-K", date(2015, 2, 1)),
        (2, "WRONGLY MAPPED INC", "10-K", date(2015, 2, 1)),
        (2, "WRONGLY MAPPED INC", "10-Q", date(2015, 8, 1)),
        (3, "FOREIGN FILER PLC", "20-F", date(2015, 4, 1)),
        (5, "OTHER INDUSTRIES", "10-K", date(2015, 3, 1)),
        # A filer whose only 10-K is outside the window does not count.
        (4, "NOWHERE BANK", "10-K", date(2012, 3, 1)),
    )
    return panel, membership, cik_log, sub


def test_audit_produces_the_four_classes() -> None:
    rows, summary = audit_cik_map.audit(*_fixture(), months=[MONTH])
    got = dict(zip(rows["ticker"], rows["class"], strict=True))
    assert got == {
        "WRONG": "map_wrong",
        "FOR": "foreign_filer",
        "NONE": "no_xbrl",
        "OTH": "other",
    }
    # The map's miss is named: the filer with 10-K/10-Q filings in the window.
    wrong = rows.filter(pl.col("ticker") == "WRONG").row(0, named=True)
    assert wrong["best_cik"] == 2 and wrong["assigned_cik"] is None
    # A member with assets and a name not in the index at that month are absent.
    assert "OK" not in got and "GONE" not in got
    counts = dict(zip(summary["class"], summary["n"], strict=True))
    assert counts == {"map_wrong": 1, "foreign_filer": 1, "no_xbrl": 1, "other": 1}
    assert sorted(summary["class"].to_list()) == sorted(audit_cik_map.CLASSES)


def test_summary_has_every_class_for_every_month_even_when_zero() -> None:
    panel, membership, cik_log, sub = _fixture()
    _, summary = audit_cik_map.audit(
        panel.with_columns(pl.lit(1.0).alias("assets")),
        membership,
        cik_log,
        sub,
        [MONTH],
    )
    assert summary.height == len(audit_cik_map.CLASSES)
    assert summary["n"].sum() == 0
