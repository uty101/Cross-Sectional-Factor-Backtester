# Cross-Sectional Factor Backtester

Read this first. The brief is
[Project Outline/01_Factor_Backtester.docx](Project%20Outline/01_Factor_Backtester.docx),
the acceptance criteria are in [README.md](README.md), and the build order
and module contracts are in [PLAN.md](PLAN.md). This file holds what every
session must not violate, and how to run things on this machine.

**Data honesty is the deliverable, not the returns.** A 2.0 Sharpe means
something is leaking. The brief's bar is that value, momentum and quality
long-short series correlate above 0.7 with French HML, UMD and RMW. Momentum
clears it. The reported value and quality factors do not and the bar was
not lowered for them; the join was tested by replicating French's own
construction against his big-cap legs instead ("Validation status" below).
A large unexplained alpha on a plain signal is an error, not a discovery.

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
| 10 | A text score is a deterministic function of documents **filed** on or before *t - asof_buffer_days*. No language model scores a filing: a model trained after the filing knows what happened next, and that leak passes every other test here. | `test_text_signal_is_unchanged_by_a_later_filing`, `test_scorer_has_no_model_and_no_network` |

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
uv run pytest                              # 166 tests, ~8 s
uv run ruff check . && uv run ruff format --check .
uv run backtester fetch --step <universe|prices|benchmarks|fundamentals|shares|text> --as-of YYYY-MM-DD
uv run backtester build --step <same>      # raw -> interim/processed + data/checks
uv run backtester run --factor momentum [--no-sector] [--note "..."]
uv run backtester run-all                  # the five reported factors, base spec
uv run backtester sensitivities            # cw, hold 3/6/12, no-sector: 25 logged runs
uv run backtester delisting                # terminal-return convention, 6 logged runs
uv run backtester report                   # results.md, 4 charts, methodology.pdf
uv run backtester research-log             # reports/what_did_not_work.md from the spec log + git
uv run backtester agent research_log       # needs ANTHROPIC_API_KEY and gh; logs to decisions/
uv run dagster dev                         # assets, checks, schedules (backtester.orchestration)
uv run python -c "from backtester import config, recompute; print(recompute.full(config.load())[1])"  # ~6 min, must match
```

**All phases are built and run** (2026-09-11). The state of the data on
disk: 70 SEC zips (2009q1-2026q2, ~2.5 GB) under `data/raw/sec`, 679
yfinance price files, the French zips, all in `data/raw/manifest.json`.
`data/interim/sec_num.parquet` is the cached ingest (16.6M rows). It is
stamped with a hash of `tag_map.toml` and `INGEST_VERSION`, and
`fundamentals.load_num` re-ingests (about 5 minutes) when either
changes; before 2026-09-15 a stale cache silently came back without the
new tags, and the recompute check caught it. Also on disk since F2:
`data/raw/sec/companyconcept/` (share counts from the SEC API, 2,520
files) and `data/raw/prices/yfinance_splits/` (858 files).

Every backtest appends to `reports/specifications.csv`; 340 rows as of the
last report (144 of them are the September 2026 reruns after the data
fixes and two tie rules the recompute found). **N in the deflated Sharpe
is the number of distinct `spec_key` values** (61, of which 8 candidates;
FIX_PLAN_2 G2, `speclog.py`), not the row count: re-running a
specification after a code fix is the same trial. Each row carries
`config_hash`, `git_commit` (blank for rows logged before 2026-09-14; not
backfilled), `kind` (`candidate` or `diagnostic`, read off the note; the
report shows a deflated Sharpe against each count), `sector_neutral`,
`variant` and `spec_key` (backfilled from the note for older rows). **Do not delete rows from it**,
including the diagnostic runs and the two broken first momentum attempts;
the deflated Sharpe reads it.

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
  sources.py             Tiingo second source, Alpha Vantage delistings, reconcile/merge (F6; needs keys in .env)
  benchmarks.py          French factors + big-cap HML/RMW legs, FRED
  fundamentals.py        SEC FSDS via DuckDB, first_filed, asof_join, caps
  tag_map.toml           19 concepts, ordered XBRL tags (only ever added to)
  identity.py            price-identity exclusion list (FIX_PLAN_3 H1/H2); run.py applies it
  sectors.py             CIK matching by name, SIC -> 11 buckets
  text.py                10-K primary documents from EDGAR, year-on-year similarity
  agents/                base.run_agent harness; tools.Toolbox with the allowlists in code
  orchestration/         Dagster definitions: one asset per table, checks on data/checks, schedules
  research_log.py        what_did_not_work.md: superseded/abandoned spec rows + the commit after each
  signals.py             signals, winsorise, sector z, composite
  portfolio.py           the engine; any (month, ticker, z); spec log
  stats.py               IC, decay, FM/NW, DSR, attribution, break-even
  run.py                 FACTORS registry, run_factor, run_all, sensitivities, replicate
  report.py              tables + 4 charts -> reports/results.md
  methodology.py         the 2-page PDF from the same numbers
  cli.py
decisions/               agent run logs and decision records; BUILD_PLAN.md is the spec
tests/                   one file per module; invariants named in test names
data/raw|interim|processed   gitignored except raw/manifest.json
data/checks/             committed evidence; README.md there lists every file
reports/                 figures, results.md, methodology.pdf, specifications.csv
```

### Things a future session should know

