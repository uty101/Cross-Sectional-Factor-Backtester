# FIX_PLAN.md — Data fixes and better data access

Second build spec. `BUILD_PLAN.md` is done; this file fixes what the
2026-09-14 review found and adds the data sources needed to fix the rest.
Same rules as `CLAUDE.md`: one step per session, stop after each, show
the tests, never loosen a threshold to pass a gate. Use the repo's real
names (`backtester` package, `config.toml`, `data/checks/`, `decisions/`,
`uv run`), not the ones in `BUILD_PLAN.md`.

Order matters. Steps F1 to F3 change the fundamentals panel, so nothing
downstream is re-reported until F4. Do not update `README.md` results
until F4 says so.

---

# Part A — API and data source setup (owner does this, not Claude Code)

Register for these before starting Part B. Put every key in `.env`
(already gitignored) and read them with `os.environ`. Never paste a key
into a prompt or a file that is committed.

| Env var | Service | Why | Needed by |
|---|---|---|---|
| `SEC_USER_AGENT` | SEC EDGAR | already in use | all SEC fetches |
| `ANTHROPIC_API_KEY` | Anthropic | agents go live | F9 |
| `GH_TOKEN` + `gh` CLI installed | GitHub | agents open PRs and issues | F9 |
| `TIINGO_API_KEY` | tiingo.com, free tier | second daily price source, some delisted coverage, used for cross-source reconcile | F6 |
| `ALPHAVANTAGE_API_KEY` | alphavantage.co, free | `LISTING_STATUS` endpoint returns every delisted US ticker with its delisting date; used for delisting dates and the terminal-return rule | F6 |
| `NASDAQ_DATA_LINK_API_KEY` | data.nasdaq.com, Sharadar bundle (paid, check current price) | `SEP` daily prices including delisted names, `SF1` point-in-time fundamentals with `datekey` = filing date, `TICKERS` with historical ticker to CIK map. This is the one that removes survivorship bias and replaces the name-match CIK map. Optional but recommended | F7 |
| `FRED_API_KEY` | fred.stlouisfed.org, free | already used for USREC; key raises the rate limit | none new |

Priority if paying for one thing: Sharadar. Priority if paying for
nothing: Tiingo plus Alpha Vantage gets you cross-source reconcile and
real delisting dates, which fixes the terminal-return rule but not the
missing history.

Also install `gh` (GitHub CLI) and run `gh auth login` once so the agents
can open pull requests.

---

# Part B — Fixes

## Step F1 — CIK map audit

**Why.** Total assets coverage is flat at about 82% of members from 2011
to 2024. Every S&P 500 member is a large accelerated filer and was XBRL
from FY2009, so a constant 18% hole is the ticker to CIK map, not the SEC
data.

**Build**
- `scripts/audit_cik_map.py`: for month end 2015-12-31, list every member
  with no `assets` value in the fundamentals panel. For each, record:
  ticker, company name from Wikipedia, CIK the map assigned (or none),
  method used (`company_tickers`, `name_match`, `none`), whether the
  ticker is a removed name, and the best CIK found by querying the SEC
  `sub` table on company name fragments (`name ILIKE '%<first word>%'`).
  Write `data/checks/cik_audit_2015.csv`.
- Repeat for 2011-12-31 and 2022-12-31 into the same file with a `month`
  column.
- Classify each row: `map_wrong` (a CIK with filings exists and was
  missed), `foreign_filer` (20-F or 40-F only), `no_xbrl` (no filings in
  `sub` at all), `other`. Write counts per class to
  `data/checks/cik_audit_summary.csv`.

**Test**
- `tests/test_cik_audit.py`: the script runs on the fixture panel and
  produces the summary with the four classes.

**Done when** the summary exists and `decisions/cik_audit.md` states how
many of the missing members are `map_wrong`. If more than a third are,
proceed to F1b; if not, write why and skip to F2.

## Step F1b — CIK map overrides

**Build**
- `data/checks/cik_overrides.csv`: `ticker, cik, source_url, note`, one
  row per `map_wrong` case from F1, each with an EDGAR URL showing the
  filer. Web search per row; do not guess CIKs.
