# Cross-Sectional Factor Backtester — Build Plan for Claude Code

This file is the build specification. Work through it one step at a time.

## How to use this file

Copy it to the repo root as `BUILD_PLAN.md`. Then in Claude Code, say:

> Read BUILD_PLAN.md. Do step 0.1 only. Stop when its "Done when" condition is met and show me the test output.

Then `Do step 0.2 only`, and so on. Never let it do a whole phase at once.

## Global rules (apply to every step)

1. One step per session. After finishing a step, run `make test`, show the output, and stop. Do not start the next step.
2. Every parameter that affects returns lives in `config/base.yaml`. No hardcoded numbers in `src/`.
3. SEC `num.txt` and `sub.txt` are read with DuckDB only. Never `pd.read_csv` on them.
4. Every parquet in `data/processed/` has an `asof_date` column and a `fetched_at` column.
5. Never overwrite a file in `data/raw/`. New pulls get a new filename with the fetch date.
6. Every function that uses a date must only use data dated on or before that date. Add an assertion where practical.
7. Every run of `run.py` appends a row to `reports/specifications.csv` before computing anything.
8. Write a test for every step that has one listed. Tests live in `tests/`. Use pytest.
9. Use polars for dataframes unless a library needs pandas (statsmodels, yfinance). Convert at the boundary.
10. Type hints on every function. Docstring says what date convention the function assumes.
11. Do not add features, refactor other modules, or "improve" earlier steps unless the current step says so.
12. If a step cannot be completed as written, stop and explain why. Do not work around it silently.

---

# Phase 0 — Repo foundation

## Step 0.1 — Project skeleton

**Build**
- `pyproject.toml` with project name `factor_backtester`, Python 3.11, dependencies: `polars`, `duckdb`, `pandas`, `numpy`, `scipy`, `statsmodels`, `yfinance`, `pandas-datareader`, `requests`, `beautifulsoup4`, `lxml`, `pyyaml`, `pyarrow`, `matplotlib`. Dev dependencies: `pytest`, `ruff`, `nbstripout`. Pin all versions to current stable.
- Directories with `.gitkeep`: `src/factor_backtester/`, `src/factor_backtester/signals/`, `src/factor_backtester/agents/`, `tests/`, `tests/fixtures/`, `config/`, `manifests/`, `decisions/`, `data/raw/`, `data/interim/`, `data/processed/`, `reports/figures/`, `notebooks/`.
- `src/factor_backtester/__init__.py` and `src/factor_backtester/signals/__init__.py` and `src/factor_backtester/agents/__init__.py`.
- `Makefile` with targets: `setup` (pip install -e ".[dev]"), `test` (pytest -q), `lint` (ruff check src tests), `data` (placeholder echo), `run` (placeholder echo), `report` (placeholder echo).
- `.pre-commit-config.yaml` with ruff and nbstripout.

**Test**
- `tests/test_smoke.py`: imports `factor_backtester` and asserts `True`.

**Done when** `make setup && make test` passes with 1 test.

## Step 0.2 — Config loader

**Build**
- `config/base.yaml`:
  ```yaml
  universe: sp500
  start_date: "2010-01-31"
  end_date: null            # null means today
  rebalance: monthly
  holding_months: 1
  execution_lag_days: 1
  filing_buffer_days: 1
  winsor_lower: 0.01
  winsor_upper: 0.99
  sector_neutral: true
  weighting: [equal, cap]
  n_deciles: 10
  cost_bp_base: 10
  cost_bp_sensitivity: [5, 10, 25]
  cost_bp_curve: [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
  momentum_lookback: 12
  momentum_skip: 1
  vol_window_days: 252
  beta_window_days: 252
  ic_horizons: [1, 2, 3, 6, 12]
  newey_west_lag: null      # null means holding_months - 1
  price_conflict_threshold: 0.01
  min_concept_coverage: 0.90
  ```
- `src/factor_backtester/config.py`: `load_config(path: str = "config/base.yaml") -> dict`. Resolves `end_date: null` to today. Resolves `newey_west_lag: null` to `holding_months - 1`. Returns a plain dict. Also `config_hash(cfg: dict) -> str` returning the first 12 chars of sha256 of the sorted JSON dump.

**Test**
- `tests/test_config.py`: loads config, asserts `end_date` is a date string, asserts `newey_west_lag == 0`, asserts `config_hash` is stable across two loads and changes when a value changes.

**Done when** tests pass.

## Step 0.3 — Specification log

**Build**
- `src/factor_backtester/speclog.py`: `log_specification(cfg: dict, description: str, path: str = "reports/specifications.csv") -> str`. Appends a row: `timestamp_utc, config_hash, git_commit, description, config_json`. Creates the file with a header if absent. Returns the config hash. Get git commit via `subprocess` (`git rev-parse --short HEAD`), fall back to `"nogit"`.
- `src/factor_backtester/speclog.py`: `count_specifications(path) -> int`. Number of distinct `config_hash` values.

**Test**
- `tests/test_speclog.py`: writes to a tmp path, logs 3 rows with 2 distinct configs, asserts `count_specifications == 2`.

**Done when** tests pass.

## Step 0.4 — README truth

