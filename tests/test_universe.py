"""Invariant 3: a ticker is in the cross-section at t only if it was a member on t."""

from datetime import date

import polars as pl

from backtester import universe

AS_OF = date(2026, 9, 11)


def _constituents(*rows: tuple[str, date | None]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "ticker": t,
                "security": t.lower(),
                "gics_sector": "X",
                "gics_sub_industry": "Y",
                "date_added": d,
                "cik": None,
            }
            for t, d in rows
        ],
        schema={
            "ticker": pl.Utf8,
            "security": pl.Utf8,
            "gics_sector": pl.Utf8,
            "gics_sub_industry": pl.Utf8,
            "date_added": pl.Date,
            "cik": pl.Utf8,
        },
    )


def _changes(*rows: tuple[date, str | None, str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "row": i,
                "date": d,
                "added": a,
                "added_security": a,
                "removed": r,
                "removed_security": r,
                "reason": "test",
            }
            for i, (d, a, r) in enumerate(rows)
        ],
        schema={
            "row": pl.Int64,
            "date": pl.Date,
            "added": pl.Utf8,
            "added_security": pl.Utf8,
            "removed": pl.Utf8,
            "removed_security": pl.Utf8,
            "reason": pl.Utf8,
        },
    )


def test_member_absent_outside_interval() -> None:
    # NEW replaced OLD on 2020-06-15. NEW is a current member.
    cons = _constituents(("NEW", date(2020, 6, 15)), ("STAY", date(1990, 1, 1)))
    chg = _changes((date(2020, 6, 15), "NEW", "OLD"))
    m = universe.build_membership(cons, chg, AS_OF)
    iv = m.intervals

    assert m.inconsistencies.height == 0
    assert universe.members_at(iv, date(2020, 6, 14)) == ["OLD", "STAY"]
    assert universe.members_at(iv, date(2020, 6, 15)) == ["NEW", "STAY"]
    assert universe.members_at(iv, date(2026, 9, 11)) == ["NEW", "STAY"]
    assert universe.members_at(iv, date(2010, 1, 31)) == ["OLD", "STAY"]


def test_removal_is_effective_on_the_date_and_addition_too() -> None:
    cons = _constituents(("A", None))
    chg = _changes((date(2015, 3, 2), "A", "B"), (date(2012, 1, 9), "B", "C"))
    m = universe.build_membership(cons, chg, AS_OF)
    row = {r["ticker"]: r for r in m.intervals.iter_rows(named=True)}
    assert row["B"]["start"] == date(2012, 1, 9)
    assert row["B"]["end"] == date(2015, 3, 1)
    assert row["C"]["end"] == date(2012, 1, 8)
    assert row["C"]["start"] == universe.UNKNOWN_START
    assert row["A"]["start_source"] == "changes:0"
    assert row["B"]["start_source"] == "changes:1"


def test_ticker_can_leave_and_return() -> None:
    # X was a member, left 2013, came back 2019, still in.
    cons = _constituents(("X", date(2019, 5, 1)))
    chg = _changes((date(2019, 5, 1), "X", None), (date(2013, 2, 1), None, "X"))
    m = universe.build_membership(cons, chg, AS_OF)
    iv = m.intervals
    assert m.inconsistencies.height == 0
    assert iv.filter(pl.col("ticker") == "X").height == 2
    assert universe.members_at(iv, date(2012, 12, 31)) == ["X"]
    assert universe.members_at(iv, date(2015, 12, 31)) == []
    assert universe.members_at(iv, date(2020, 12, 31)) == ["X"]


def test_same_day_swap_of_a_ticker_for_itself() -> None:
    # 21st Century Fox (FOX) out, Fox Corporation (FOX) in, 2019-03-19.
    cons = _constituents(("FOX", date(2019, 3, 19)))
    chg = _changes((date(2019, 3, 19), "FOX", "FOX"), (date(2015, 9, 18), "FOX", None))
    m = universe.build_membership(cons, chg, AS_OF)
    assert m.inconsistencies.height == 0
    ivs = m.intervals.filter(pl.col("ticker") == "FOX").sort("start")
    assert ivs["start"].to_list() == [date(2015, 9, 18), date(2019, 3, 19)]
    assert ivs["end"].to_list() == [date(2019, 3, 18), None]
    assert universe.members_at(m.intervals, date(2019, 3, 18)) == ["FOX"]
    assert universe.members_at(m.intervals, date(2019, 3, 19)) == ["FOX"]


def test_pre2010_date_added_is_trusted_for_a_member_with_no_change_row() -> None:
    cons = _constituents(("Q", date(2008, 4, 3)))
    m = universe.build_membership(cons, _changes(), AS_OF)
    r = m.intervals.row(0, named=True)
    assert r["start"] == date(2008, 4, 3)
    assert r["start_source"] == "constituents:date_added"
    assert r["end"] is None
    assert universe.members_at(m.intervals, date(2008, 4, 2)) == []
    assert universe.members_at(m.intervals, date(2008, 4, 3)) == ["Q"]