- `sectors.cik_map`: apply overrides after `company_tickers` and before
  name match. Log the method per ticker in `data/checks/cik_map.csv` as
  now, adding `override` as a method.
- Rebuild the fundamentals panel. Recompute
  `data/checks/fundamentals_coverage.csv`.

**Test**
- `tests/test_cik_overrides.py`: every override row has a CIK with at
  least one row in `sub`; no two tickers share a CIK unless one is a
  share-class alias listed in `ticker_renames.csv`.

**Done when** `assets` coverage is at or above 95% of members for every
month from 2011-01-31. If it isn't, write the residual list to
`decisions/cik_audit.md` with the class per name and stop.

## Step F2 — Shares outstanding from the cover page

**Why.** 145 names are dropped for a market cap under 1bn, including CMG
at a median 297m and DECK at 439m, which are off by about 100x. That is
a units or tag problem. Market cap feeds cap weighting and the
denominators of B/P and E/P, so this touches value directly.

**Build**
- `tag_map.toml`: add concept `shares_cover` with tags
  `[dei:EntityCommonStockSharesOutstanding, EntityCommonStockSharesOutstanding]`.
  This is the cover-page count, reported with its own date
  (`ddate` in `num` is the cover date). Keep the existing balance-sheet
  and weighted-average concepts.
- `fundamentals.shares_outstanding`: priority order `shares_cover`, then
  balance-sheet `CommonStockSharesOutstanding`, then diluted weighted
  average. Record `shares_source` per row.
- `scripts/crosscheck_shares.py`: for every ticker-month with a SEC
  share count, fetch the yfinance `sharesOutstanding` at the latest date
  and compare the SEC count at the latest date to it. Also compare
  `price × shares` to the yfinance market cap. Write
  `data/checks/shares_crosscheck.csv` with `ticker, sec_shares,
  yf_shares, ratio, sec_source, flag` where `flag` is set when the ratio
  is outside [0.5, 2].
- For flagged names, inspect the `num` rows for that CIK and concept
  across all three share tags; if one tag gives a ratio inside the band,
  switch that ticker's source and log it in
  `data/checks/shares_overrides.csv` with the reason. If none does, keep
  the drop and list it.
- Remove the "cap under 1bn dropped" rule from `fundamentals.market_caps`.
  Replace it with: drop only tickers in `shares_overrides.csv` marked
  `unresolved`.

**Test**
- `tests/test_shares.py`: fixture with a cover-page count, a balance-sheet
  count and a weighted average; assert the cover count wins; assert a
  ratio of 100 is flagged.

**Done when** fewer than 20 names are `unresolved`, cap-weighted runs hold
at least 85% of members in every month from 2011, and
`data/checks/market_cap_dropped.csv` is regenerated from the new rule.

## Step F3 — COGS and revenue tag coverage

**Why.** In 2011, 430 members have assets, 296 revenue, 198 COGS. Gross
profitability is computed on roughly half the universe, which is a
selected subsample, and GP/A alone shows a sector-neutral net Sharpe of
-0.42, contradicting the large-cap literature. This is a tag map problem
before it is a data limit.

**Build**
- `scripts/tag_gap.py <concept> <fy>`: for a concept and fiscal year,
  list every member CIK with no value, then query `num` for that CIK's
  10-K in that year and print the 20 most common tags whose name
  contains any of a keyword list (`Cost`, `Revenue`, `Sales`). Write
  `data/checks/tag_gap_<concept>_<fy>.csv`.
- Run it for `cogs` and `revenue` on FY2011, FY2015, FY2020.
- Add tags to `tag_map.toml` for any tag used by 5 or more missing
  filers, in this priority: `cogs`: `CostOfRevenue`,
  `CostOfGoodsAndServicesSold`, `CostOfGoodsSold`,
  `CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization`,
  `CostOfServices`, `CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization`.
  `revenue`: `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`,
  `SalesRevenueNet`, `SalesRevenueGoodsNet`, `RevenueFromContractWithCustomerIncludingAssessedTax`,
  `RevenuesNetOfInterestExpense`, `InterestAndDividendIncomeOperating`
  (banks: revenue = net interest income + noninterest income; add a
  derived rule for financials only, logged).
