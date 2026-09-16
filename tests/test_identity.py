"""FIX_PLAN_3 H2: what yfinance says a removed name's symbol is, against
what the index said it was, and whether the series sits at that filer's
price."""

from datetime import date

import polars as pl

from backtester import identity, prices

HS = date(2008, 1, 1)


def _intervals() -> pl.DataFrame:
    rows = [
        ("HAR", "Harman International", date(1900, 1, 1), date(2017, 3, 15)),
        ("EP", "El Paso Corporation", date(1900, 1, 1), date(2012, 5, 16)),
        ("XYZ", "Xyz Industries", date(2011, 1, 1), date(2015, 1, 1)),
        ("COL", "Rockwell Collins", date(1900, 1, 1), date(2018, 12, 2)),
        ("GONE", "Gone Corporation", date(1900, 1, 1), date(2010, 6, 1)),
        ("AET", "Aetna", date(1900, 1, 1), date(2018, 11, 28)),
        ("GR", "Goodrich Corporation", date(1900, 1, 1), date(2012, 7, 30)),
        ("HOT", "Starwood Hotels", date(1900, 1, 1), date(2016, 9, 23)),
        ("DELL", "Dell", date(1900, 1, 1), date(2013, 10, 29)),
        ("DELL", "Dell Technologies", date(2024, 9, 23), None),
        ("SBNY", "Signature Bank", date(2021, 12, 20), date(2023, 3, 14)),
        ("NOW", "Current Member", date(2000, 1, 1), None),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "ticker": pl.Utf8,
            "security": pl.Utf8,
            "start": pl.Date,
            "end": pl.Date,
        },
        orient="row",
    )


LIVE = {"exchange": "NYQ", "currency": "USD", "quoteType": "EQUITY"}
PLACEHOLDER = {"exchange": "YHD", "quoteType": "MUTUALFUND"}
INFO = {
    # Yahoo's delisted placeholder, numeric short name: no name to test.
    "HAR": {"shortName": "906601", **PLACEHOLDER},
    # A mismatch: another company on the symbol, live.
    "EP": {
        "longName": "Empire Petroleum Corporation",
        "exchange": "ASE",
        "currency": "USD",
        "quoteType": "EQUITY",
    },
    # The right name on a non-USD listing.
    "XYZ": {
        "longName": "Xyz Industries plc",
        "exchange": "LSE",
        "currency": "GBp",
        "quoteType": "EQUITY",
    },
    # yfinance knows nothing (delisted).
    "COL": {},
    "GONE": {},
    # A placeholder that still carries the company's name.
    "AET": {"longName": "Aetna Inc.", **PLACEHOLDER},
    "GR": {"shortName": "1040989", **PLACEHOLDER},
    "HOT": {},
    "DELL": {"longName": "Dell Technologies Inc.", **LIVE},
    # The right name, quoted over the counter since the bank failed.
    "SBNY": {
        "longName": "Signature Bank",
        "exchange": "PNK",
        "currency": "USD",
        "quoteType": "EQUITY",
    },
}


def _first_prices() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ticker": [
                "HAR",
                "EP",
                "XYZ",
                "COL",
                "GONE",
                "AET",
                "GR",
                "HOT",
                "DELL",
                "SBNY",
            ],
            "first_price": [
                date(2013, 1, 17),  # five years into the history: late
                date(2008, 1, 2),
                date(2011, 1, 3),
                date(2012, 8, 2),  # late, inside the membership
                date(2008, 1, 2),
                date(2008, 1, 2),
                date(2008, 1, 2),
                date(2015, 1, 2),  # late, inside the membership, but at the right level
                date(2016, 8, 17),  # late, but after the removed interval ended
                date(2008, 1, 2),
            ],
        },
        schema={"ticker": pl.Utf8, "first_price": pl.Date},
    )


def _levels() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ticker": ["HAR", "EP", "AET", "GR", "HOT"],
            "level": [83.8, 0.007, 1.01, 0.071, 0.99],
            "level_min": [44.9, 0.002, 0.94, 0.03, 0.99],
            "level_max": [91.9, 0.02, 1.05, 0.07, 0.99],
            "n_levels": [3, 3, 9, 3, 1],
        },
        schema=prices.LEVEL_SCHEMA,
    )


def _check(levels=None) -> dict[str, dict]:
    got = prices.identity_check(
        _intervals(), INFO, _first_prices(), None, levels, history_start=HS
    )
    return {r["ticker"]: r for r in got.to_dicts()}


def test_identity_flags_a_mismatch_a_foreign_listing_and_a_late_series() -> None:
    by = _check()
    # Removed names only, one row each (DELL's two intervals are one row).
    assert set(by) == {
        "HAR",
        "EP",
        "XYZ",
        "COL",
        "GONE",
        "AET",
        "GR",
        "HOT",
        "DELL",
        "SBNY",
    }
    assert by["EP"]["flag"] and by["EP"]["overlap"] == 0.0
    assert "name overlap" in by["EP"]["reason"]
    assert by["XYZ"]["flag"] and by["XYZ"]["overlap"] == 1.0
    # The currency flags it; the exchange does not, because the name matches.
    assert by["XYZ"]["reason"] == "currency GBp"
    # No info is recorded, not flagged; the first-price rule still applies.
    assert by["GONE"]["reason"] == "no_info" and not by["GONE"]["flag"]
    assert by["COL"]["flag"] and by["COL"]["reason"].startswith("no_info; first price")
    assert by["HAR"]["flag"] and by["HAR"]["reason"].startswith(
        "first price 2013-01-17"
    )
    # A series that starts after the removed interval ended is not late.
    assert not by["DELL"]["flag"]
    # A matching name on the pink sheets is the company after it delisted.
    assert not by["SBNY"]["flag"] and by["SBNY"]["exchange"] == "PNK"


