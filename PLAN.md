# Build plan

The brief ([Project Outline/01_Factor_Backtester.docx](Project%20Outline/01_Factor_Backtester.docx))
fixes *what* is built and the README fixes *what counts as done*. This file
fixes the *order* and the *contracts between modules*, so that each phase
has a gate and nothing downstream is started on an ungated upstream.

Working rule from the brief, section 7: **build momentum end to end and
validate it against UMD before touching the SEC data.** Everything below is
sequenced around that.

---

## 0. Invariants

These are the things the pipeline is wrong if it violates. Each has a test
named next to it, and the test is written before the code it guards.

| # | Invariant | Test |
|---|---|---|
| 1 | A fundamental used at month-end *t* was **filed** on or before *t − 1 day*. Joined as-of `filed`, never `period_end`. | `test_asof_join_excludes_filing_after_signal_date` — plants a filing dated *t* and asserts it is excluded; dated *t − 2* and asserts it is used |
| 2 | Restatements do not rewrite history: for a given (company, concept, period) the **first-filed** value wins. | `test_first_filed_value_beats_later_amendment` |
| 3 | A ticker is in the cross-section at *t* only if it was an index member on *t*. | `test_member_absent_outside_interval` |
| 4 | Signal at month-end *t* is traded at the close of the **next trading day** and earns nothing before then. | `test_execution_lag_skips_first_day` |
| 5 | Momentum is *t − 12 → t − 1*; month *t* is excluded. | `test_momentum_skips_most_recent_month` |
| 6 | Turnover is ½ Σ\|w − w⁻\| with w⁻ the **drifted** weight, both legs counted. | `test_turnover_against_hand_computed_case` |
| 7 | Raw downloads are never overwritten; every fetch is appended to `data/raw/manifest.json` with URL, sha256, timestamp. | `test_fetch_refuses_to_overwrite_raw` |
| 8 | Every backtest run appends a row to `reports/specifications.csv`. N in the deflated Sharpe is the row count, never an argument. | `test_run_logs_specification` |
| 9 | Nothing in `src/` reads a config value that is not in `config.toml`. Cost, lag, rebalance, weighting, winsor limits, universe, dates all live there. | (review, not test) |

---

## 1. Tooling

Proposed, not yet decided — see §6.

- **uv** for env and lockfile; Python 3.12 pinned in `.python-version`.
- **polars** for every frame in `src/`; **DuckDB** only inside `fundamentals.py`
  to chew the SEC `num.txt` files (several GB uncompressed). pandas appears
  only at the edges where a library demands it (matplotlib, statsmodels).
- **pyarrow / parquet** for every stored table, each with an explicit `as_of`
  column.
- **pytest**, **ruff**, **nbstripout**, driven by a `Makefile`:
  `make fetch`, `make build`, `make run`, `make report`, `make check`.
- **scipy** for Spearman and Φ; **statsmodels** kept only to cross-check the
  hand-written Newey-West in a test, not used in the pipeline.
- **matplotlib** for the four charts, saved to `reports/figures/` (committed).

---

## 2. Data flow

```
data/raw/           immutable downloads + manifest.json
  wikipedia/          sp500_changes_<date>.html
  sec/                2009q1.zip ... 2026q3.zip
  prices/             <ticker>.csv per pull
  french/             F-F_Research_Data_5_Factors_2x3.csv, F-F_Momentum_Factor.csv
  fred/               DGS1MO.csv
        |
        v  parse once, never by hand
data/interim/       one parquet per source, tidy, long
  membership.parquet        ticker, cik, start, end
  prices_daily.parquet      date, ticker, adj_close, volume, shares_out?
  fundamentals.parquet      cik, tag, period_end, qtrs, value, filed, adsh, form
  sectors.parquet           cik, sic, bucket
  french_monthly.parquet    month, mkt_rf, smb, hml, rmw, cma, umd, rf
        |
        v  month-end panels, every row stamped as_of
data/processed/
  returns_monthly.parquet   month, ticker, ret, ret_fwd_1d_lagged
  signals_raw.parquet       month, ticker, signal, value
  signals_z.parquet         month, ticker, signal, z       (winsor -> sector demean -> z)
  portfolios.parquet        month, factor, weighting, decile, ret_gross, ret_net, turnover
        |
        v
reports/
  figures/chart{1..4}_<factor>.png     committed
  specifications.csv                    committed — the N
  results.md                            table pasted into README
  methodology.pdf                       the 2-pager recruiters forward
```