- Do not add `CostsAndExpenses` to `cogs`; it includes SG&A.
- Financials: exclude sector `financials` from `gross_profitability` by
  rule (Novy-Marx does), and say so in the signal docstring. Keep them
  in accruals.
- Rerun `scripts/check_tag_map.py` (tags only added) and regenerate
  `data/checks/tag_coverage.csv`.

**Test**
- `tests/test_tag_map.py`: every new tag has at least one row in `num`;
  `CostsAndExpenses` is not in `cogs`.

**Done when** `cogs` coverage is at or above 85% of non-financial members
and `revenue` at or above 95% of members for every fiscal year from
2011. Write the before and after coverage by year to
`decisions/tag_coverage_f3.md`.

## Step F4 — Full recompute and re-report

**Build**
- Add a `kind` column to the spec log: `candidate` or `diagnostic`.
  Backfill from the `note` column (anything starting `diagnostic`,
  `sensitivity` or `French replication` is diagnostic). `stats.deflated_sharpe`
  reports two DSRs: `dsr_all` (N = all rows) and `dsr_candidates`
  (N = candidate rows). Results table shows both.
- Run every candidate and sensitivity specification again on the F1 to
  F3 panel. Log each with a note `post-F3`.
- Run `recompute.full`; it must match to 1e-10.
- Regenerate `reports/results.md`, `validation.csv`, charts.
- Update `tests/fixtures/momentum_baseline.json` only if the momentum
  vs UMD correlation moved by more than 0.02, and explain why in the
  commit.
- Paste the new tables into `README.md`. Add one line under the results
  table: "Price history covers X% of member-months; the missing names are
  disproportionately those that left the index. See Data."

**Test**
- `tests/test_regression.py` still passes.
- `tests/test_readme.py` equality between README tables and `results.md`.

**Done when** the README is updated and `decisions/f4_before_after.md`
shows net Sharpe, IC and validation correlation per factor before and
after F1 to F3.

## Step F5 — Beta-hedged low volatility and the BAB validation

**Why.** The low vol long-short has a market beta of -0.65. BAB is
beta-neutral by construction, so comparing a -0.65 beta series to it is
not a like-for-like test.

**Build**
- `portfolio.beta_hedge(ls_returns, mkt_rf, window=36)`: rolling 36-month
  beta of the long-short to Mkt-RF, estimated on months strictly before
  t, and a hedged series `ls - beta_{t-1} × mkt_rf`.
- Register `low_vol_hedged` and `low_beta_hedged` as reported variants
  in the variants table, not new headline rows.
- Validation: add `low_beta_hedged vs bab` with threshold 0.5. Keep the
  raw row.

**Test**
- `tests/test_beta_hedge.py`: a synthetic series that is exactly
  -0.5 × market has a hedged series with beta 0 to 1e-8, and the beta at
  t uses no month at or after t.

**Done when** both rows are in `validation.csv` and the README validation
table.

## Step F6 — Second price source and real delisting dates

**Why.** yfinance stitches reused symbols and has no delisted history.
Stooq is gone. There is currently no cross-source reconcile at all.

**Build**
- `prices.fetch_tiingo(tickers, start, end)`: daily adjusted close and
  volume via the Tiingo REST API, key from `TIINGO_API_KEY`. Respect the
  free-tier rate limit (read it from the response headers, back off).
  Save raw pulls under `data/raw/prices/tiingo_<date>.parquet`.
- `prices.fetch_delistings()`: Alpha Vantage `LISTING_STATUS` with
  `state=delisted`; save `data/raw/delistings_<date>.csv` and
  `data/checks/delistings.csv` filtered to tickers ever in the universe,
  columns `ticker, name, exchange, delisting_date`.
- `prices.reconcile_sources(yf, tiingo, threshold)`: monthly returns from
  both, flag any month where they differ by more than
  `config.toml [prices] conflict_threshold = 0.01`. Write
  `data/checks/price_conflicts.csv`.
