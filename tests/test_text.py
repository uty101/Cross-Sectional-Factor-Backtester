"""The 10-K text signal keeps invariants 1 and 2, and adds invariant 10: a
text score is a deterministic function of documents filed on or before
t - buffer, with no model in the loop."""

from collections import Counter
from datetime import date, datetime

import polars as pl
import pytest

from backtester import config, text

M = [date(2021, 1, 31), date(2021, 2, 28), date(2021, 3, 31), date(2021, 4, 30)]


def _index(*rows: tuple[str, int, str, date, date]) -> pl.DataFrame:
    """(adsh, cik, form, period, filed)."""
    return pl.DataFrame(
        [
            {
                "adsh": a,
                "cik": c,
                "form": f,
                "period": p,
                "fy": p.year,
                "filed": d,
                "accepted": datetime(d.year, d.month, d.day, 16, 0),
                "instance": f"x-{p:%Y%m%d}.htm",
            }
            for a, c, f, p, d in rows
        ],
        schema=text.FILINGS_SCHEMA,
    )


def _cfg(repo_root, **changes):
    return config.load(repo_root / "config.toml").with_(**changes)


# --- the scorer (invariant 10) -------------------------------------------


def test_similarity_against_hand_computed_case() -> None:
    a = Counter({"apple": 2, "bank": 1})
    b = Counter({"apple": 1, "bank": 2})
    cos, jac = text.similarity(a, b)
    # dot = 2*1 + 1*2 = 4; |a| = |b| = sqrt(5); cosine = 4/5.
    assert cos == pytest.approx(0.8)
    assert jac == pytest.approx(1.0)
    assert text.similarity(a, a) == pytest.approx((1.0, 1.0))
    assert text.similarity(a, Counter({"cash": 3})) == (0.0, 0.0)
    assert text.similarity(a, Counter()) == (0.0, 0.0)


def test_similarity_is_deterministic_and_symmetric() -> None:
    a = Counter(text.to_words(b"Revenue grew because demand for the product grew."))
    b = Counter(text.to_words(b"Revenue fell because demand for the product fell."))
    assert text.similarity(a, b) == text.similarity(a, b) == text.similarity(b, a)


def test_to_words_drops_markup_numbers_and_the_inline_xbrl_header() -> None:
    doc = b"""<html><head><title>10-K</title></head><body>
    <ix:header><ix:hidden>dei:DocumentType 10-K taxonomy 2023</ix:hidden></ix:header>
    <script>var x = 1;</script>
    <p>Net&nbsp;revenue was $1,234 million in 2023, up from 2022.</p>
    <table><tr><td>Cash</td><td>500</td></tr></table>
    </body></html>"""
    words = text.to_words(doc)
    assert words == ["net", "revenue", "million", "cash"]  # "up" is a stop word
    # Plain-text filings go through the same tokeniser.
    assert text.to_words(b"Risk Factors.\nOur revenue may fall.") == [
        "risk",
        "factors",
        "revenue",
        "fall",
    ]


def test_scorer_has_no_model_and_no_network() -> None:
    # Invariant 10, the static half: the module that scores a document
    # imports nothing that could call a language model or the web at
    # scoring time. `requests` is imported inside fetch only.
    import sys

    src = open(text.__file__, encoding="utf-8").read()
    for name in ("anthropic", "openai", "transformers", "torch", "sklearn"):
        assert name not in src
    assert "import requests" not in src.split("def fetch")[0]
    assert "backtester.text" in sys.modules


# --- pairs (invariant 2) ---------------------------------------------------


def test_pairs_use_the_prior_original_and_the_first_filing_of_a_period() -> None:
    idx = _index(
        ("k19", 1, "10-K", date(2019, 12, 31), date(2020, 2, 20)),
        ("k19a", 1, "10-K/A", date(2019, 12, 31), date(2020, 5, 1)),
        ("k19b", 1, "10-K", date(2019, 12, 31), date(2020, 6, 1)),  # re-filed
        ("k20", 1, "10-K", date(2020, 12, 31), date(2021, 2, 18)),
        ("k18", 2, "10-K", date(2018, 12, 31), date(2019, 2, 20)),
        ("k21", 2, "10-K", date(2021, 12, 31), date(2022, 2, 20)),  # gap: 2019 missed
    )
    p = text.pairs(idx)
    assert p.filter(pl.col("cik") == 1).select("adsh", "prev_adsh").rows() == [
        ("k20", "k19")
    ]
    assert p.filter(pl.col("cik") == 2).height == 0


# --- the signal (invariants 1 and 10) ------------------------------------