---

## 3. Modules and their contracts

Every module exposes a small number of pure functions on polars frames.
The engine (`portfolio.py`) must accept **any** signal frame in the shape
`(month, ticker, z)` — that is the reuse contract for projects 2 and 7.

### `config.py`
Loads `config.toml` into a frozen dataclass. One source of truth for:
`start`, `end`, `cost_bps` (base 10; sensitivities 5, 25), `lag_days` (1),
`rebalance` ("M"), `weighting` ("ew" | "cw"), `winsor` (0.01, 0.99),
`n_deciles` (10), `momentum_window` (12, 1), `vol_window` (252).

### `universe.py`
- `parse_wikipedia_changes(html) -> Frame[ticker, added, removed, reason]`
- `build_membership(changes, current_members) -> Frame[ticker, start, end]`
  — walk backwards from today's constituents applying removals/additions.
- `members_at(membership, date) -> list[str]`
- Spot-check file `data/checks/membership_spotcheck.csv`: 20 changes verified
  against press releases (brief §10). Committed.

### `prices.py`
- `fetch(ticker, source) -> raw csv` — yfinance first, Stooq fallback.
- `build_daily(raw_dir) -> prices_daily.parquet`
- `monthly_returns(daily, lag_days) -> returns_monthly`
- `coverage_report(membership, daily) -> Frame[month, n_members, n_priced, gap_pct]`
  — the delisted-name gap as a % of universe-months, reported in README.

### `fundamentals.py`
- `ingest_quarter(zip) -> DuckDB` — `sub`, `num`, `tag`, `pre` loaded raw.
- `tag_map.toml` — the ~15 concepts each mapped to an ordered list of XBRL
  tags; coverage per concept per year is a committed table
  (`data/checks/tag_coverage.csv`).
- `first_filed(num) -> Frame` — dedupe on (cik, concept, period_end, qtrs),
  keep min `filed`.
- `asof_join(panel, fundamentals, buffer_days=1) -> Frame` — **the** join.
  Written once, tested first, used everywhere.
- `ttm(...)` and `latest_balance(...)` helpers for flow vs stock concepts.

### `sectors.py`
- SIC → 11 GICS-like buckets, hand-mapped in `sic_map.toml`. Unmapped SICs
  go to `Other` and are counted.

### `signals.py`
Each signal is `f(inputs) -> Frame[month, ticker, value]`:
`book_to_price`, `earnings_yield`, `momentum_12_1`, `gross_profitability`,
`accruals`, `asset_growth`, `volatility_252`, `beta`.
Then one normaliser: `normalise(raw, sectors, winsor) -> Frame[month, ticker, z]`
— winsorise at the config percentiles, demean within sector, divide by sector
std. `composite(zs) -> z` averages and re-standardises.

### `portfolio.py` — the engine
- `assign_deciles(z, n) -> Frame[month, ticker, decile]`
- `weights(deciles, caps, weighting) -> Frame[month, ticker, w]`
- `drift(w, daily_returns) -> w_minus`
- `turnover(w, w_minus)`
- `backtest(signal_z, returns, cfg) -> Frame[month, decile|LS, ret_gross, ret_net, turnover]`
  and, as a side effect, one row in `specifications.csv`.

### `stats.py`
`ic_series`, `ic_decay(horizons=[1,2,3,6,12]) -> half_life`, `fama_macbeth`,
`newey_west(lags=holding-1)`, `sharpe`, `max_drawdown`,
`deflated_sharpe(sr, n_trials, T, skew, kurt)`,
`attribution(ls_returns, french) -> alpha, betas, t-stats`, `breakeven_cost`.

### `benchmarks.py`
Ken French + FRED loaders → `french_monthly.parquet`.

