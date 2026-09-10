# Cross-Sectional Factor Backtester

Point-in-time equity factor research for US large caps, 2010–2026, with
costs, signal decay and overfitting control.

> **Status: specification only.** Nothing in `src/` is implemented yet. The
> results table below is deliberately empty — it gets filled from a real run,
> not from expectations. See [the brief](Project%20Outline/01_Factor_Backtester.docx).

## What this is

A monthly-rebalanced factor backtester that treats **data honesty as the
deliverable, not the returns**. It takes point-in-time fundamentals from SEC
filings, a reconstructed historical universe, and daily prices, and produces
decile and long–short portfolios for value, momentum, quality and low
volatility — with costs, turnover and statistical tests on top.

The single check that matters: **are the fundamentals lagged correctly?** Every
value used at month *t* must have been *filed* before *t*, joined as-of filing
date with a further one-day buffer — not keyed on period end. Most candidate
backtests fail exactly here.

## The question

Do value, momentum, quality and low volatility earn a premium on a universe an
outsider can verify, over 2010–2026?

- How much paper return survives turnover, spreads and a 1-day execution lag?
- How fast does each signal decay, and what rebalance frequency follows?
- How much of the result is multiple-testing luck, once N is counted honestly?

**The expected answer is modest, and that is the point.** Momentum and quality
should survive costs at a modest Sharpe; value is likely weak over this window;
low volatility's return is largely duration and beta. *A 2.0 Sharpe means
something is leaking.*

## Validation bar

The pipeline is considered wrong until the long–short series clear this:

| Series | Must correlate with | Threshold |
|---|---|---|
| Value long–short | French **HML** | > 0.7 |
| Momentum long–short | French **UMD** | > 0.7 |
| Quality long–short | French **RMW** | > 0.7 |

A large unexplained alpha on a plain value signal is an error, not a discovery.

## Results

Filled from a run. Empty until there is one.

| Factor | Gross ann. | Net ann. | Vol | Sharpe (net) | DSR | Max DD | Turnover | Mean IC | IC t-stat | Break-even cost |
|---|---|---|---|---|---|---|---|---|---|---|
| Momentum 12-1 | | | | | | | | | | |
| Value (B/P, E/P) | | | | | | | | | | |
| Quality (GP/A, accruals) | | | | | | | | | | |
| Low volatility | | | | | | | | | | |

Base case cost is 10 bp one-way, with 5 bp and 25 bp shown as sensitivities.
**Break-even cost** — the level at which net Sharpe hits zero — is reported
because it is more useful than any single net return.

## Data

| Need | Source | Note |
|---|---|---|
| Universe history | Wikipedia S&P 500 changes table | Stored as membership intervals per ticker |
| Fundamentals | SEC Financial Statement Data Sets | Quarterly zips, 2009→; **filing date is the key** |
| Prices | yfinance, Stooq | Delisted coverage is patchy and is logged |
| Sector map | SIC codes from EDGAR | Mapped to 11 GICS-like buckets |
| Benchmarks | Ken French data library | Mkt, SMB, HML, RMW, CMA, UMD |
| Risk-free | FRED DGS1MO | For excess returns |

**Known limitation, stated up front:** the S&P 500 restriction is a compromise
forced by free data — roughly 500 names per month and ~1,100 unique names over
the window. Survivorship is handled by reconstructing membership month by
month, but the universe is still large-cap only, and a Russell 3000 version
would need paid coverage of delisted names.

## What did not work

Kept as a first-class section, per the brief. Populated as things fail.

## Layout

```
data/            raw, interim, processed — all gitignored
src/universe.py      month-by-month S&P 500 membership
src/fundamentals.py  SEC filings, as-of filing date
src/prices.py        daily adjusted prices
src/signals.py       winsorise, sector-neutralise, z-score
src/portfolio.py     deciles, long-short, costs, turnover
src/stats.py         IC, Fama-MacBeth, Newey-West, deflated Sharpe
notebooks/
reports/             figures and specifications.csv are committed
```

Build order is momentum first — it needs no fundamentals — validated against
UMD before the SEC data is touched.