- Merge rule: prefer yfinance where both agree; where they conflict,
  prefer Tiingo; where only Tiingo has the name, use it. Record
  `source` per row as now.
- Terminal-return rule (`prices.terminal_returns`): use the Alpha
  Vantage delisting date to decide which names actually delisted vs were
  acquired. Acquired names (delisting reason not bankruptcy, last price
  within 20% of the prior month) get their last actual return; bankrupt
  or unknown get -30%. Log the class per name in
  `data/checks/delisting_terminal.csv`.
- Regenerate `data/checks/price_coverage_*.csv`.

**Test**
- `tests/test_prices.py`: reconcile flags exactly one deliberate 5%
  disagreement; a name present only in Tiingo is kept with
  `source = tiingo`.

**Done when** `gap_pct` in `price_coverage_summary.csv` is reported
before and after in `decisions/f6_price_sources.md`, conflicts are under
1% of ticker-months, and every removed name has a delisting class.

## Step F7 — Sharadar (only if `NASDAQ_DATA_LINK_API_KEY` is set)

**Build**
- `prices.fetch_sharadar_sep(tickers, start, end)`: `SEP` table, includes
  delisted names. Becomes the primary source; yfinance and Tiingo become
  the reconcile.
- `sectors.cik_map_sharadar()`: `TICKERS` table gives `ticker, cik,
  firstpricedate, lastpricedate, isdelisted`. Use it as the primary CIK
  source for removed names, ahead of name match. Log agreement with the
  existing map in `data/checks/cik_map.csv`.
- Do NOT replace SEC fundamentals with `SF1`. Keep the SEC join as the
  point-in-time source. Add one diagnostic run using `SF1` `datekey` as
  a cross-check on the as-of join: for 50 random ticker-months, the
  SEC value and the SF1 value visible at the same date must agree on
  `assets` and `revenue` within 1%. Write
  `data/checks/sf1_crosscheck.csv`.

**Test**
- `tests/test_sharadar.py`: skipped when the key is absent; otherwise
  fetch 2 tickers for one month and assert schema.

**Done when** `gap_pct` is under 3% for every month from 2010 and the
SF1 cross-check has at least 48 of 50 agreeing. Then rerun F4.

## Step F8 — Presentation

**Build**
- Move the 10-K text factor out of the headline results table into a
  `## Appendix: text factor` section in `results.md` and the README.
  Headline table is the 5 factors the brief asked for.
- Add the survivorship line from F4 directly under the headline table.
- Validation table: 6 rows (momentum, B/P replica vs big-cap HML,
  profitability replica vs big-cap RMW, low beta raw, low beta hedged,
  and the composite value and quality rows marked as "not a join test").

**Done when** `tests/test_readme.py` passes on the new layout.

## Step F9 — Agents go live

**Build**
- With `ANTHROPIC_API_KEY` and `gh` set up: run the research-log agent
  once for real. It must produce `decisions/research_log/<timestamp>.json`
  and open a pull request updating `reports/what_did_not_work.md`.
- Review and merge the PR by hand.
- Run the reporting agent once on the current green run; it opens a PR
  with `reports/monthly_notes/2026-09.md`.
- Run the tag-map agent on `cogs` FY2011 as a trigger test; its PR must
  pass the `tag-map` CI job.
- Trigger the triage agent by hand on the January 2010 thin-month case
  (before `min_names` was added, using a config override) and confirm it
  writes a ranked diagnosis without modifying anything.

**Done when** 4 agents each have one real logged run in `decisions/` and
the README build status shows phase 11 complete.

---

# Part C — Definitions that stand (do not change)

- Cost: `r_net = r_gross − 2c × TO`, `TO = ½Σ|Δw|`, `c` one-way. The
  brief's formula is documented as wrong.
- First-filed value wins. No `prevrpt` filter.
- `min_names = 50`; no portfolio in a thinner month.
- Signal at t uses `filed + 1 day <= t` for fundamentals and
  `date <= t` for prices.
- Entry at the close of the first trading day after t.
