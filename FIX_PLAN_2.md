# FIX_PLAN_2.md — Trial count, reporting, the site, and unblocking F6 to F9

Follows `FIX_PLAN.md`. Same rules as `CLAUDE.md`. One step per session,
stop after each, show the tests. Part A is for the owner and takes about
30 minutes; Part B is for Claude Code and does not need Part A until G6.

---

# Part A — Owner: get the keys and prove they load (30 minutes)

Do these in order. Nothing in Part B after G5 runs until `uv run
backtester secrets` prints every line as `set`.

**A1. Create the `.env` file.** In the repo root:
```
touch .env
```
It is already gitignored. Confirm with `git check-ignore .env`, which
must print `.env`.

**A2. Tiingo (free).** Go to tiingo.com, sign up, open Account then API,
copy the token. Add to `.env`:
```
TIINGO_API_KEY=...
```
Free tier limits: about 50 unique symbols per hour and 1,000 requests a
day at the time of writing. F6's fetcher backs off on the headers, so a
full first pull of 850 tickers takes most of a day; leave it running.

**A3. Alpha Vantage (free).** Go to alphavantage.co, click Get Free API
Key, fill the form, copy the key.
```
ALPHAVANTAGE_API_KEY=...
```
Only one endpoint is used (`LISTING_STATUS`), one call, so the 25-a-day
free limit is irrelevant.

**A4. Anthropic.** console.anthropic.com, API Keys, create one, add a
small prepaid balance (10 to 20 USD covers every agent run in the plan).
```
ANTHROPIC_API_KEY=...
FB_AGENT_MODEL=claude-sonnet-4-6
```

**A5. GitHub CLI.** Install `gh` (`brew install gh` on a Mac, `winget
install GitHub.cli` on Windows). Then `gh auth login`, choose GitHub.com,
HTTPS, authenticate with browser. Check with `gh auth status`. No token
goes in `.env`; `gh` stores its own.

**A6. Sharadar (optional, paid).** data.nasdaq.com, search "Sharadar
Core US Equities Bundle", subscribe, then Account Settings, API key.
```
NASDAQ_DATA_LINK_API_KEY=...
```
Check the current monthly price before deciding. This is the only source
in the plan that carries the price history of names that left the
index. If you skip it, survivorship stays and the caveat under the
results table stays with it.

**A7. Verify.** After G1 lands, run:
```
uv run backtester secrets
```
It prints one line per key, `set` or `missing`, without printing values.

---

# Part B — Claude Code

## Step G1 — `secrets` command

**Build**
- `cli.py`: `backtester secrets` prints each key name in
  `config.SECRET_NAMES` (`SEC_USER_AGENT, TIINGO_API_KEY,
  ALPHAVANTAGE_API_KEY, ANTHROPIC_API_KEY, FB_AGENT_MODEL,
  NASDAQ_DATA_LINK_API_KEY`) with `set` or `missing`, and whether `gh
  auth status` succeeds. Never prints a value or a prefix of one.
- `config.secret(name)` already reads env then `.env`; add
  `config.require(name)` that raises with the Part A step number in the
  message when missing.

**Test**
- `tests/test_secrets.py`: with a tmp `.env` containing `X=1`, `secret("X")`
  returns `1`; `require("Y")` raises with "Part A" in the message; the
  `secrets` command output contains no `=` characters.

**Done when** `uv run backtester secrets` runs and shows the current state.

## Step G2 — Trial count for the deflated Sharpe

**Why.** The spec log has 335 rows but 12 distinct config hashes and 3
distinct candidate hashes, because `config_hash` hashes the global
config. Three recomputes after bug fixes added 48 rows each and were
counted as 144 new trials. Re-running the same specification after a
code fix is not a new trial.

**Build**
- `speclog.spec_key(row)`: sha256 of the tuple `(factor, signal,
  weighting, cost_bps, lag_days, rebalance, holding_months, winsor_lo,
  winsor_hi, n_deciles, sector_neutral, start, end)`. Add a `spec_key`
  column; backfill every existing row.
- `speclog.count_trials(kind=None)`: number of distinct `spec_key`
  values, optionally filtered to `kind == candidate`.
- `stats.deflated_sharpe`: `n_trials` from `count_trials`. The variance
  of Sharpe across trials is computed over one row per `spec_key` (the
  latest), not over all rows.
- `results.md` header reports `N = <distinct> distinct specifications
  (<rows> runs logged), <candidates> candidates`. Keep both DSR columns.

**Test**
- `tests/test_speclog.py`: 5 rows, 2 distinct spec keys, 1 candidate key;
  `count_trials()` is 2 and `count_trials("candidate")` is 1; the same
  spec logged twice with different `git_commit` counts once.

**Done when** the results table is regenerated and
`decisions/g2_trial_count.md` shows every DSR before and after.

## Step G3 — Caveats next to the numbers

**Build**
- Results table: add a `Coverage` column with the share of members the
  signal is computed on in a typical month (`fundamentals_coverage.csv`
  for fundamentals signals, price coverage for price signals). Quality's
  cell reads like `67% of non-fin.` and footnotes the COGS reason in one
  line under the table.