def _sim(*rows: tuple[int, str, date, date, float]) -> pl.DataFrame:
    """(cik, adsh, period, filed, cosine)."""
    return pl.DataFrame(
        [
            {
                "cik": c,
                "adsh": a,
                "prev_adsh": "prev",
                "period": p,
                "prev_period": date(p.year - 1, p.month, p.day),
                "filed": d,
                "n_words": 5000,
                "prev_n_words": 5000,
                "cosine": v,
                "jaccard": v / 2,
            }
            for c, a, p, d, v in rows
        ],
        schema=text.SIMILARITY_SCHEMA,
    )


CIKS = pl.DataFrame({"ticker": ["AAA"], "cik": [1]})


def test_text_signal_uses_only_filings_before_signal_date(repo_root) -> None:
    cfg = _cfg(repo_root)
    sim = _sim(
        (1, "k19", date(2019, 12, 31), date(2020, 2, 20), 0.90),
        (1, "k20", date(2020, 12, 31), date(2021, 2, 28), 0.60),  # the month-end
    )
    out = text.signal(cfg, sim, CIKS, M)
    got = dict(zip(out["month"], out["value"], strict=True))
    assert got[M[0]] == 0.90
    assert got[M[1]] == 0.90  # filed on the month-end: not yet, with a 1-day buffer
    assert got[M[2]] == 0.60
    assert text.signal(cfg, sim, CIKS, M, measure="jaccard").filter(
        pl.col("month") == M[3]
    )["value"][0] == pytest.approx(0.30)


def test_text_signal_is_unchanged_by_a_later_filing(repo_root) -> None:
    # Invariant 10, the dynamic half: adding a document filed after t
    # cannot move the value at t. A model-based scorer would fail this
    # in spirit even where it passed it in form; this scorer passes both.
    cfg = _cfg(repo_root)
    before = _sim((1, "k19", date(2019, 12, 31), date(2020, 2, 20), 0.90))
    after = pl.concat(
        [before, _sim((1, "k20", date(2020, 12, 31), date(2021, 4, 15), 0.10))]
    )
    a = text.signal(cfg, before, CIKS, M[:3])
    b = text.signal(cfg, after, CIKS, M[:3])
    assert a.rows() == b.rows()


def test_text_signal_expires_a_stale_filing(repo_root) -> None:
    cfg = _cfg(repo_root)
    sim = _sim((1, "k18", date(2018, 12, 31), date(2019, 2, 20), 0.90))
    out = text.signal(cfg, sim, CIKS, [date(2020, 6, 30), date(2020, 7, 31)])
    # Period end 2018-12-31 + 18 months = 2020-06-30: current at June, not July.
    assert out["month"].to_list() == [date(2020, 6, 30)]


# --- config -------------------------------------------------------------


def test_config_rejects_a_scorer_that_is_not_deterministic(repo_root) -> None:
    cfg = config.load(repo_root / "config.toml")
    assert cfg.text_similarity in config.SIMILARITIES
    with pytest.raises(ValueError):
        cfg.with_(text_similarity="llm")


# --- the index and the raw store --------------------------------------


def test_filing_index_reads_sub_txt_and_keeps_originals_only() -> None:
    rows = [
        "adsh cik name form period fy fp filed accepted prevrpt instance",
        "0001-20-1 1 X 10-K 20191231 2019 FY 20200220 2020-02-20T16:30:00.0 0 x.htm",
        "0001-20-2 1 X 10-K/A 20191231 2019 FY 20200501 2020-05-01T16:30:00.0 0 x.htm",
        "0001-20-3 1 X 10-Q 20200331 2020 Q1 20200505 2020-05-05T16:30:00.0 0 x.htm",
    ]
    # Space-separated above for line length; sub.txt is tab-separated with a
    # space inside the acceptance timestamp.
    sub = "\n".join("\t".join(r.split(" ")).replace("T", " ") for r in rows)
    sub = sub.encode() + b"\n"
    idx = text._parse_sub(sub)
    assert idx["adsh"].to_list() == ["0001-20-1"]
    assert idx["filed"][0] == date(2020, 2, 20)
    assert idx["accepted"][0] == datetime(2020, 2, 20, 16, 30)


def test_primary_documents_reads_both_page_shapes() -> None:
    main = {
        "filings": {
            "recent": {"accessionNumber": ["a-1"], "primaryDocument": ["a.htm"]},
            "files": [{"name": "more.json"}],
        }
    }
    overflow = {"accessionNumber": ["a-0", "a-x"], "primaryDocument": ["b.htm", ""]}
    assert text.primary_documents([main, overflow]) == {"a-1": "a.htm", "a-0": "b.htm"}
    assert text.doc_url(320193, "0000320193-23-000106", "aapl-20230930.htm") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/"
        "aapl-20230930.htm"
    )
    assert text.doc_path(320193, "0000320193-23-000106", "aapl-20230930.htm") == (
        "edgar/10k/320193/0000320193-23-000106.htm.gz"
    )