**Build**
- Edit `README.md`: rename the `## Layout` section to `## Planned layout`, add a line at the top of it: "Built incrementally per BUILD_PLAN.md. Modules listed here exist once their step is done."
- Add a `## Build status` section with a checklist of phases 0 to 11, all unchecked.

**Done when** README renders with the new sections. No test.

---

# Phase 1 — Universe

## Step 1.1 — Wikipedia fetch and parse

**Build**
- `src/factor_backtester/universe.py`:
  - `fetch_wikipedia_html(save_dir: str = "data/raw/universe") -> str`: GET `https://en.wikipedia.org/wiki/List_of_S%26P_500_companies`, save to `save_dir/sp500_<YYYYMMDD>.html`, return path. Use a browser User-Agent header.
  - `parse_current_constituents(html_path: str) -> pl.DataFrame`: columns `ticker, company, gics_sector, gics_sub_industry, date_added, cik`. Ticker normalised: `.` replaced with `-` (BRK.B → BRK-B).
  - `parse_changes_table(html_path: str) -> pl.DataFrame`: columns `date, action, ticker, company, reason`. `action` is `"add"` or `"remove"`. One row per ticker per action. Handle rows where the added or removed cell is empty. Handle multi-line cells.
- Write `manifests/universe.json` on every fetch: `{fetched_at, html_path, sha256, n_current, n_changes}`.

**Test**
- `tests/fixtures/sp500_sample.html`: save a copy of the live page.
- `tests/test_universe_parse.py`: parse the fixture, assert current count between 500 and 505, assert changes table has both actions, assert no null tickers, assert dates parse.

**Done when** tests pass.

## Step 1.2 — Membership intervals

**Build**
- `universe.py`: `build_membership_intervals(current: pl.DataFrame, changes: pl.DataFrame, start_date: str) -> pl.DataFrame` with columns `ticker, start, end` where `end` is null for current members. Algorithm: start from the current list with `end = null`, walk the changes table backwards in time; a `remove` on date d means the ticker was a member until d (open an interval ending d); an `add` on date d closes the most recent open interval for that ticker at start d. Any ticker still open at `start_date` gets `start = start_date`.
- `config/ticker_aliases.yaml`: mapping of old ticker → new ticker for renames (start with FB→META, GOOG/GOOGL, ANTM→ELV; add as discovered). Apply before building intervals.
- `universe.py`: `membership_at(intervals: pl.DataFrame, date) -> list[str]`.
- `universe.py`: `monthly_membership(intervals, start_date, end_date) -> pl.DataFrame` with columns `asof_date, ticker`, one row per member per month end.
- Save to `data/processed/universe_monthly.parquet` with `fetched_at`.

**Test**
- `tests/test_universe_intervals.py`: build intervals from fixture, assert for every month end from `start_date` the count is between 490 and 510, assert no ticker has overlapping intervals.

**Done when** tests pass and the parquet exists.

## Step 1.3 — Spot-check fixture

**Build**
- `tests/fixtures/universe_spotcheck.csv`: 20 rows of `date, action, ticker` chosen at random from the changes table after 2010. Verify each manually against a press release and add a `source_url` column. Do this verification with a web search per row; do not invent URLs.
- `tests/test_universe_spotcheck.py`: for each row, assert the parsed changes table contains it.

**Done when** all 20 pass. If any fail, that is a parser bug, fix the parser, not the fixture.

---

# Phase 2 — Prices

## Step 2.1 — Dual-source fetch

**Build**
- `src/factor_backtester/prices.py`:
  - `fetch_yfinance(tickers: list[str], start: str, end: str) -> pl.DataFrame`: columns `date, ticker, adj_close, close, volume, source="yfinance"`. Batch in groups of 50. Retry twice on failure. Record failures.
  - `fetch_stooq(tickers, start, end) -> pl.DataFrame`: same schema, `source="stooq"`. Stooq US tickers need a `.US` suffix.
  - `fetch_all(intervals: pl.DataFrame, cfg: dict) -> None`: every ticker that ever appears in intervals, from `start_date` minus 400 calendar days (momentum and vol need lookback) to `end_date`. Save raw pulls to `data/raw/prices/<source>_<YYYYMMDD>.parquet`.
- Write `manifests/price_fetch.json`: per ticker, per source: `first_date, last_date, n_rows, error`.

**Test**
- `tests/test_prices_fetch.py`: fetch `["AAPL", "MSFT"]` for one month from both sources, assert both return rows, assert schema matches.

**Done when** the manifest lists every ticker in the interval table and tests pass.

## Step 2.2 — Reconcile and gap report

**Build**
- `prices.py`: `monthly_returns(prices: pl.DataFrame) -> pl.DataFrame` with columns `asof_date, ticker, ret` using month-end adj_close.
- `prices.py`: `reconcile_sources(yf: pl.DataFrame, stooq: pl.DataFrame, threshold: float) -> pl.DataFrame`: join monthly returns from both sources, flag rows where `abs(ret_yf - ret_stooq) > threshold`. Save to `manifests/price_conflicts.csv`.
- `prices.py`: `gap_report(intervals, prices, cfg) -> pl.DataFrame`: for each ticker-month in `universe_monthly.parquet`, whether a price exists. Save `manifests/price_gaps.csv` with `ticker, expected_start, expected_end, actual_start, actual_end, missing_months`. Compute `gap_pct = missing ticker-months / total ticker-months` and write it into `manifests/price_fetch.json`.
- `prices.py`: `build_processed_prices() -> None`: prefer yfinance, fall back to stooq where yfinance is missing, save `data/processed/prices_daily.parquet` with `date, ticker, adj_close, volume, source, fetched_at`.

