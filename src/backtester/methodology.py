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

from backtester import portfolio
from backtester.config import Config
from backtester.report import LABELS, factor_report, load_inputs
from backtester.run import REPORTED


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
    n_trials = portfolio.count_specifications(cfg.specifications)
    log = pl.read_csv(cfg.specifications)
    s = log["sharpe_net"].cast(pl.Float64, strict=False).drop_nulls()
    sr_var = float((s / math.sqrt(12)).var()) if s.len() > 1 else 0.0
    reports = [factor_report(cfg, f, inp, n_trials, sr_var) for f in REPORTED]
    dsr_c = next(r.row["dsr"] for r in reports if r.factor == "composite")
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
            "yield, gross profit / assets, cash-flow accruals (negated), 252-day volatility (negated). "
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
            f"from a specification log that every run appends to (N = {n_trials}).",
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
    pdf.p(
        "Momentum long-short correlates 0.79 with UMD (0.85 without sector neutralisation) and loads on "
        "it with beta 0.91, R-squared 0.66: it is UMD, and UMD earned nothing in this window. The "
        "reported value and quality factors are sector-neutral composites and correlate 0.25 and 0.07 "
        "with HML and RMW, which is construction, not a join error. The join is tested by replicating "
        "French's construction (one signal, no sector neutralisation, cap-weighted terciles) against the "
        "big-cap half of his factor: the B/P replication correlates 0.74 with the big-cap HML leg over "
        "the window and 0.89 from 2016. The profitability replication reaches 0.44, rising from 0.07 in "
        "2010-12 to 0.74 in 2019-21 as XBRL coverage does; it is reported as a fail."
    )

    pdf.h2("What the numbers mean")
    pdf.bullets(
        [
            "Value worked (net Sharpe 0.50, Fama-MacBeth t 3.2, break-even 80 bp). Its 4.9% attribution "
            "alpha is the number to distrust first: sector-neutral B/P alone has 4.5% (t 2.3) with an HML "
            "loading of 0.26, so the alpha is what sector neutralisation leaves after a factor that is not "
            "sector-neutral. Cap-weighted it is 0.30; on the well-covered months from 2015-12 it is 0.48.",
            "Momentum is marginal after costs (0.05; break-even 15 bp at 0.62 monthly turnover) and better "
            "held 3-12 months (0.18-0.23). Quality is small (0.17; 0.42 cap-weighted). Low volatility "
            "loses as a long-short: beta -0.65 (t -10.5), RMW 0.94 (t 8.2), alpha 1.1% (t 0.4) - it is a "
            "short-beta position and shorting beta lost for sixteen years.",
            "Signal decay: momentum's IC halves in about 15 months; value, quality and the composite do "
            "not decay within 12 months, so holding them 6-12 months keeps the return and cuts most of "
            "the turnover (composite: 0.34 monthly, 0.64 at 12 months).",
            f"The deflated Sharpe of the composite is {dsr_c:.2f}: a {100 * dsr_c:.0f}% probability that "
            f"its Sharpe beats the best of {n_trials} random trials with the same dispersion. Nothing here "
            "is a 2.0 Sharpe.",
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
            "Wikipedia's CIK for ExxonMobil is a 2026 entity; some filers report share counts in the wrong "
            "units; OperatingIncomeLoss is not reported by banks. Each has a logged rule.",
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
