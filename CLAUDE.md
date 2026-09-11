# Cross-Sectional Factor Backtester

Read this first. The brief is
[Project Outline/01_Factor_Backtester.docx](Project%20Outline/01_Factor_Backtester.docx),
the acceptance criteria are in [README.md](README.md), and the build order
and module contracts are in [PLAN.md](PLAN.md). This file holds what every
session must not violate, and how to run things on this machine.

**Data honesty is the deliverable, not the returns.** A 2.0 Sharpe means
something is leaking. Value, momentum and quality long-short series must
correlate above 0.7 with French HML, UMD and RMW; below that the pipeline
is wrong, not the literature.

---

## Invariants

Each has a test named next to it. The test is written before the code it
guards. Do not weaken one to make a run pass.

| # | Invariant | Test |
|---|---|---|
| 1 | A fundamental used at month-end *t* was **filed** on or before *t - asof_buffer_days*. Joined as-of `filed`, never `period_end`. | `test_asof_join_excludes_filing_after_signal_date` |
| 2 | Restatements do not rewrite history: for (company, concept, period) the **first-filed** value wins. | `test_first_filed_value_beats_later_amendment` |
| 3 | A ticker is in the cross-section at *t* only if it was an index member on *t*. | `test_member_absent_outside_interval` |
| 4 | Signal at month-end *t* is traded at the close of *t + lag_days* and earns nothing before then. | `test_execution_lag_skips_first_day` |
| 5 | Momentum is *t-12 → t-1*; month *t* is excluded. | `test_momentum_skips_most_recent_month` |
| 6 | Turnover is ½ Σ\|w − w⁻\| with w⁻ the **drifted** weight; both legs counted. | `test_turnover_against_hand_computed_case` |
| 7 | Raw downloads are never overwritten; every fetch appends to `data/raw/manifest.json` (URL, sha256, timestamp). | `test_fetch_refuses_to_overwrite_raw` |
| 8 | Every backtest run appends a row to `reports/specifications.csv`. N in the deflated Sharpe is that row count, never an argument. | `test_run_logs_specification` |
| 9 | Nothing in `src/` reads a knob that is not in `config.toml`. | review |

Two consequences worth spelling out:

- **A tweak that is not in `specifications.csv` did not happen.** If a
  factor looks bad and gets adjusted until it looks good, every adjustment
  is a row. The file is append-only.
- **No number in the README is typed from memory.** The results table is
  pasted from `reports/results.md`, which is written by `report.py`.

---

## Running it

Everything goes through `uv`; the lockfile is the environment.

```bash
uv sync                                    # once, and after pyproject changes
uv run pytest                              # tests
uv run ruff check . && uv run ruff format --check .
uv run backtester run --factor momentum    # phase 3 onward
```

`make check` is the gate for every phase (lint + tests). **There is no
`make` on this laptop**; run the two commands above instead, or install it
with `winget install GnuWin32.Make`. The Makefile is there for CI and other
machines.

Python is pinned to 3.12 in `.python-version` for wheel coverage
(polars, duckdb, pyarrow). 3.14 is also installed; do not let uv pick it.

---

## Layout

```
config.toml              every knob; sensitivity tables loop over this
src/backtester/
  config.py              frozen Config, load(), with_()
  universe.py            S&P 500 membership intervals      (phase 1)
  prices.py              daily prices, monthly returns     (phase 2)
  benchmarks.py          French factors, FRED RF           (phase 3)
  signals.py             raw signals + normalise()         (phases 3, 6)
  portfolio.py           the engine; any (month,ticker,z)  (phase 3)
  stats.py               IC, FM/NW, DSR, attribution       (phase 4)
  fundamentals.py        SEC FSDS, first_filed, asof_join  (phase 5)
  sectors.py             SIC -> 11 buckets                 (phase 5)
  report.py              4 charts, results.md              (phase 8)
  cli.py                 fetch | build | run | report
tests/
data/raw|interim|processed   gitignored; data/checks is committed
reports/figures, reports/specifications.csv   committed
```

Phases and their gates are in PLAN.md section 4. Do not start a phase
until the previous gate is green and committed.

---

## Conventions

- polars for every frame inside `src/`; pandas only where a library
  demands it (matplotlib, the statsmodels cross-check in tests).
- Every stored table is parquet with an explicit `as_of` column.
- Commit messages: a one-line sentence saying what is now true, then a body
  explaining why, in the style of the existing history (`git log`).
- Data lives in the folder; the raw zips are several GB and are not in git.
  The manifest that records what was fetched is.
- Datacentre IPs get rate-limited harder than laptops by SEC and yfinance;
  prefer copying `data/raw` between machines to re-fetching.
- Tickers: current members carry their current ticker back through
  history, removed names the ticker they were removed under. Renames the
  universe walk detects are in `data/interim/ticker_renames.parquet`.
- Anything hand-verified lives in `data/checks/` with its evidence in the
  row (`membership_overrides.csv`, `membership_spotcheck.csv`). Prefer an
  evidenced override row to a cleverer heuristic in `src/`.

## This machine

- `PYTHONIOENCODING=utf-8` before any Python that prints a polars frame or
  an em-dash; the console codepage is cp1252 and it will raise otherwise.
- The Bash tool truncates long heredocs silently (`unexpected EOF while
  looking for matching '`). Write files over ~150 lines with the Write tool.
- Wikipedia needs a `User-Agent`; `raw.USER_AGENT` is set for it.