**Test**
- `tests/test_prices_reconcile.py`: construct two small frames with one deliberate 5% disagreement, assert exactly one flag.

**Done when** `gap_pct` is written and conflict rows are under 1% of ticker-months. If over 1%, list the worst 20 tickers in `decisions/price_conflicts_review.md` and stop.

## Step 2.3 — Market cap

**Build**
- `prices.py`: `shares_outstanding_yf(tickers) -> pl.DataFrame` as a temporary source of shares (replaced by SEC in step 4.6). Columns `ticker, shares, asof_date`.
- `prices.py`: `market_cap(prices, shares) -> pl.DataFrame` with `asof_date, ticker, mcap` at month ends.

**Test** none beyond schema. **Done when** `data/processed/mcap_monthly.parquet` exists.

---

# Phase 3 — Momentum end to end (the engine)

## Step 3.1 — Signal interface

**Build**
- `src/factor_backtester/signals/base.py`:
  - `SIGNAL_SCHEMA = {"asof_date": pl.Date, "ticker": pl.Utf8, "signal": pl.Float64}`.
  - `validate_signal(df: pl.DataFrame) -> pl.DataFrame`: asserts columns and dtypes, asserts no duplicate `(asof_date, ticker)`, asserts every `asof_date` is a month end. Returns df.
  - `restrict_to_universe(df, universe_monthly) -> pl.DataFrame`: inner join on `(asof_date, ticker)`.

**Test**
- `tests/test_signal_schema.py`: valid frame passes, duplicate row raises, non-month-end date raises.

**Done when** tests pass.

## Step 3.2 — Momentum signal

**Build**
- `src/factor_backtester/signals/momentum.py`: `momentum(prices_daily, cfg) -> pl.DataFrame`. At each month end t, signal = product of (1 + monthly return) for months t-12 to t-2 (with `momentum_lookback=12`, `momentum_skip=1`), minus 1. Requires all 11 monthly returns present, else null. Uses only prices with `date <= t`.

**Test**
- `tests/test_momentum.py`: synthetic daily prices for 2 tickers over 14 months with known returns, assert the momentum value at the last month end matches a hand-computed number to 1e-10. Also assert that changing the price on a date after t does not change the signal at t.

**Done when** tests pass.

## Step 3.3 — Normalisation

**Build**
- `src/factor_backtester/signals/normalise.py`:
  - `winsorise(df, lower, upper) -> pl.DataFrame`: per `asof_date`, clip `signal` to the [lower, upper] quantiles.
  - `zscore(df, by: list[str] = ["asof_date"]) -> pl.DataFrame`: per group, `(signal - mean) / std`. If `sector` in `by` and the column is absent, fall back to `["asof_date"]` and log a warning (sectors arrive in Phase 4).
  - `normalise(df, cfg, sectors: pl.DataFrame | None = None) -> pl.DataFrame`: winsorise then zscore, sector-neutral if `cfg["sector_neutral"]` and sectors provided. Output column `z`.

**Test**
- `tests/test_normalise.py`: per-date mean of `z` is 0 and std is 1 to 1e-8; winsorise clips the max to the 99th percentile.

**Done when** tests pass.

## Step 3.4 — Portfolio construction

**Build**
- `src/factor_backtester/portfolio.py`:
  - `assign_deciles(df, n) -> pl.DataFrame`: per `asof_date`, rank `z` into `n` equal-count buckets, column `decile` (1 = lowest z, n = highest).
  - `target_weights(df, weighting: str, mcap: pl.DataFrame | None) -> pl.DataFrame`: per `(asof_date, decile)`, weights sum to 1. `"equal"` or `"cap"`.
  - `long_short_weights(df) -> pl.DataFrame`: top decile weights minus bottom decile weights, each leg summing to 1.
  - `holding_returns(weights, prices_daily, cfg) -> pl.DataFrame`: for each `asof_date` t, entry at the close on the first trading day strictly after t plus `execution_lag_days - 1` (lag 1 = next trading day close), exit at the close on the first trading day after the next month end plus the same lag. Return per portfolio = sum of `weight × (exit/entry - 1)`. Output `asof_date, portfolio, gross_ret`. Portfolio labels: `D1..D10`, `LS`.
  - `drifted_weights(weights, prices_daily, cfg) -> pl.DataFrame`: weight at the end of the holding period after price drift, before rebalancing.
  - `turnover(target_t, drifted_tminus1) -> pl.DataFrame`: `0.5 * sum(abs(w_t - w_{t-1}^drift))` per portfolio per date. For `LS`, sum both legs.
  - `net_returns(gross, turnover, cost_bp) -> pl.DataFrame`: `net_ret = gross_ret - cost_bp/1e4 * turnover`.
  - `run_portfolio(signal_z, prices_daily, mcap, cfg, weighting, cost_bp) -> pl.DataFrame`: chains the above, returns `asof_date, portfolio, gross_ret, turnover, net_ret`.

