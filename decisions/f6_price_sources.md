# A second price source and real delisting dates (FIX_PLAN F6)

**Date:** 2026-09-15. **Status: built, not run.** Both fetches need a key
from Part A of the plan and there is no `.env` on this machine:
`TIINGO_API_KEY` and `ALPHAVANTAGE_API_KEY` are unset, so
`sources.fetch_tiingo` and `sources.fetch_delistings` print that they
skipped and the pipeline runs on yfinance alone, exactly as before.

## What is built

`src/backtester/sources.py`, wired into `prices.fetch`, `prices.build`
and the delisting sensitivity; `tests/test_sources.py` (4 tests, no
network).

- `fetch_tiingo(cfg, as_of)`: daily adjusted closes per universe ticker
  from the Tiingo REST API, `format=csv`, one parquet per fetch date
  under `data/raw/prices/tiingo_<as_of>.parquet` (never overwritten,
  in the manifest). Backs off on a 429 by `Retry-After` and pauses when
  `X-RateLimit-Remaining` drops under 5. A 404 is a symbol Tiingo does
  not have.
- `fetch_delistings(cfg, as_of)`: Alpha Vantage `LISTING_STATUS`
  `state=delisted` to `data/raw/delistings_<as_of>.csv`; the universe's
  rows to `data/checks/delistings.csv` (ticker, name, exchange,
  delisting_date; Yahoo's dash for a share class becomes the dot).
- `reconcile(yf, tiingo, threshold)`: calendar-month returns from each
  source's last adjusted close; a month where they differ by more than
  `config.toml [prices] conflict_threshold` (0.01) is a conflict.
  `data/checks/price_conflicts.csv` holds them (empty now).
- `merge`: yfinance rows where the two agree or where Tiingo has
  nothing; Tiingo rows for a conflicting month and for a name only
  Tiingo has. `prices_daily.parquet` now carries `source` on every row
  (all `yfinance` today). `price_coverage_summary.csv` gains
  `tickers_from_tiingo`, `conflict_months`,
  `conflict_pct_of_ticker_months` (0, 0, 0.0).
- `classify_removed`: every removed name whose last print is within 45
  days of removal is `acquired` (a delisting date on record and the last
  close within 20% of the prior month-end), `failed` (a delisting date
  and a larger fall) or `unknown` (no record). `prices.terminal_returns`
  gives an acquired name 0 in place of the -30% shock (its last actual
  return is already earned) and the others the shock;
  `data/checks/delisting_terminal.csv` carries the class per name. With
  no delisting list every one of the nine names is `unknown`, and the
  terminal sensitivity is unchanged (the six rows logged on 2026-09-15
  with note `sensitivity terminal` confirm it).

Alpha Vantage's list has no delisting *reason*; "bankrupt or unknown"
in the plan is read as "no record, or a record with a price collapse".

Keys are read by `config.secret(name)`: the environment first, then a
`.env` at the repo root (gitignored). Nothing is committed with a key.

## What the numbers say, before

`gap_pct` in `price_coverage_summary.csv` is **14.64%** of universe-months
(31% in 2010 falling to 0%); 631 of 858 universe tickers have a yfinance
history; COL, GR and EP have a history that is another company's
(`decisions/f2_shares.md`). The "after" column is written when the keys
exist and the fetch has run:

| metric | before | after |
|---|---|---|
| gap_pct | 14.64 | (needs TIINGO_API_KEY) |
| tickers_with_prices | 631 | |
| tickers_from_tiingo | 0 | |
| conflict_pct_of_ticker_months | 0.0 | |
| removed names with a delisting class other than unknown | 0 of 9 | (needs ALPHAVANTAGE_API_KEY) |

## To finish F6

1. Put the two keys in `.env`.
2. `uv run backtester fetch --step prices --as-of <today>` (the yfinance
   files for the day are skipped if present; Tiingo pulls 858 tickers,
   which is under the free tier's daily allowance of 500 unique symbols
   only over two days: the fetch is resumable per parquet, not per
   ticker, so expect to run it on two dates).
3. `uv run backtester build --step prices`, then `rerun --note " post-F6"`,
   `report`, and `recompute.full`.
4. Fill the table above; the F2 override rows for COL, GR and EP come out
   if Tiingo's history for them is Rockwell Collins', Goodrich's and El
   Paso's.