def test_a_placeholder_quote_is_not_evidence_and_the_price_level_is() -> None:
    # Without levels: Yahoo's YHD/MUTUALFUND code on AET, GR and HAR flags
    # nothing by itself (every delisted symbol carries it).
    by = _check()
    assert not by["AET"]["flag"] and by["AET"]["overlap"] == 1.0
    assert not by["GR"]["flag"] and by["GR"]["overlap"] is None
    # With levels: GR's series is at 7% of Goodrich's price and is flagged;
    # AET's is at Aetna's and is not; HOT's short series is at Starwood's
    # price, so its late start is truncation, not reuse.
    by = _check(_levels())
    assert by["GR"]["flag"] and "price level 0.071" in by["GR"]["reason"]
    assert not by["AET"]["flag"] and by["AET"]["level"] == 1.01
    assert not by["HOT"]["flag"]
    assert by["HAR"]["flag"] and "price level 83.8" in by["HAR"]["reason"]
    assert by["EP"]["flag"] and "price level 0.007" in by["EP"]["reason"]


def test_a_renamed_registrant_matches_through_its_sec_name() -> None:
    info = {"EP": {"longName": "Empire Petroleum Corporation", **LIVE}}
    sec = pl.DataFrame({"ticker": ["EP"], "sec_name": ["EMPIRE PETROLEUM CORP|OLD CO"]})
    got = prices.identity_check(
        _intervals(), info, _first_prices(), sec, history_start=HS
    )
    ep = got.filter(pl.col("ticker") == "EP").row(0, named=True)
    assert ep["overlap"] == 1.0 and not ep["flag"]


def test_price_level_is_close_times_cover_count_in_the_price_basis_over_float() -> None:
    floats = pl.DataFrame(
        [(1, "h-14", date(2013, 12, 31), date(2014, 8, 7), "10-K", 5.52e9, 2014)],
        schema={
            "cik": pl.Int64,
            "adsh": pl.Utf8,
            "ddate": pl.Date,
            "filed": pl.Date,
            "form": pl.Utf8,
            "value": pl.Float64,
            "fy": pl.Int32,
        },
        orient="row",
    )
    cover = pl.DataFrame(
        [(1, "h-q2", date(2014, 1, 31), date(2014, 2, 5), "10-Q", 67.55e6)],
        schema={
            "cik": pl.Int64,
            "adsh": pl.Utf8,
            "ddate": pl.Date,
            "filed": pl.Date,
            "form": pl.Utf8,
            "value": pl.Float64,
        },
        orient="row",
    )
    # A 2-for-1 split after the count's filing date halves the level.
    splits = pl.DataFrame(
        {"ticker": ["HAR"], "date": [date(2015, 6, 1)], "ratio": [2.0]},
        schema={"ticker": pl.Utf8, "date": pl.Date, "ratio": pl.Float64},
    )
    ciks = pl.DataFrame(
        {"ticker": ["HAR"], "cik": [1]}, schema={"ticker": pl.Utf8, "cik": pl.Int64}
    )
    daily = pl.DataFrame(
        {
            "date": [date(2013, 12, 30), date(2013, 12, 31)],
            "ticker": ["HAR"] * 2,
            "close": [7000.0, 7483.38],
        },
        schema={"date": pl.Date, "ticker": pl.Utf8, "close": pl.Float64},
    )
    got = prices.price_levels(floats, cover, splits, ciks, daily, _intervals())
    row = got.row(0, named=True)
    assert row["ticker"] == "HAR" and row["n_levels"] == 1
    assert abs(row["level"] - 7483.38 * 67.55e6 * 2.0 / 5.52e9) < 1e-9
    # Without the split: the H1 ratio for HAR FY2014.
    got = prices.price_levels(floats, cover, None, ciks, daily, _intervals())
    assert abs(got.row(0, named=True)["level"] - 91.57) < 0.01


def test_flagged_names_are_excluded_for_their_whole_membership(tmp_path) -> None:
    from backtester import config

    cfg = config.load("config.toml").with_(data=tmp_path)
    (tmp_path / "checks").mkdir()
    prices.identity_check(
        _intervals(), INFO, _first_prices(), None, _levels(), history_start=HS
    ).write_csv(tmp_path / "checks" / identity.IDENTITY)
    rows = identity.load_identity_flags(cfg)
    assert rows["ticker"].to_list() == ["COL", "EP", "GR", "HAR", "XYZ"]
    ep = rows.filter(pl.col("ticker") == "EP").row(0, named=True)
    assert (ep["start"], ep["end"]) == (date(1900, 1, 1), date(2012, 5, 16))
    assert ep["source_check"] == "identity"
    out = identity.write_exclusions(cfg, None, rows)
    assert (tmp_path / "checks" / identity.EXCLUSIONS).exists()
    assert identity.load_exclusions(cfg).equals(out)