**Test**
- `tests/test_portfolio.py`: 20 synthetic tickers, 3 months. Assert decile counts equal within 1. Assert weights sum to 1 per decile. Assert turnover on a month where the portfolio does not change is 0 and where it fully changes is 1 (equal weight, no drift). Assert that entry price is dated strictly after `asof_date`.

**Done when** tests pass.

## Step 3.5 — Basic statistics

**Build**
- `src/factor_backtester/stats.py`:
  - `rank_ic(signal_z, forward_returns) -> pl.DataFrame`: per `asof_date`, Spearman correlation of `z` with next-month return. Output `asof_date, ic`.
  - `ic_summary(ic) -> dict`: `mean_ic, std_ic, ic_tstat (mean/std*sqrt(T)), ic_ir_annual (mean/std*sqrt(12))`.
  - `perf_summary(ret: pl.Series, periods_per_year=12) -> dict`: `ann_return, ann_vol, sharpe, max_drawdown, skew, kurtosis, n_obs`. Sharpe uses excess returns if an `rf` series is passed.
  - `breakeven_cost(gross_ret, turnover) -> float`: the cost in bp at which mean net return is 0: `mean(gross) / mean(turnover) * 1e4`.
  - `cost_curve(gross_ret, turnover, cost_bps: list[int]) -> pl.DataFrame`: net Sharpe per cost.

**Test**
- `tests/test_stats.py`: known series with hand-computed Sharpe and drawdown; breakeven of a series with mean gross 1% and mean turnover 0.5 equals 200 bp.

**Done when** tests pass.

## Step 3.6 — Benchmarks and risk-free

**Build**
- `src/factor_backtester/benchmarks.py`:
  - `fetch_french_factors() -> pl.DataFrame`: monthly `Mkt-RF, SMB, HML, RMW, CMA, RF` from the 5-factor file and `UMD` from the momentum file, via `pandas_datareader` or direct zip download from the Ken French library. Columns `asof_date, mkt_rf, smb, hml, rmw, cma, umd, rf` in decimals. Save `data/processed/french_monthly.parquet`.
  - `fetch_aqr_bab() -> pl.DataFrame`: BAB US monthly from AQR's data library xlsx. Save `data/processed/aqr_bab_monthly.parquet`. If the download fails, log it and continue (used only in Phase 8).
  - `correlation_with_benchmark(ls_returns, bench_series) -> float`.

**Test**
- `tests/test_benchmarks.py`: French frame has no nulls after 2010, `rf` monthly is between 0 and 0.01.

**Done when** tests pass and both parquets exist (BAB may be absent with a logged reason).

## Step 3.7 — First end-to-end run

**Build**
- `run.py` at repo root:
  1. `load_config`, `log_specification(cfg, description=sys.argv[1] if given else "run")`.
  2. Load universe, prices, mcap, French.
  3. For each signal in a `SIGNALS` registry (only `momentum` for now): compute signal → `restrict_to_universe` → `normalise` → for each weighting → for each cost in `cost_bp_sensitivity` → `run_portfolio` → `perf_summary`, `ic_summary`, `breakeven_cost`, `cost_curve`.
  4. Write `reports/results.csv` (one row per signal × weighting × cost) and `reports/returns_monthly.parquet` (all portfolio return series).
  5. Print momentum LS correlation with UMD.
- Update `Makefile` `run` target to `python run.py`.

**Test**
- `tests/test_run_smoke.py`: runs `run.py` on a 24-month slice via an env var `FB_TEST_SLICE=1` and asserts `results.csv` has rows.

**Done when** momentum LS (equal weight, 10 bp) correlates above 0.70 with UMD over the full window and deciles D1→D10 have monotonically increasing mean gross return (allow 1 inversion). If either fails, stop and write the diagnosis to `decisions/momentum_validation.md`. Do not proceed to Phase 4 until this passes.

---

# Phase 4 — SEC fundamentals

## Step 4.1 — Download SEC Financial Statement Data Sets

**Build**
- `src/factor_backtester/fundamentals.py`:
  - `list_sec_quarters(start_year=2009) -> list[str]`: `["2009q1", ..., current]`.
  - `download_sec_quarter(q: str, save_dir="data/raw/sec") -> str`: GET `https://www.sec.gov/files/dera/data/financial-statement-data-sets/<q>.zip`. SEC requires a User-Agent with contact email; read it from env `SEC_USER_AGENT`, fail loudly if unset. Skip if the file already exists. Rate limit to 1 request per second.
- Write `manifests/sec_download.json`: per quarter, `path, size_bytes, sha256, downloaded_at`.

**Test**
- `tests/test_sec_download.py`: downloads `2015q1` only if not present, asserts the zip contains `sub.txt, num.txt, tag.txt, pre.txt`.

**Done when** all quarters from 2009q1 are present in the manifest.

## Step 4.2 — Load into DuckDB

