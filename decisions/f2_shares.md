# Shares outstanding and market cap (FIX_PLAN F2)

**Date:** 2026-09-15. **Code:** `src/backtester/shares.py`,
`fundamentals.market_caps`. **Evidence:** `data/checks/shares_crosscheck.csv`,
`data/checks/shares_overrides.csv` (hand-written),
`data/checks/market_cap_dropped.csv`. **Tests:** `tests/test_shares.py`.

## The diagnosis in the plan was wrong, and the fix is different

F2 was written on the reading that Chipotle's median cap of 297m and
Deckers' 439m were "off by about 100x", a units or tag problem, to be
fixed by taking the cover-page share count. The counts were right.
CMG's cover page in 2015 says 31.1m shares; the yfinance close for
2015-12-31 is 9.597. The real close that day was 479.85: **yfinance's
`Close` is split-adjusted** (only dividends are left in), and Chipotle
split 50-for-1 in June 2024. Every pre-2024 cap was 50 times too small
because a 2015 count met a price in 2026 share-basis. Deckers (6-for-1,
2024), Super Micro (10-for-1, 2024), CoStar, Copart, Bio-Techne, Enphase
and the rest of the 145 names the 1bn floor caught are the same story.

The plan's own cross-check would not have found this: it compares the
SEC count with yfinance's *current* count, and both are in today's
basis. The cross-check passes for CMG before and after the fix.

So F2 does three things instead of one:

1. **Splits.** `shares.fetch_splits` pulls each ticker's split events
   from yfinance (`data/raw/prices/yfinance_splits/`, 1,814 events for
   456 tickers, 319 since 2010 across 221 tickers). A count is
   multiplied by every split dated after its **filing** date (a filing
   made after a split already reports post-split numbers, ASC 260) and
   on or before the price series' own as-of date. `shares.split_factor`.
2. **The cover-page count, from a different source.** The plan asks for
   a `shares_cover` concept in `tag_map.toml`. The Financial Statement
   Data Sets do not carry it: 10 of 6,877 filings in 2015q3 have
   `EntityCommonStockSharesOutstanding` in `num.txt`, so the tag-map
   route returns nothing and `tag_map.toml` is unchanged. The count
   comes from the SEC's companyconcept API instead
   (`data/raw/sec/companyconcept/<cik>_EntityCommonStockSharesOutstanding_*.json`,
   840 CIKs, 39,670 facts for 764 of them), each fact with its accession
   number and filing date, so it joins as-of like every other concept.
   The same API supplies `CommonStockSharesOutstanding` and
   `WeightedAverageNumberOfDilutedSharesOutstanding` for the filers the
   FSDS is missing them for (General Dynamics has 664 USD rows in
   2020q3 and not one share count; Comcast's cover total stops in 2012).
   Priority is cover, then balance sheet, then diluted weighted average,
   as the plan says; `shares_source` is recorded per row.
3. **A plausibility guard instead of a size floor.** The 1bn rule is
   gone. What replaces it is not "drop only `unresolved` tickers" alone,
   because the errors that remain are per filing, not per ticker:
   Garmin's XBRL reports both the balance-sheet and the weighted-average
   count in thousands in some filings and in units in others (191,815
   against 192,239,000 in FY2015); Coca-Cola's weighted average is in
   millions for four quarters of 2012; TechnipFMC's and Baker Hughes'
   first filings as new registrants carry the merger shell's 1 and 100
   shares. `shares.resolve` puts every source in the price basis, takes
   the ticker's rolling 61-month median across sources as the
   reference, and uses the highest-priority source within a factor of 5
   of it. The reference is computed only from counts whose implied cap
   lies between 200m and 20tn: EchoStar reports its weighted average in
   thousands in every 10-Q and in units in every 10-K, so the wrong
   values are the majority of any window, and AEP's count is a million
   times too large for nine months of one year; without the prior the
   median follows the error (EchoStar) or a high quantile does (AEP).
   A source outside the band is still used if a second source agrees
   with it within 25% **and** it is within a factor of 50 of the
   reference: that keeps AIG's 2011 recapitalisation (135m to 1.8bn in a
   quarter, cover page and weighted average agreeing) and still rejects
   two sources that are both in thousands and a merger shell whose cover
   page and balance sheet both say 1 share. A count under 100,000 is a
   shell. A month with no plausible source has no cap and is logged.

