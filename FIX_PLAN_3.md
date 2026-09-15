# FIX_PLAN_3.md — Price identity checks, log hygiene, then G6 to G9

Follows `FIX_PLAN_2.md`. Same rules as `CLAUDE.md`, including a
`review/<step>.md` per step from the template. G5 found that yfinance's
`HAR` is not Harman International and that the scan which found it was
heuristic. The steps below turn that into a rule, then continue the
pending G steps unchanged.

---

## Step H1 — Public float cross-check (rule, not diagnostic)

**Why.** Every real bug so far was caught by comparing the pipeline's
number to an external one (French factors, a 2015 close against a 2015
count). The cover page of every 10-K carries `dei:EntityPublicFloat`,
the market value of non-affiliate shares at the end of the second
fiscal quarter. Price × shares at that date must be at least the float
and rarely more than a few times it. This one check catches reused or
misresolved symbols (HAR at $2trn), split-basis errors, and
thousands-versus-units filings in a single pass.

**Build**
- `tag_map.toml`: concept `public_float` with tags
  `[dei:EntityPublicFloat, EntityPublicFloat]`, `qtrs = 0`, keyed on the
  10-K `adsh`; `ddate` is the float date.
- `fundamentals.public_float_check() -> pl.DataFrame`: for every (ticker,
  fiscal year) with a float value, take the month-end close on or before
  the float date and the cover-page share count as of that date, compute
  `cap = close × shares` and `ratio = cap / float`. Columns: `ticker,
  fy, float_date, close, shares, cap, public_float, ratio, flag`.
  `flag` is `low` if ratio < 0.5, `high` if ratio > 20, else blank.
  Thresholds in `config.toml [checks] float_ratio_lo = 0.5,
  float_ratio_hi = 20`.
- Write `data/checks/public_float.csv` and a summary
  `data/checks/public_float_summary.csv` (flags per year, per reason
  where obvious: ratio near a known split factor, near 1000, or off by
  more than 100x).
- Rule: any (ticker, fiscal year) flagged is excluded from every signal
  and every portfolio for the 12 months following the float date. The
  exclusion list is `data/checks/price_identity_exclusions.csv` with
  `ticker, start, end, reason, source_check`. H2 appends to the same
  file.
- Do not exclude on a missing float; only on a bad ratio.

**Test**
- `tests/test_public_float.py`: fixture with 3 ticker-years: one at
  ratio 1.4 (clean), one at 0.0002 (a $2trn cap against a $5bn float,
  the HAR case), one at 1000 (units). Assert the two flags and the
  exclusion windows.

**Done when** `public_float.csv` covers at least 90% of member-years
from 2011, HAR 2013 through 2016 is flagged `high`, CMG 2024 is not
flagged (the split fix holds), and the review file lists every flagged
ticker-year with its 5 rows. Do not rerun the factors yet.

## Step H2 — Symbol identity for removed names

**Why.** HAR's bad series started before Harman delisted, so it is not a
US symbol reuse; yfinance resolved the ticker to a different instrument.
Every removed name fetched by bare ticker has this exposure.

**Build**
- `prices.identity_check(intervals, universe_names) -> pl.DataFrame`:
  for every ticker that ever left the index, fetch yfinance `info`
  (`longName`, `shortName`, `exchange`, `quoteType`, `currency`) once,
  cache to `data/raw/yf_info_<date>.json`, and compare `longName` to the
  Wikipedia company name with token overlap after stripping `Inc`,
  `Corp`, `Co`, `Ltd`, `plc`, `Holdings`, `Group`, `The`. Also record
  the first price date against the membership start, the currency, and
  whether `exchange` is a US exchange.
- Flag when overlap is below 0.5, or currency is not USD, or exchange is
  not NYSE/NASDAQ/NYSE American, or first price date is more than 24
  months after membership start. Write `data/checks/yf_identity.csv`
  with `ticker, wiki_name, yf_name, overlap, exchange, currency,
  first_price, member_start, flag, reason`.
- Append flagged tickers to `price_identity_exclusions.csv` for their
  whole membership interval with `source_check = identity`.
- Names with no `info` at all (delisted, yfinance returns nothing) are
  recorded as `no_info`, not flagged; they are already in the price gap.

**Test**
- `tests/test_identity.py`: fixture rows for a match (overlap 0.8, NYSE,
  USD), a mismatch (overlap 0.0), a non-USD listing; assert flags.

**Done when** every removed name has a row, HAR, EP and COL are flagged,
and the review file lists all flagged names with reason.

## Step H3 — Rerun with exclusions

**Build**
- `run.py` reads `price_identity_exclusions.csv` and drops the listed
  ticker-months before signals are computed. Log the count dropped per
  month to `data/checks/exclusions_applied.csv`.
- Rerun every candidate and sensitivity specification; `kind` stays as
  before; note `post-H2`. Same keys, so N does not move.
- Run `recompute.full`.
- Regenerate `results.md`, validation, charts, README. Update
  `reports/answer.md` if any number in it changed; the test enforces it.

**Done when** `decisions/h3_before_after.md` has every results-table
cell and every validation correlation before and after, and the RMW
replica reads its post-exclusion value in the validation table (0.64
expected).

## Step H4 — Log hygiene

**Build**
- `speclog.log_specification` refuses to append a row whose `spec_key`,
  `git_commit` and `note` all match an existing row, and returns the
  existing row instead. Diagnostic scripts run twice no longer log twice.
- The 3 phase-6 rows whose `sector_neutral` was backfilled from note text
  (2026-09-11 value, quality, low_vol): resolve from
  `git log -p -- src/backtester/run.py` at those commits and set the
  column from the code, not the note. State the answer in the review
  file.
- `results.md` header: N reported as "61 distinct specifications; 8
  candidates. The candidate count is a floor: diagnostic runs informed
  which specifications became candidates." Results table column order:
  `DSR (all)` before `DSR (cand.)`, and the README's prose cites the
  all-trials DSR.

**Test**
- `tests/test_speclog.py`: logging the same key, commit and note twice
  yields one row.

**Done when** tests pass and the 3 rows are resolved.

## Step H5 — Results site (was G7)

Unchanged from `FIX_PLAN_2.md` G7. `DATA.answer` comes from
`reports/answer.md`; `DATA.exclusions` adds one line under the coverage
chart: "<n> ticker-years excluded by the public-float and identity
checks; list in data/checks/price_identity_exclusions.csv".

## Step H6 — G6, second price source (needs the keys)

Unchanged from `FIX_PLAN_2.md` G6, with one addition: H1 and H2 run
against the Tiingo series too, and the review file reports how many of
the yfinance flags Tiingo clears.

## Step H7 — G8 Sharadar, G9 agents

Unchanged.

---

## Definitions that stand

- A trial is a distinct `spec_key`; the same key re-run after a code
  change is the same trial.
- Cost `r_net = r_gross − 2c × TO`. First-filed value wins.
  `min_names = 50`. Share counts in the price series' split basis.
- A ticker-year fails the public-float check when `close × shares /
  EntityPublicFloat` is outside [0.5, 20], and is excluded for the 12
  months after the float date.