def test_in_window_date_added_without_a_change_row_is_only_provisional() -> None:
    cons = _constituents(("SRE", date(2017, 3, 17)))
    m = universe.build_membership(cons, _changes(), AS_OF)
    r = m.intervals.row(0, named=True)
    assert r["start"] == date(2017, 3, 17)
    assert r["start_source"] == "unverified:date_added"


def test_rename_is_matched_on_date_added() -> None:
    # FB added 2013-12-23; today's table says META, date added 2013-12-23.
    cons = _constituents(("META", date(2013, 12, 23)), ("Z", date(1990, 1, 1)))
    chg = _changes((date(2013, 12, 23), "FB", "OLD"))
    m = universe.build_membership(cons, chg, AS_OF)
    assert m.inconsistencies.height == 0
    assert m.renames.select("old_ticker", "new_ticker", "date").rows() == [
        ("FB", "META", date(2013, 12, 23))
    ]
    meta = m.intervals.filter(pl.col("ticker") == "META").row(0, named=True)
    assert meta["start"] == date(2013, 12, 23)
    assert meta["start_source"] == "changes:0:renamed_from:FB"
    assert "FB" not in m.intervals["ticker"].to_list()
    assert universe.members_at(m.intervals, date(2013, 12, 22)) == ["OLD", "Z"]
    assert universe.members_at(m.intervals, date(2014, 1, 31)) == ["META", "Z"]


def test_rename_within_tolerance_but_ambiguous_is_flagged_not_guessed() -> None:
    cons = _constituents(("P", date(2013, 12, 23)), ("Q", date(2013, 12, 24)))
    chg = _changes((date(2013, 12, 23), "FB", None))
    m = universe.build_membership(cons, chg, AS_OF)
    assert m.renames.height == 0
    assert m.inconsistencies["ticker"].to_list() == ["FB"]
    assert "2 rename candidates" in m.inconsistencies["problem"][0]


def test_adjudication_rejects_date_added_when_crosscheck_has_ticker_before() -> None:
    cons = _constituents(("SRE", date(2017, 3, 17)), ("BRK.B", date(2010, 2, 16)))
    m = universe.build_membership(cons, _changes(), AS_OF)
    snaps = {
        date(1996, 1, 2): frozenset({"SRE", "X"}),
        date(2010, 2, 16): frozenset({"SRE", "X", "BRK.B"}),
    }
    intervals, adj = universe.adjudicate(m, snaps)
    row = {r["ticker"]: r for r in intervals.iter_rows(named=True)}
    assert row["SRE"]["start"] == universe.UNKNOWN_START
    assert row["SRE"]["start_source"] == "crosscheck:first_seen"
    assert row["BRK.B"]["start"] == date(2010, 2, 16)
    assert row["BRK.B"]["start_source"] == "date_added:crosscheck_agrees"
    assert adj.height == 2
    assert adj.filter(pl.col("ticker") == "SRE")["verdict"][0].startswith(
        "date_added rejected"
    )


def test_reconcile_counts_agreement_under_current_ticker() -> None:
    cons = _constituents(("META", date(2013, 12, 23)))
    chg = _changes((date(2013, 12, 23), "FB", None))
    m = universe.build_membership(cons, chg, AS_OF)
    snaps = {date(2013, 12, 23): frozenset({"FB", "GHOST"})}
    rec = universe.reconcile(
        m.intervals, snaps, m.renames, date(2014, 1, 31), date(2014, 2, 28)
    )
    per_year, diff = rec.per_year, rec.residual
    assert per_year.row(0, named=True) == {
        "year": 2014,
        "universe_months": 2,
        "crosscheck_months": 4,
        "agree": 2,
        "agree_pct": 50.0,
    }
    assert diff.rows() == [
        ("GHOST", "only_crosscheck", 2, date(2014, 1, 31), date(2014, 2, 28))
    ]


def test_monthly_counts_cover_every_month_end() -> None:
    cons = _constituents(("A", date(2000, 1, 1)))
    m = universe.build_membership(cons, _changes(), AS_OF)
    counts = universe.monthly_counts(m.intervals, date(2024, 1, 31), date(2024, 6, 30))
    assert counts["month"].to_list() == [
        date(2024, 1, 31),
        date(2024, 2, 29),
        date(2024, 3, 31),
        date(2024, 4, 30),
        date(2024, 5, 31),
        date(2024, 6, 30),
    ]
    assert counts["n_members"].to_list() == [1] * 6