- **Validation status** (after FIX_PLAN F1-F4, 2026-09-15). Momentum vs
  UMD 0.78 (pass). Value and quality as reported are sector-neutral
  composites and score 0.56 / 0.07 vs HML / RMW (value was 0.25 before
  the market-cap fix); the join is validated by `run.replicate`: B/P
  cap-weighted terciles vs the big-cap HML leg 0.78 (0.90 from 2016),
  0.72 vs full HML. The RMW replication is 0.62 vs the big-cap leg (0.44
  vs full RMW); its early-years weakness was the CIK map, not XBRL
  coverage (2010-12 went from 0.07 to 0.69), and a 2013-15 trough of
  0.38 is not understood. `reports/validation.csv` judges the two
  replications against the big-cap legs (bar 0.6) and the reported
  factors against the full factors (bar 0.7); the text factor is an
  appendix, not a headline row (F8). Do not tune the reported factors to raise
  these numbers.
- **Value's old net Sharpe of 0.48 was a market-cap bug**, not a premium:
  split-adjusted prices met unadjusted share counts, so pre-split
  winners (CMG, DECK, SMCI) sat in the value long leg with a B/P 6-50x
  too large. After F2 value is -0.16 net and loads 0.42 on HML.
  `decisions/f4_before_after.md` has every factor before and after.
- **Cost convention** differs from the brief on purpose: every dollar
  traded pays c, `ret_net = ret_gross - 2c * turnover`.
- **The full recompute must match to 1e-10 before a report is trusted.**
  `recompute.full` rebuilds everything under `data/recompute/` (raw via a
  junction, hand-written checks copied in, spec rows to its own log) and
  compares. Both nondeterminism sources found on 2026-09-14 are fixed
  (override rows as inputs; the `latest_flow` quarter-wins rule); a new
  one is a bug, and the drift agent's job.
- **A month thinner than `min_names` (50) forms no portfolio.** January
  2010 had 15–23 names with fundamentals; the text factor's first four
  months had 2–5. Their "returns" were single stocks. Found by the 4σ
  detector in `agents/triage.py` on 2026-09-14.
- **Spec-log row 94 is mislabelled** ("sensitivity jaccard", actually
  cosine); row 131 is the correction and its note miscounts the row. Do
  not edit either; the README explains it.
- **Series stamping.** Long-short rows carry the *formation* month; anything
  compared with a French factor is shifted one month first
  (`stats.to_month_earned`, `run.validate`). Getting this wrong was the
  0.04-correlation bug.
- **Wikipedia's CIK can be a brand-new entity** (XOM); `sectors.cik_map`
  falls back to the name when a CIK has no filings. **A ticker can have
  more than one CIK over time** (Disney 2019, JCI and CB 2016):
  `data/checks/cik_overrides.csv` holds the eras and `sectors.cik_at`
  resolves one per month. See `decisions/cik_audit.md`.
- **yfinance's Close is split-adjusted; SEC share counts are not.** A
  count is multiplied by every split after its filing date
  (`shares.split_factor`, `data/interim/splits.parquet`) before it meets
  a price; without that Chipotle's cap was 50 times too small before
  2024, which is what the old $1bn floor was catching. The count is the
  cover-page `dei:EntityCommonStockSharesOutstanding` from the SEC
  companyconcept API (FSDS num.txt does not carry it), then the
  balance-sheet count, then the diluted weighted average
  (`shares.select`). Nothing is dropped by size any more;
  `market_cap_dropped.csv` lists what still comes out under $1bn.
- **A price is checked against the filer's own market value** (FIX_PLAN_3
  H1). Every 10-K cover carries `dei:EntityPublicFloat`; the pipeline's
  cap at the float date over it is in [0.5, 20] for 8,453 of 8,515
  ticker-years, and the 62 outside are `data/checks/public_float.csv`
  (`flag`, `reason`). A flag is excluded for 12 months
  (`price_identity_exclusions.csv`) unless the reason is `float_scale`:
  the filer's own float in thousands or billions (GE 2011, eBay 2019),
  49 of the 62, where the pipeline is right. Like the cover share count,
  the float comes from the companyconcept API, not the FSDS. Exelon's
  XBRL float is twice its cover text for four years and is excluded by
  the rule; `review/h1.md` has every flagged row.
- **Text comes from EDGAR, never from company websites.** The 10-K
  primary documents live under `data/raw/edgar/10k/<cik>/<adsh>.htm.gz`,
  one per original filing, indexed from `sub.txt` in the FSDS zips so the
  filing date is the SEC's. Websites have no filing timestamp, overwrite
  restated numbers in place, and vanish for delisted names. Earnings-call
  transcripts are not filed and are not used; the 8-K earnings release
  (Exhibit 99.1) is the next text source to add, not a transcript vendor.
  The scorer is cosine/Jaccard between consecutive 10-Ks ("Lazy Prices");
  `config.toml [text] similarity` accepts only those two, by design.

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
- API keys come from the environment or a gitignored `.env` at the repo
  root (`config.secret`). FIX_PLAN F6 (Tiingo, Alpha Vantage), F7
  (Sharadar) and F9 (Anthropic, gh) are built or pending against keys
  that are not on this machine; each fetch says so and skips.
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
- **`data/recompute/raw` is a directory junction into the 5 GB raw
  store.** It is gitignored; on 2026-09-14, for the minutes before that
  line existed, one `git add -A` walked it and wrote 13,500 unreachable
  blobs into `.git` (repacked away with `git repack -a -d`). Never `git
  add -A` here; name the paths. If `.git` is ever gigabytes, that is why.