**Build**
- `fundamentals.py`:
  - `load_sec_to_duckdb(db_path="data/interim/sec.duckdb", raw_dir="data/raw/sec") -> None`: for each zip, read `sub.txt` and `num.txt` with `read_csv` inside DuckDB (tab-delimited, `all_varchar=true` then cast), append into tables `sub` and `num` with an added column `quarter`. Load `tag.txt` once into `tag` (union distinct across quarters). Idempotent: skip quarters already loaded (track in a `loaded_quarters` table).
  - Cast `sub.filed` and `sub.period` to DATE, `num.value` to DOUBLE, `num.ddate` to DATE, `num.qtrs` to INTEGER.
  - Create indexes on `sub(adsh)`, `num(adsh, tag)`.

**Test**
- `tests/test_sec_load.py`: load a single quarter into a tmp db, assert row counts are positive, assert `filed` is DATE type.

**Done when** all quarters loaded and `SELECT COUNT(*) FROM num` is above 100 million (order of magnitude check).

## Step 4.3 — Filter to original filings

**Build**
- `fundamentals.py`: `original_filings_view(con) -> None`: creates view `sub_orig` = `sub` where `form IN ('10-K', '10-Q')` (exclude `/A` amendments) and `prevrpt = 0`. Document in the docstring: amendments are excluded so the first-filed value is used.

**Test**
- `tests/test_sec_original.py`: assert no `form LIKE '%/A'` in `sub_orig`.

**Done when** tests pass.

## Step 4.4 — Tag map and coverage

**Build**
- `config/tag_map.yaml`: for each concept, an ordered list of XBRL tags to try. Concepts and starting tags:
  ```yaml
  total_assets: [Assets]
  total_equity: [StockholdersEquity, StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest]
  revenue: [Revenues, RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet, RevenueFromContractWithCustomerIncludingAssessedTax]
  cogs: [CostOfRevenue, CostOfGoodsAndServicesSold, CostOfGoodsSold]
  net_income: [NetIncomeLoss, ProfitLoss]
  operating_cash_flow: [NetCashProvidedByUsedInOperatingActivities]
  current_assets: [AssetsCurrent]
  current_liabilities: [LiabilitiesCurrent]
  cash: [CashAndCashEquivalentsAtCarryingValue, CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents]
  total_liabilities: [Liabilities]
  long_term_debt: [LongTermDebtNoncurrent, LongTermDebt]
  shares_outstanding: [CommonStockSharesOutstanding, EntityCommonStockSharesOutstanding, WeightedAverageNumberOfDilutedSharesOutstanding]
  eps_diluted: [EarningsPerShareDiluted]
  operating_income: [OperatingIncomeLoss]
  depreciation: [DepreciationDepletionAndAmortization, DepreciationAndAmortization]
  ```
- `fundamentals.py`:
  - `extract_concepts(con, tag_map) -> pl.DataFrame`: for each concept, for each filing in `sub_orig`, take the first tag in the list that has a value with `qtrs` matching the concept type (balance sheet concepts `qtrs=0`; flow concepts: take `qtrs=4` from 10-K, `qtrs=1` from 10-Q) and `coreg IS NULL` (consolidated only). Output `cik, adsh, form, period, filed, concept, value, tag_used`.
  - `coverage_report(df, universe_ciks) -> pl.DataFrame`: per concept per fiscal year, share of universe CIKs with a value. Save `manifests/tag_coverage.csv`.

**Test**
- `tests/test_tag_map.py`: every concept in `tag_map.yaml` produces at least one row; `tag_used` is always in the list for that concept.