def test_parse_date_accepts_both_wikipedia_formats() -> None:
    assert universe.parse_date("August 18, 2026") == date(2026, 8, 18)
    assert universe.parse_date("1957-03-04") == date(1957, 3, 4)
    assert universe.parse_date("1957-03-04 (as Foo)") == date(1957, 3, 4)
    assert universe.parse_date("") is None


def test_clean_ticker_drops_wikipedia_junk() -> None:
    assert universe.clean_ticker("ALLE |") == "ALLE"
    assert universe.clean_ticker("BRK.B") == "BRK.B"
    assert universe.clean_ticker("BF-B ") == "BF-B"
    assert universe.clean_ticker("") is None
    assert universe.clean_ticker(None) is None


def test_parse_crosscheck_strips_delisting_suffix() -> None:
    text = 'date,tickers\n2010-01-04,"AAPL,ABC-201503,BRK-B"\n2010-01-05,"AAPL"\n'
    snaps = universe.parse_crosscheck(text)
    assert snaps[date(2010, 1, 4)] == {"AAPL", "ABC", "BRK.B"}
    assert universe.crosscheck_at(snaps, date(2010, 1, 4)) == {"AAPL", "ABC", "BRK.B"}
    assert universe.crosscheck_at(snaps, date(2010, 1, 9)) == {"AAPL"}
    assert universe.crosscheck_at(snaps, date(2009, 1, 1)) == frozenset()


def test_reconcile_pairs_label_only_differences_as_aliases() -> None:
    # EQR renamed VMRK with no index event: same months, both sides.
    cons = _constituents(("VMRK", date(1990, 1, 1)), ("ZZZ", date(1990, 1, 1)))
    m = universe.build_membership(cons, _changes(), AS_OF)
    snaps = {
        date(2000, 1, 1): frozenset({"EQR", "ZZZ"}),
        date(2020, 3, 1): frozenset({"EQR", "ZZZ", "GHOST"}),
    }
    rec = universe.reconcile(
        m.intervals, snaps, m.renames, date(2020, 1, 31), date(2020, 3, 31)
    )
    assert rec.aliases.select("crosscheck_ticker", "wikipedia_ticker").rows() == [
        ("EQR", "VMRK")
    ]
    assert rec.residual.select("ticker", "months").rows() == [("GHOST", 1)]
    assert rec.per_year["agree"][0] == 6  # VMRK and ZZZ, three month-ends


def test_overrides_add_intervals_and_never_remove() -> None:
    cons = _constituents(("GOOG", date(2014, 4, 3)))
    m = universe.build_membership(cons, _changes(), AS_OF)
    overrides = pl.DataFrame(
        [
            {
                "ticker": "GOOGL",
                "security": "Alphabet (Class A)",
                "start": date(2006, 3, 31),
                "end": date(2014, 4, 2),
                "reason": "class C distribution",
                "evidence": "press release",
            }
        ],
        schema=universe.OVERRIDES_SCHEMA,
    )
    out = universe.apply_overrides(m.intervals, overrides)
    assert out.height == 2
    assert universe.members_at(out, date(2012, 6, 30)) == ["GOOGL"]
    assert universe.members_at(out, date(2014, 4, 30)) == ["GOOG"]
    assert out.filter(pl.col("ticker") == "GOOGL")["start_source"][0] == "override"


def test_override_matching_ticker_and_end_corrects_the_start() -> None:
    # UAA added as UA in 2014, removed as UAA in 2022: the walk leaves the
    # start unknown, the override pins it.
    cons = _constituents(("KDP", date(2022, 6, 21)))
    chg = _changes((date(2022, 6, 21), "KDP", "UAA"), (date(2014, 5, 1), "UA", None))
    m = universe.build_membership(cons, chg, AS_OF)
    uaa = m.intervals.filter(pl.col("ticker") == "UAA").row(0, named=True)
    assert uaa["start"] == universe.UNKNOWN_START and uaa["end"] == date(2022, 6, 20)
    overrides = pl.DataFrame(
        [
            {
                "ticker": "UAA",
                "security": "Under Armour (Class A)",
                "start": date(2014, 5, 1),
                "end": date(2022, 6, 20),
                "reason": "added as UA",
                "evidence": "row 1",
            }
        ],
        schema=universe.OVERRIDES_SCHEMA,
    )
    out = universe.apply_overrides(m.intervals, overrides)
    assert out.filter(pl.col("ticker") == "UAA").height == 1
    uaa = out.filter(pl.col("ticker") == "UAA").row(0, named=True)
    assert uaa["start"] == date(2014, 5, 1)
    assert uaa["start_source"] == "override"
    assert uaa["end_source"] == "changes:0"
    assert universe.members_at(out, date(2014, 4, 30)) == []
    assert universe.members_at(out, date(2014, 5, 31)) == ["UAA"]