- IC decay table: `Half-life` is `n/a` when the h=1 IC t-stat is below
  1.96 in absolute value. The chart omits the fitted curve in that case.
- Attribution table: add the `Coverage` footnote reference to Quality.

**Test**
- `tests/test_readme.py`: results table has the `Coverage` column and
  the quality footnote; no half-life is printed for a factor whose IC
  t-stat is under 1.96.

**Done when** `results.md` and README match and tests pass.

## Step G4 — The answer paragraph

**Build**
- Rewrite the README's "The question" and the first paragraph of
  "Results" to what the tables now show. Constraints: at most 120 words,
  every number in it appears in a table on the page, no adjectives. It
  must say three things: what survived (nothing at 10 bp once DSR is
  applied; quality is the closest), what the biggest correction was (the
  split-basis market cap that made value look like it earned 4.7% alpha),
  and what the data cannot say (the missing 14.6% of member-months are
  disproportionately names that left the index).
- Write the same 120 words into `reports/answer.md`; the site (G7) reads
  it from there.

**Done when** `tests/test_readme.py` checks every number in `answer.md`
against `results.md`.

## Step G5 — RMW replica 2013 to 2015

**Why.** The replication against French's big-cap RMW leg is 0.69, 0.38,
0.83, 0.62, 0.61 by 3-year block. The trough is the one open thread in
the join tests.

**Build**
- `scripts/rmw_trough.py`: for 2013-01 to 2015-12, month by month,
  compute the replica's tercile membership and compare the top and
  bottom tercile lists to a naive operating-profitability sort built
  from `net_income_ttm + interest_expense + tax` where available. Report
  the 20 names with the largest rank disagreement, their sector, and
  which concept (`pretax_income`, `equity`, `shares`) drives it. Also
  report the replica's correlation with big-cap RMW when Financials are
  excluded, and when `equity` uses the average of the last two fiscal
  years instead of one.
- Write `decisions/g5_rmw_trough.md` with the finding, or with "not
  found" and the three things ruled out.

**Done when** the decision file exists. No result may be changed on the
strength of it without a new candidate row and a note.

## Step G6 — Run F6 for real (needs A2, A3)

**Build**
- `uv run backtester secrets` must show Tiingo and Alpha Vantage set.
- Run `prices.fetch` with Tiingo enabled. Expect a long first run; the
  manifest records progress per ticker so a second run resumes.
- Run `fetch_delistings`, then `prices.build`, then the terminal
  sensitivity.
- Update `decisions/f6_price_sources.md` from "built, not run" to the
  measured numbers: tickers from Tiingo only, conflict months, gap_pct
  before and after, delisting classes per removed name.

**Done when** `price_coverage_summary.csv` has a non-zero
`tickers_from_tiingo`, `price_conflicts.csv` is populated, every removed
name has a class other than `unknown` where Alpha Vantage lists it, and
the results table is regenerated with the survivorship line updated to
the new gap_pct.

## Step G7 — Results site (FIX_PLAN F10)

**Build**
- `report/site_template.html` from the file supplied on 2026-09-15.
- `report.site()`: builds the `DATA` object from `results.csv`,
  `validation.csv`, `data/checks/price_coverage_monthly.csv`,
  `reports/answer.md`, the first 5 lines of `what_did_not_work.md`, and
  the run history from candidate rows in `specifications.csv` (one point
  per distinct `spec_key`, latest run, for the value and quality base
  specs). Writes `docs/index.html` with the two chart PNGs embedded as
  base64 JPEG at width 1000. Copies `methodology.pdf` and `results.md`
  into `docs/`.
- Dagster asset `site`, downstream of `figures` and `validation`,
  blocked when any check failed.
- `.github/workflows/pages.yml`: deploy `docs/` to GitHub Pages on push
  to `main`. Owner enables Pages once in repo Settings, source "GitHub
  Actions".
- README: the Pages URL in the status line at the top.

**Test**
- `tests/test_site.py`: every factor in `results.csv` is in `DATA.factors`;
  no `__IMG_` placeholder remains; every number in `answer.md` appears in
  `DATA`; the file is under 400 KB.

**Done when** the Pages URL shows the current numbers and changing
`cost_bp_base` in `config.toml` and rerunning changes the page with no
manual edit.

## Step G8 — Sharadar (needs A6; skip if the key is absent)

As FIX_PLAN F7, unchanged. Then rerun G6's build and G7.

## Step G9 — Agents live (needs A4, A5)

As FIX_PLAN F9, unchanged. First run is the research-log agent; it must
regenerate `what_did_not_work.md` from the current log (it still says
185 specifications) and open the PR.

---

# Part C — Definitions that stand

- A trial is a distinct `spec_key`. Re-running one after a code change
  is the same trial.
- Cost `r_net = r_gross − 2c × TO`. First-filed value wins. `min_names = 50`.
- Signal at t uses `filed + 1 day <= t` for fundamentals, `date <= t`
  for prices, and share counts in the price series' split basis.