**Done when** every concept has coverage above `min_concept_coverage` for every year from 2010. If not, add tags to the map (research the missing filers' tags via DuckDB queries on `num` for those CIKs) and rerun. Log each tag added in the commit message.

## Step 4.5 — Trailing twelve months for flow concepts

**Build**
- `fundamentals.py`: `ttm(df) -> pl.DataFrame`: for flow concepts, at each 10-Q build TTM = last 10-K annual value + sum of quarters since fiscal year end − sum of same quarters prior year. At each 10-K, TTM = annual value. Output the same schema with `concept` suffixed `_ttm`. Require all inputs present, else null.

**Test**
- `tests/test_ttm.py`: synthetic 8 quarters with known values, assert TTM at Q2 equals hand computation.

**Done when** tests pass.

## Step 4.6 — The as-of join

**Build**
- `fundamentals.py`:
  - `cik_ticker_map(con) -> pl.DataFrame`: from SEC `company_tickers.json` (download to `data/raw/sec/company_tickers_<date>.json`), columns `cik, ticker`. Apply `ticker_aliases.yaml`.
  - `asof_fundamentals(concepts: pl.DataFrame, asof_dates: list[date], buffer_days: int) -> pl.DataFrame`: for each `asof_date` and each CIK, the value from the latest filing with `filed + buffer_days <= asof_date`. Implement with `join_asof` in polars on `filed` shifted by `buffer_days`, strategy `backward`. Output `asof_date, ticker, concept, value, filed, period`.
  - Assertion inside: `max(filed + buffer) <= asof_date` for every output row.
- Save `data/processed/fundamentals_monthly.parquet`.

**Test**
- `tests/test_point_in_time.py` — THE test. Fixture: one CIK, three filings of `total_assets` with `filed` dates 2020-02-15 (value 100), 2020-05-10 (value 110), 2020-08-05 (value 120). Signal date 2020-05-31 with buffer 1 day → assert value is 110. Signal date 2020-05-10 with buffer 1 → assert value is 100 (filed same day is excluded by the buffer). Signal date 2020-08-31 → 120. A filing dated 2020-09-01 with value 999 must never appear at any of those dates.
- Copy the body of this test verbatim into the README under a new top section `## The point-in-time test`.

**Done when** tests pass and the README shows the test.

## Step 4.7 — Sectors

**Build**
- `fundamentals.py`: `sic_codes(con) -> pl.DataFrame` from `sub.sic` (latest per CIK).
- `config/sic_to_sector.yaml`: map SIC ranges to 11 buckets: energy, materials, industrials, consumer_discretionary, consumer_staples, health_care, financials, information_technology, communication_services, utilities, real_estate. Write the ranges by hand from the SEC SIC list. Fallback: use `gics_sector` from the Wikipedia current table for any ticker without SIC.
- `fundamentals.py`: `sector_map() -> pl.DataFrame` with `ticker, sector`. Save `data/processed/sectors.parquet`.

**Test**
- `tests/test_sectors.py`: every ticker in `universe_monthly` has a sector; every sector has at least 10 tickers.

**Done when** tests pass.

## Step 4.8 — Replace yfinance shares with SEC shares

**Build**
- `prices.py`: `market_cap` now takes `shares_outstanding` from `fundamentals_monthly.parquet` (as-of). Keep yfinance shares as fallback where SEC is null; log the fallback count in `manifests/mcap.json`.

**Done when** `mcap_monthly.parquet` is rebuilt and the fallback count is under 5% of ticker-months.

---

# Phase 5 — Remaining signals

Each signal file returns the Step 3.1 schema and uses only as-of data. Each has a test asserting a hand-computed value on a 2-ticker fixture and asserting that a later-dated filing does not change the signal.

## Step 5.1 — Value
- `signals/value.py`: `book_to_price = total_equity / mcap`, `earnings_yield = net_income_ttm / mcap`. Composite `value` = re-standardised mean of the two z-scores. Register all three.

## Step 5.2 — Quality
- `signals/quality.py`: `gross_profitability = (revenue_ttm - cogs_ttm) / total_assets`, `accruals = -(net_income_ttm - operating_cash_flow_ttm) / total_assets` (sign so higher is better), `asset_growth = -(total_assets / total_assets_12m_ago - 1)` (sign so higher is better). Composite `quality` = mean z of `gross_profitability` and `accruals`. Register all four.

## Step 5.3 — Low volatility
- `signals/lowvol.py`: `low_vol = -std(daily returns over vol_window_days)`, `low_beta = -beta vs mkt_rf over beta_window_days` (daily French Mkt-RF; add `fetch_french_daily` to `benchmarks.py`). Register both.

## Step 5.4 — Composite
- `signals/composite.py`: `composite` = re-standardised mean z of `momentum, value, quality, low_vol`.

## Step 5.5 — Sector neutralisation on
- Update `run.py` to pass `sectors.parquet` into `normalise`. Confirm `sector_neutral: true` now demeans within sector.
- Generic assertion added to `normalise`: fail if any input row has a `filed` column with `filed + buffer > asof_date`.

**Done when** all signal tests pass and `run.py` executes with every registered signal on the test slice.

---

# Phase 6 — Full backtest run

## Step 6.1 — Full grid
- `run.py`: every registered signal × `[equal, cap]` × `cost_bp_sensitivity`. Write `reports/results.csv` and `reports/returns_monthly.parquet`.

## Step 6.2 — Cost curves
- `run.py`: for each signal and weighting, `cost_curve` over `cost_bp_curve`. Write `reports/cost_curves.csv`.

## Step 6.3 — Regression check
- `tests/test_momentum_regression.py`: momentum LS vs UMD correlation still above 0.70 after all Phase 4 and 5 changes. Store the Phase 3.7 correlation in `tests/fixtures/momentum_baseline.json` and assert the new value is within 0.05 of it.

**Done when** the full grid runs and the regression test passes.

---

# Phase 7 — Advanced statistics

## Step 7.1 — Fama-MacBeth
- `stats.py`: `fama_macbeth(signal_z_wide: pl.DataFrame, forward_returns) -> dict`: at each date, OLS of next-month return on the z-score columns; return time series of lambdas and their means. Use statsmodels.

## Step 7.2 — Newey-West
- `stats.py`: `newey_west_se(series: np.ndarray, lag: int) -> float` implementing the formula in brief 6.3. `fama_macbeth` reports `lambda_mean, nw_se, nw_tstat` with `lag = cfg["newey_west_lag"]`.
- Test: against `statsmodels` HAC with the same lag on a known series, within 1e-6.

## Step 7.3 — IC decay
- `stats.py`: `ic_decay(signal_z, monthly_returns, horizons) -> pl.DataFrame` with IC at each horizon h (signal at t vs return over t+1..t+h). `half_life(decay) -> float`: fit `IC_h = IC_1 * exp(-k h)`, return `ln(2)/k`.

## Step 7.4 — Deflated Sharpe
- `stats.py`: `expected_max_sharpe(n_trials, sr_variance) -> float` and `deflated_sharpe(sr, sr0, T, skew, kurt) -> float` per brief 6.5. `n_trials = count_specifications()`. `sr_variance` = variance of Sharpe across the rows of `results.csv`.
- Test: with `n_trials=1`, `sr0=0` and DSR reduces to `Phi(sr*sqrt(T-1)/sqrt(1 - skew*sr + (kurt-1)/4*sr^2))`.

## Step 7.5 — Factor attribution
- `stats.py`: `attribution(ls_returns, french) -> dict`: OLS of LS on `mkt_rf, hml, umd, rmw`, report alpha (annualised), betas, t-stats (Newey-West), R².

## Step 7.6 — Wire into run.py
- Add `fm_lambda, fm_nw_tstat, mean_ic, ic_tstat, half_life, dsr, alpha_ann, alpha_tstat, r2` columns to `results.csv`.

**Done when** all Phase 7 tests pass and `results.csv` has the new columns for every row.

---

# Phase 8 — Validation and known failures

## Step 8.1 — Validation table
- `src/factor_backtester/validate.py`: correlations of `momentum` LS vs `umd`, `gross_profitability` LS vs `rmw`, `book_to_price` LS vs `hml`, `low_beta` LS vs AQR BAB (if present). Thresholds from a new `config/validation.yaml`: momentum 0.70, gross_profitability 0.60, book_to_price 0.60, low_beta 0.50. Write `reports/validation.csv` with `series, benchmark, correlation, threshold, pass`.
- `run.py` calls this last and prints the table.

## Step 8.2 — Delisting sensitivity
- `run.py --delisting-mode {drop, terminal}`: `drop` excludes ticker-months in `price_gaps.csv`; `terminal` assigns a −30% return on the last available month for tickers that were removed from the universe with no subsequent price. Write both to `reports/results_delisting_<mode>.csv`.

## Step 8.3 — Weighting decomposition
- `stats.py`: `weighting_gap(equal_ls, cap_ls, french) -> dict`: regress `(equal − cap)` on `smb`, report beta and R². Write `reports/weighting_gap.csv`.

## Step 8.4 — What did not work
- `src/factor_backtester/research_log.py`: `build_what_did_not_work(spec_csv, git_log) -> str`: for every `config_hash` in `specifications.csv` that is not the current one, one line: description, date, and the commit message of the commit that superseded it. Write `reports/what_did_not_work.md`.

**Done when** every row of `validation.csv` passes or has a paragraph in `decisions/validation_failures.md` explaining why.

---

# Phase 9 — Deliverables

## Step 9.1 — Charts
- `src/factor_backtester/report.py` producing into `reports/figures/`:
  - `fig1_decile_cumret.png`: 2×2 panels (momentum, value, quality, low_vol), cumulative log return of D1..D10.
  - `fig2_rolling_ic.png`: rolling 36-month mean IC per factor, zero line, NBER recession shading (hardcode 2020-02 to 2020-04 and read others from FRED `USREC`).
  - `fig3_ic_decay.png`: IC by horizon per factor with the fitted exponential and half-life in the legend.
  - `fig4_cost_curve.png`: net Sharpe vs cost bp per factor, zero line, break-even marked.
- Matplotlib only, 150 dpi, consistent palette.

## Step 9.2 — README rebuild
- `report.py`: `write_readme()` regenerates `README.md` from `README.template.md` with placeholders for the results table, validation table, gap_pct, what-did-not-work, and the 4 figures. Template keeps the point-in-time test at the top. Build status checklist updated.

## Step 9.3 — Methodology note
- `reports/methodology.md` (2 pages when rendered): data, point-in-time convention, signal definitions, portfolio rules, cost model, statistics, validation, limitations. `make report` renders to `reports/methodology.pdf` with pandoc.

**Done when** `make data && make run && make report` reproduces the README from a clean clone.

---

# Phase 10 — Orchestration and incremental refresh

## Step 10.1 — Dagster project
- Add `dagster` and `dagster-webserver` to dependencies. `orchestration/` package with `definitions.py`. One asset per processed parquet: `universe_monthly, prices_daily, mcap_monthly, sec_raw, fundamentals_monthly, sectors, french_monthly, aqr_bab, signal_<name> (one per registered signal), returns_monthly, results, validation, figures, readme`. Dependencies match the data flow.

## Step 10.2 — Incremental fetch
- Each fetch function accepts `since: date | None` read from its manifest. Universe: refetch the page, diff intervals, append. Prices: pull last 45 days for active tickers, full history for new tickers, upsert on `(date, ticker)`. SEC: download only quarters not in the manifest. Benchmarks: refetch fully (small).
- Schedules: prices weekly (Sunday), universe monthly (1st), SEC quarterly (check monthly, download if new), benchmarks monthly.

## Step 10.3 — Incremental compute
- Signal and portfolio assets compute only `asof_date`s not yet present in their parquet and append. Stats and results recompute fully (cheap).

## Step 10.4 — Full recompute check
- Weekly job `full_recompute`: runs the whole pipeline from `data/raw/` into `data/interim/recompute/` and asserts every processed parquet matches the incremental one to 1e-10 on all numeric columns and exactly on all others. Any difference fails the job and writes the diff summary to `decisions/drift/<date>.md`.

## Step 10.5 — Asset checks
- Dagster asset checks: universe monthly count in [490, 510]; tag coverage above threshold; price conflicts under 1%; validation correlations above thresholds; `results.csv` has the expected row count. A failed check blocks downstream assets.

**Done when** the Dagster UI shows a green run of all assets and the full recompute matches.

---

# Phase 11 — Agents

All agents use one harness. All agents write only to `decisions/` and to pull requests. No agent writes to `data/` or runs `run.py` with modified config.

## Step 11.1 — Harness
- `agents/base.py`:
  - Tools exposed to the model: `read_file(path)` (repo only), `list_dir(path)`, `duckdb_query(sql)` (read-only connection to `data/interim/sec.duckdb` and a read-only view over processed parquets), `run_script(name, args)` (allowlist: `report.py`, `validate.py`, `research_log.py`), `write_decision(agent, filename, content)`, `open_pr(branch, title, body, files: dict[path, content])`, `open_issue(title, body)`, `web_search(query)`.
  - `run_agent(name, system_prompt, user_prompt, tools, max_turns=20) -> dict`: calls the Claude API (model from env `FB_AGENT_MODEL`), loops on tool use, and logs `{agent, timestamp, model, system_prompt_sha, user_prompt, tool_calls, final_output}` to `decisions/<agent>/<timestamp>.json`.
  - Test: a mock tool returns a fixed string, the log file is written with all fields.

## Step 11.2 — Research log agent
- Trigger: after every pipeline run. Prompt: read `specifications.csv`, `git log --oneline -200`, and the current `what_did_not_work.md`; produce an updated version, one line per abandoned specification, factual, no interpretation. Writes to `decisions/research_log/` and opens a PR updating `reports/what_did_not_work.md`.

## Step 11.3 — Reporting agent
- Trigger: pipeline run with all asset checks green. Prompt: run `report.py` via the tool, read `results.csv` and `validation.csv`, write a 200-word `reports/monthly_notes/<YYYY-MM>.md` stating what changed vs the previous month's results (numbers only, no forecasts). Opens a PR. Blocked by the harness if any check failed (harness reads Dagster run status).

## Step 11.4 — Tag map agent
- Trigger: tag coverage check fails, or new tags appear in the latest quarter's `tag.txt` matching a concept's keywords. Prompt: for each under-covered concept, query `num` for the affected CIKs, find which tags they report the concept under, read the `tag` descriptions, propose additions to `tag_map.yaml` with a one-line rationale each. Opens a PR. CI on the PR reruns `coverage_report` and fails if any concept's coverage decreased.

## Step 11.5 — Anomaly triage agent
- Trigger: any asset check failure, or any factor LS monthly return beyond 4 standard deviations of its history. Prompt: read the Dagster failure, relevant manifests, the offending month's cross-section, produce a ranked list of 3 likely causes each with the query used to test it and the result. Writes `decisions/triage/<date>.md` and opens an issue. Does not modify anything.

## Step 11.6 — Universe change agent
- Trigger: universe parser raises. Prompt: read the raw HTML, identify the structural change, propose the parsed change rows for the affected dates, web search for the S&P press release confirming each, cite URLs. Opens a PR with a fixture update and, if needed, a parser patch. The spot-check test must still pass.

## Step 11.7 — Drift agent
- Trigger: full recompute mismatch. Prompt: read `decisions/drift/<date>.md`, bisect by asset in dependency order using read-only queries on both copies, name the first divergent asset and the earliest divergent `asof_date`, hypothesise the cause from the git log since the last green recompute. Writes the finding and opens an issue.

## Step 11.8 — Schedules and CI
- Dagster sensors wire each trigger. GitHub Actions: `test` on every push and PR; `coverage` check on PRs touching `tag_map.yaml`; `spotcheck` on PRs touching `universe.py` or fixtures.

**Done when** each agent has one real logged run in `decisions/` and the README build status shows all phases checked.

---

# Appendix — Definitions Claude Code must not change

- Month end: last calendar day of the month; prices use the last trading day on or before it.
- Signal at t uses data with `date <= t` (prices) or `filed + buffer <= t` (fundamentals).
- Entry at the close of the first trading day after t (lag 1). Exit at the close of the first trading day after the next month end.
- Turnover = 0.5 × Σ|w_t − w_{t−1}^{drift}|, both legs for LS.
- Net return = gross − cost × turnover, cost in decimal.
- Break-even cost = mean(gross) / mean(turnover), in bp.
- IC = Spearman correlation of z at t with return from t to t+1.
- Newey-West lag = holding_months − 1.
- Deciles: D1 lowest signal, D10 highest, LS = D10 − D1.
- Winsorise before z-score, sector-neutral z-score when sectors exist.
