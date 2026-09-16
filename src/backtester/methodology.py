"""The two-page methodology note, reports/methodology.pdf.

Recruiters forward PDFs; they do not clone repos (brief, section 9). The
note is generated from the same saved results as results.md, so it cannot
drift from the README. Core fonts only, so it renders anywhere.
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
from fpdf import FPDF

from backtester.config import Config
from backtester.report import LABELS, factor_report, load_inputs
from backtester.run import REPORTED, validate, validation_table


def _clean(s: str) -> str:
    """Core fonts are Latin-1: swap the few characters that are not."""
    return (
        s.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("→", "->")
        .replace("×", "x")
        .replace("≤", "<=")
        .replace("≥", ">=")
    )


class Note(FPDF):
    def h1(self, text: str) -> None:
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 8, _clean(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def h2(self, text: str) -> None:
        self.ln(1.5)
        self.set_font("Helvetica", "B", 10.5)
        self.cell(0, 6, _clean(text), new_x="LMARGIN", new_y="NEXT")

    def p(self, text: str, size: float = 9.0) -> None:
        self.set_font("Helvetica", "", size)
        self.multi_cell(0, 4.3, _clean(text))
        self.ln(0.8)

    def bullets(self, items: list[str], size: float = 9.0) -> None:
        self.set_font("Helvetica", "", size)
        for it in items:
            x = self.get_x()
            self.cell(4, 4.3, "-")
            self.multi_cell(0, 4.3, _clean(it))
            self.set_x(x)
        self.ln(0.8)

    def table(
        self, header: list[str], rows: list[list[str]], widths: list[float]
    ) -> None:
        self.set_font("Helvetica", "B", 8)
        for h, w in zip(header, widths, strict=True):
            self.cell(w, 5, _clean(h), border="B")
        self.ln()
        self.set_font("Helvetica", "", 8)
        for r in rows:
            for c, w in zip(r, widths, strict=True):
                self.cell(w, 4.6, _clean(c))
            self.ln()
        self.ln(1.5)


def _f(x: float, nd: int = 2, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{100 * x:.{nd}f}%" if pct else f"{x:.{nd}f}"


def build(cfg: Config) -> None:
    inp = load_inputs(cfg)
    from backtester.report import trial_counts

    trials = trial_counts(cfg)
    n_trials = trials["all"][0]
    reports = [factor_report(cfg, f, inp, trials) for f in REPORTED]
    cov = pl.read_csv(cfg.data / "checks" / "price_coverage_summary.csv")
    gap = float(cov.filter(pl.col("metric") == "gap_pct")["value"][0])
    uni = pl.read_csv(cfg.data / "checks" / "membership_summary.csv")
    agree = uni.filter(pl.col("metric") == "crosscheck_agree_pct")["value"][0]

    pdf = Note(format="A4")
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.h1("Cross-sectional factor backtester: methodology note")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(
        0,
        5,
        _clean(
            f"US large caps, {cfg.start.year}-{cfg.end.year}. Generated {date.today()} from the saved runs; "
            "the repository README carries the same numbers."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    pdf.h2("Question")
    pdf.p(
        "Do value, momentum, quality and low volatility earn a premium on a universe an outsider can "
        "verify, once the fundamentals are lagged to their filing date, costs and a one-day execution "
        "lag are charged, and the number of specifications tried is counted honestly?"
    )

    pdf.h2("Data, and what is honest about it")
    pdf.bullets(
        [
            "Universe: S&P 500 membership reconstructed month by month from Wikipedia's changes table, "
            f"cross-checked against an independent daily list ({agree}% of universe-months agree, every "
            "disagreement listed) and 20 changes checked against S&P press releases. 496-504 names at "
            "every month-end, 818 unique names over the window.",
            "Fundamentals: SEC Financial Statement Data Sets, 2009q1-2026q2, 16 concepts through an ordered "
            "XBRL tag map. Every value is keyed on its filing date; the first-filed value wins over "
            "amendments; the value used at month-end t was filed on or before t - 1 day. This join has "
            "three unit tests, one of which plants a filing dated after the signal date and asserts it "
            "is excluded.",
            f"Prices: yfinance daily adjusted closes. Delisted names are largely absent: {gap:.1f}% of "
            "universe-months have no price, 31% in 2010 falling to 0% today. yfinance's series for reused "
            "symbols are dropped by three logged rules (no history inside membership, bad print, corrupt series).",
            "Benchmarks: Ken French's factors and the six size x B/M and size x profitability portfolios, "
            "whose big-cap legs are the like-for-like comparison for a large-cap universe.",
        ]
    )

    pdf.h2("Method")
    pdf.bullets(
        [
            "Signals at each month-end from data available then: 12-1 momentum, book-to-price, earnings "
            "yield, gross profit / assets, cash-flow accruals (negated), 252-day volatility (negated), "
            "and the cosine similarity of the latest 10-K text to the prior year's (Cohen, Malloy and "
            "Nguyen 2020), from EDGAR primary documents dated by the SEC's filing date, scored without "
            "a language model so that nothing trained after the filing can leak into the score. "
            "Winsorised at the 1st/99th percentile, z-scored within sector (SIC mapped by hand to 11 "
            "GICS-like buckets), composites averaged and re-standardised.",
            "Portfolios: ten equal-count deciles, equal-weighted (cap-weighted as a sensitivity), formed "
            "monthly and traded at the close of the next trading day; long-short is decile 10 minus 1. "
            "Turnover is half the sum of absolute weight changes against drifted weights, both legs. "
            "Every dollar bought or sold pays the one-way cost c, so r_net = r_gross - 2c x turnover; "
            "the brief's r_gross - c x turnover charges half that.",
            "Statistics: Spearman IC by month and by horizon 1-12 with an exponential half-life; "
            "Fama-MacBeth premia with Newey-West errors (checked against statsmodels to 1e-9); "
            "attribution on Mkt-RF, HML, UMD, RMW; break-even cost; and the deflated Sharpe with N read "
            f"from a specification log that every run appends to (N = {n_trials} distinct "
            f"specifications over {trials['rows']} logged runs).",
        ]
    )

    pdf.h2(f"Results (net of {cfg.base_bps:.0f} bp; DSR uses N = {n_trials})")
    header = [
        "Factor",
        "Gross",
        "Net",
        "Vol",
        "Sharpe",
        "DSR",
        "MaxDD",
        "Turn.",
        "IC",
        "IC t",
        "Break-even",
    ]
    widths = [40, 13, 13, 13, 14, 12, 13, 12, 13, 11, 24]
    rows = []
    for r in reports:
        x = r.row
        be = x["breakeven_bps"]
        rows.append(
            [
                LABELS[r.factor],
                _f(x["gross_ann"], 1, True),
                _f(x["net_ann"], 1, True),
                _f(x["vol"], 1, True),
                _f(x["sharpe_net"]),
                _f(x["dsr"]),
                _f(x["max_dd"], 0, True),
                _f(x["turnover"]),
                _f(x["mean_ic"], 3),
                _f(x["ic_t"], 1),
                "none"
                if (isinstance(be, float) and (math.isnan(be) or be < 0))
                else f"{be:.0f} bp",
            ]
        )
    pdf.table(header, rows, widths)

    pdf.h2("Validation")
    val = {r.factor: r.validation for r in reports}
    att = {r.factor: r.attribution for r in reports}
    rows_by = {r.factor: r.row for r in reports}
    vt = validation_table(cfg, inp)
    corr = dict(zip(vt["series"], vt["correlation"], strict=True))
    big = {}
    for f, leg in (("hml_replica", "big_hml"), ("rmw_replica", "big_rmw")):
        path = cfg.data / "processed" / f"long_short_{f}.parquet"
        if path.exists() and leg in inp.french.columns:
            ls = pl.read_parquet(path)
            big[f] = validate(ls, inp.french, leg)["corr"]
            big[f + "_2016"] = validate(
                ls.filter(pl.col("month") >= date(2016, 1, 1)), inp.french, leg
            )["corr"]
    m_umd = val["momentum"]["corr"]
    pdf.p(
        f"Momentum long-short correlates {m_umd:.2f} with UMD and loads on it with beta "
        f"{att['momentum'].betas['umd']:.2f}, R-squared {att['momentum'].r2:.2f}: it is UMD, and UMD "
        f"earned nothing in this window. The reported value and quality factors are sector-neutral "
        f"composites and correlate {val['value']['corr']:.2f} and {val['quality']['corr']:.2f} with HML "
        f"and RMW, which is construction, not a join error. The join is tested by replicating French's "
        f"construction (one signal, no sector neutralisation, cap-weighted terciles) against the big-cap "
        f"half of his factor: the B/P replication correlates {big.get('hml_replica', float('nan')):.2f} "
        f"with the big-cap HML leg over the window and {big.get('hml_replica_2016', float('nan')):.2f} "
        f"from 2016 ({corr.get('hml_replica', float('nan')):.2f} against full HML). The profitability "
        f"replication reaches {big.get('rmw_replica', float('nan')):.2f} against the big-cap leg and "
        f"{corr.get('rmw_replica', float('nan')):.2f} against full RMW, a fail against the 0.6 bar; "
        "its early-years weakness was the ticker-to-CIK map (decisions/cik_audit.md), not XBRL coverage."
    )

    pdf.h2("What the numbers mean")
    v, q, mo, lv, co = (
        rows_by[k] for k in ("value", "quality", "momentum", "low_vol", "composite")
    )
    lva = att["low_vol"]
    pdf.bullets(
        [
            f"Value nets {v['sharpe_net']:.2f} and loads {att['value'].betas['hml']:.2f} on HML "
            f"(t {att['value'].beta_t['hml']:.1f}) with an alpha of {100 * att['value'].alpha_annual:.1f}% "
            f"(t {att['value'].alpha_t:.1f}): large-cap value earned nothing over the window. The 0.48 "
            "an earlier version of this note reported was a market-cap bug: split-adjusted prices met "
            "unadjusted share counts, so pre-split winners sat in the value long leg (decisions/f2_shares.md).",
            f"Momentum is marginal after costs ({mo['sharpe_net']:.2f}; break-even {mo['breakeven_bps']:.0f} bp "
            f"at {mo['turnover']:.2f} monthly turnover). Quality is the only positive line "
            f"({q['sharpe_net']:.2f}; IC t {q['ic_t']:.1f}), carried by accruals. Low volatility loses as a "
            f"long-short: beta {lva.betas['mkt_rf']:.2f} (t {lva.beta_t['mkt_rf']:.1f}), RMW "
            f"{lva.betas['rmw']:.2f} (t {lva.beta_t['rmw']:.1f}), alpha {100 * lva.alpha_annual:.1f}% "
            f"(t {lva.alpha_t:.1f}): a short-beta position, and shorting beta lost for sixteen years. "
            f"The composite nets {co['sharpe_net']:.2f}.",
            f"The deflated Sharpe of quality is {q['dsr']:.2f} against all {n_trials} distinct "
            f"specifications and {q['dsr_candidates']:.2f} against the {trials['candidates'][0]} "
            "candidate ones (a floor: the diagnostic runs informed which specifications became "
            "candidates): the probability that its Sharpe beats the best of that many random "
            "trials with the same dispersion. Nothing here is a 2.0 Sharpe.",
        ]
    )

    pdf.h2("What did not work")
    pdf.bullets(
        [
            "Wikipedia's 'Date added' is a corporate-event date for long-standing members (Sempra 2017, "
            "T. Rowe Price 2019); trusted only before 2010, adjudicated by the cross-check after.",
            "Stooq serves a JavaScript challenge, not data; yfinance stitches reused symbols and carries bad "
            "prints. Delisted names remain the survivorship that is left, and it is quantified.",
            "The first momentum run correlated 0.04 with UMD: uncleaned prices and a validation join off "
            "by one month. Both runs stay in the specification log.",
            "Wikipedia's CIK for ExxonMobil is a 2026 entity; OperatingIncomeLoss is not reported by "
            "banks. Each has a logged rule.",
            "The ticker-to-CIK map left 18% of members without filings (successor registrants, name "
            "collisions); 93 hand-verified override rows with a CIK per era fixed it. Market caps met a "
            "split-adjusted price with an unadjusted count; the value premium the first version reported "
            "was that bug. Both found by the September 2026 review, both in decisions/.",
        ],
        size=8.6,
    )
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        0,
        4,
        _clean(
            "Code, tests, the specification log and every check file are in the repository. "
            "The results table, charts and this note are regenerated by `backtester report`."
        ),
    )
    out = cfg.reports / "methodology.pdf"
    pdf.output(str(out))