### `report.py`
Four charts, the results table, the validation table, the sensitivity
tables. Writes `reports/results.md`; README is updated by hand from it so
that the numbers are looked at before they are published.

### `cli.py`
`backtester fetch | build | run --factor X | report`. Thin; every command
is one function call.

---

## 4. Phases and gates

Each phase ends at a gate. Do not start the next phase until the gate is
green and committed.

| Phase | Build | Gate |
|---|---|---|
| **0 Scaffold** | pyproject, uv lock, ruff, pytest, Makefile, `config.toml`, empty modules with docstrings, `CLAUDE.md` with the invariants | `make check` runs green on an empty suite |
| **1 Universe** | Wikipedia parse → `membership.parquet`, cross-check against an independent daily list, spot-check CSV | Invariant 3 test; ~500 names/month; unique names in window ≈ 820–850 (the brief's ~1,100 was high); agreement with the cross-check written down per year; 20 spot-checks pass |
| **2 Prices** | fetch all ever-members, coverage report, monthly returns with lag | Invariant 4, 7 tests; coverage gap % known and written down |
| **3 Momentum end to end** | `momentum_12_1` → `normalise` → `backtest` → long–short | Invariant 5, 6, 8 tests; **corr(LS, UMD) > 0.7**. If not, stop and find the leak |
| **4 Stats** | IC, decay, FM + NW, Sharpe, DD, DSR, attribution, break-even | NW matches statsmodels on a fixture; DSR matches a worked example from the paper |
| **5 Fundamentals** | SEC ingest via DuckDB, tag map, first-filed, `asof_join`, sectors | **Invariant 1, 2 tests** — the headline tests for the README; tag coverage table committed |
| **6 Value, quality, low vol** | remaining signals, composite | corr with HML > 0.7, RMW > 0.7; low vol attribution shows the beta/duration story |
| **7 Sensitivities** | cost 5/10/25, EW vs CW, rebalance frequency from half-life | one config loop, no rewrite; `specifications.csv` has every row |
| **8 Report** | four charts, results table, validation table, "What did not work", methodology PDF | README results table filled from `results.md`; no number typed by hand |

Time budget from the brief: 4–6 weeks. Rough split: 0–2 one week, 3–4 one
week, 5 one to two weeks (this is where the time goes), 6–8 one to two weeks.

---

## 5. Where it will break, and what is planned for each

From the brief §10, with the response decided up front rather than mid-crisis.

- **Delisted names.** Report the gap as % of universe-months. Run every
  result twice: full window, and window with the worst-covered months
  dropped. Both go in the README.
- **Restatements.** First-filed rule (invariant 2). The ratio of amended to
  original filings per year is logged so the reader can see the size of the
  choice.
- **Tag inconsistency.** Ordered tag lists per concept; coverage per year
  committed; a concept with <80% coverage in any year is flagged in the
  README, not silently filled.
- **Wikipedia errors pre-2010.** Window starts 2010; 20 spot-checks; the
  membership file records the source row for every interval.
- **Survivorship in your own head.** `specifications.csv` is append-only and
  timestamped. A tweak that is not logged did not happen, and the DSR is
  computed from the log.

---

## 6. Decisions to take before phase 0

1. **Package name.** Brief and README say flat `src/universe.py` etc. A
   package (`src/backtester/universe.py`) makes `uv run` and tests cleaner
   and keeps the same file names. Proposed: package.
2. **polars throughout, or pandas with DuckDB for SEC only?** Proposed:
   polars throughout — one frame type in `src/`, pandas at the edges.
3. **Market cap for cap-weighting.** Shares outstanding from SEC
   `dei:EntityCommonStockSharesOutstanding` (point-in-time, consistent with
   the rest) versus yfinance (easy, not point-in-time). Proposed: SEC, with
   yfinance as a coverage fallback that is logged.
4. **Python version.** 3.14 is on the machine; 3.12 has the widest wheel
   coverage for polars/duckdb/pyarrow. Proposed: 3.12.
5. **Where the `CLAUDE.md` invariants live.** Proposed: `CLAUDE.md` at the
   repo root carries §0 of this file verbatim so every session starts from
   it.
