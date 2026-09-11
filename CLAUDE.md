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
uv run pytest                              # 68 tests, ~3 s
uv run ruff check . && uv run ruff format --check .
uv run backtester fetch --step <universe|prices|benchmarks|fundamentals> --as-of YYYY-MM-DD
uv run backtester build --step <same>      # raw -> interim/processed + data/checks
uv run backtester run --factor momentum [--no-sector] [--note "..."]
uv run backtester run-all                  # the five reported factors, base spec
uv run backtester sensitivities            # cw, hold 3/6/12, no-sector: 25 logged runs
uv run backtester report                   # results.md, 4 charts, methodology.pdf
```

**All phases are built and run** (2026-09-11). The state of the data on
disk: 70 SEC zips (2009q1-2026q2, ~2.5 GB) under `data/raw/sec`, 679
yfinance price files, the French zips, all in `data/raw/manifest.json`.
`data/interim/sec_num.parquet` is the cached ingest (13M rows); pass
`reingest=True` to `fundamentals.build` after changing `tag_map.toml`,
otherwise new tags silently come back empty.

Every backtest appends to `reports/specifications.csv`; N is 61 as of the
last report. **Do not delete rows from it**, including the diagnostic runs
and the two broken first momentum attempts; the deflated Sharpe reads it.

`make check` is the gate (lint + tests). **There is no `make` on this
laptop**; run the two commands above instead. Python is pinned to 3.12.

---

## Layout

```
config.toml              every knob; sensitivity tables loop over this
src/backtester/
  config.py              frozen Config, load(), with_()
  raw.py, tables.py      write-once raw store + manifest; HTML table reader
  universe.py            S&P 500 membership, cross-check, overrides
  prices.py              yfinance pull, three cleaning rules, monthly returns with lag
  benchmarks.py          French factors + big-cap HML/RMW legs, FRED
  fundamentals.py        SEC FSDS via DuckDB, first_filed, asof_join, caps
  tag_map.toml           16 concepts, ordered XBRL tags
  sectors.py             CIK matching by name, SIC -> 11 buckets
  signals.py             signals, winsorise, sector z, composite
  portfolio.py           the engine; any (month, ticker, z); spec log
  stats.py               IC, decay, FM/NW, DSR, attribution, break-even
  run.py                 FACTORS registry, run_factor, run_all, sensitivities, replicate
  report.py              tables + 4 charts -> reports/results.md
  methodology.py         the 2-page PDF from the same numbers
  cli.py
tests/                   one file per module; invariants named in test names
data/raw|interim|processed   gitignored except raw/manifest.json
data/checks/             committed evidence; README.md there lists every file
reports/                 figures, results.md, methodology.pdf, specifications.csv
```

### Things a future session should know

- **Validation status.** Momentum vs UMD 0.79 (pass). Value and quality as
  reported are sector-neutral composites and score 0.25 / 0.07 vs HML / RMW;
  the join is validated by `run.replicate`: B/P cap-weighted terciles vs the
  big-cap HML leg 0.74 (0.89 from 2016). The RMW replication is 0.44 and
  that is a *coverage* limit of the XBRL data before 2013, documented, not
  fixed. Do not tune the reported factors to raise these numbers.
- **Cost convention** differs from the brief on purpose: every dollar
  traded pays c, `ret_net = ret_gross - 2c * turnover`.
- **Series stamping.** Long-short rows carry the *formation* month; anything
  compared with a French factor is shifted one month first
  (`stats.to_month_earned`, `run.validate`). Getting this wrong was the
  0.04-correlation bug.
- **Wikipedia's CIK can be a brand-new entity** (XOM); `sectors.cik_map`
  falls back to the name when a CIK has no filings.
- **Market cap** uses weighted-average diluted shares first; balance-sheet
  counts are mis-scaled for some filers. Caps under $1bn are dropped
  (`data/checks/market_cap_dropped.csv`).

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