## Cross-check

`scripts/crosscheck_shares.py`, every current member (497): the SEC
count in the price basis against yfinance's `fast_info` count, and
price x shares against yfinance's market cap. Cap ratio median 1.02,
5th to 95th percentile 0.94 to 1.11. Two names came out outside
[0.5, 2] (one remains in the file; the other is now dropped before the
check):

| ticker | ratio | what it is | decision |
|---|---|---|---|
| BRK.B | 0.0008 | every SEC count is class-A equivalents (1.6m) against a class-B price; per-class cover counts are dimensional facts the API omits | `unresolved`, dropped |
| VMRK | 0.48 | Equity Residential renamed in 2026; cover page, balance sheet and weighted average all say 375m; no filing supports yfinance's 774m | kept on the SEC count, pinned to `cover` |

Three more rows in `shares_overrides.csv` are not share-count problems
at all and are marked `unresolved` so their caps do not reach a
weighting or a B/P: **COL, GR and EP** have a median member-month cap of
9m, 388m and 42m because yfinance's history under those symbols is
another company's (COL closes at 0.50 in 2013-16 while Rockwell Collins
traded at 60-140; GR at 4 in 2010 while Goodrich was above 70). Their
returns are wrong for the same reason. That is a price-source defect
for F6 to fix with a second source; the rows say so and come out when
it does.

## Coverage

Members with a market cap, before and after, against members and
against members with a month-end price (the only ones a cap-weighted
run can hold; the rest is the price gap, F6/F7):

| December | members | priced | cap before | cap after | after / priced |
|---|---|---|---|---|---|
| 2011 | 498 | 358 | 280 | 348 | 97.2% |
| 2015 | 503 | 405 | 331 | 394 | 97.3% |
| 2020 | 504 | 459 | 394 | 450 | 98.0% |
| 2024 | 503 | 491 | 426 | 483 | 98.4% |

Over every month from 2011-01, the cap covers at least **96.8%** of
priced members (worst month 2019-04, median 98.1%). Against all members
the floor is 68.5% (January 2011), which is the price gap: F2's bar of "85% of
members in every month from 2011" is not met and cannot be met by any
share-count change while 28% of 2011 members have no yfinance history.

The 8 to 12 priced members without a cap in a given month are the
share-class filers whose counts exist only per class as dimensional
facts (V, UPS, LEN, HSY, STZ, SPG, HUM, MDLZ, JCI, BRK.B, BG) plus
Google before the 2015 reorganisation. Summing the per-class segment
rows in `num.txt` would recover most of them; that is an ingest change
(the ingest keeps unsegmented rows only) and is left for a later step.
Fewer than 20 names are unresolved, which is the plan's bar.

Source of the count used, all months: cover 96,383 rows, weighted
average 7,918, balance sheet 6,009. Member-months dropped by the guard:
107 over 21 tickers (`market_cap_dropped.csv`, reason "count out of
line with neighbours"), every one with an implied cap in the thousands
or the quadrillions: Garmin (24), Baker Hughes' 100-share shell (18),
Coca-Cola (12). Member-months still under 1bn and kept: Smith
International's last six months of 2010 (cap 0.8-1.0bn on a 249m
count; genuinely small) and nothing else.

Share counts are now carried for up to 18 months instead of 9: a few
filers reach the panel only through the balance-sheet count of their
10-K (General Dynamics, PPG, Humana), and the next 10-K is due within
12 months. A quarterly filer's count is refreshed long before that.

Nothing downstream is re-reported until F4.
