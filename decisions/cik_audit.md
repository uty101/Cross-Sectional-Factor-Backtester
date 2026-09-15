# CIK map audit (FIX_PLAN F1)

**Date:** 2026-09-15. **Script:** `scripts/audit_cik_map.py`.
**Evidence:** `data/checks/cik_audit_2015.csv` (all three months, `month`
column), `data/checks/cik_audit_summary.csv`.

## Question

Total assets coverage has sat at 87-91% of members from 2011 to 2015
(`fundamentals_coverage.csv`: 436/498 at 2011-12, 458/503 at 2015-12,
489/502 at 2022-12). Every S&P 500 member is a large accelerated filer
and was on XBRL from FY2009, so the hole is the ticker-to-CIK map unless
the audit says otherwise.

## Method

For each of 2011-12-31, 2015-12-31 and 2022-12-31, every member with no
`assets` in `fundamentals_monthly.parquet` was looked up in the full
filer index, `data/interim/sec_sub.parquet` (new: `fundamentals.ingest_sub`,
every form in every FSDS zip, 433,717 filings). The search takes the
first word of the Wikipedia name (first two when the first is generic:
AMERICAN, GENERAL, ...), finds filers whose SEC name contains it as a
word and filed anything in the 18 months to the month-end, and keeps
the one sharing the longest leading run of words, ties to the busier
filer. Classes:

| class | rule |
|---|---|
| `map_wrong` | the assigned CIK has no 10-K/10-Q in the window, and a name-matched filer with 10-K/10-Q filings does exist |
| `foreign_filer` | the name-matched filer has 20-F/40-F filings only |
| `no_xbrl` | no filer matches the name at all |
| `other` | the assigned CIK does file 10-K/10-Q in the window and still has no assets value |

## Result

| month | members missing assets | map_wrong | foreign_filer | no_xbrl | other |
|---|---|---|---|---|---|
| 2011-12-31 | 62 | 47 | 0 | 12 | 3 |
| 2015-12-31 | 45 | 36 | 0 | 7 | 2 |
| 2022-12-31 | 13 | 12 | 0 | 1 | 0 |
| all | 120 | 95 (79%) | 0 | 20 | 5 |

**95 of 120 (79%) are `map_wrong`**, far more than the one-third bar in
FIX_PLAN F1, so F1b (overrides) proceeds.

Reading the rows, the 95 split into two mechanisms:

1. **Removed names the name matcher could not place (unmatched):** AA,
   ACE, AET, AGN, BBBY, BHI, BRCM, CCE, CNX, ESRX, HOT, IPG, KFT, LSI,
   LXK, MHK, OI, PRGO, TYC, VNO, XRX, ... The filer is there under its
   SEC name (`ALCOA INC`, `AETNA INC /PA/`, `XEROX CORP`); the exact and
   prefix matchers refused because the normalised name collides with a
   second CIK (Alcoa Inc, later Arconic, and the 2016 Alcoa Corp spin-off
   both normalise to `ALCOA`) or the SEC spelling has a suffix the
   normaliser does not strip (`/PA/`, `/DE/`, `CORP/NW`).
2. **Current names whose `company_tickers.json` CIK is a successor
   entity with no filings in the period:** BLK (BlackRock Inc 1364742
   until the 2024 reorganisation, 2012383 after), CI (Cigna Corp 701221
   until 2018, Cigna Group 1739940 after), DIS (1001039 until 2019,
   1744489 after), DOW, DD, DELL, ETN, MDT, SNDK, CEG, FOXA. The SEC map
   is a snapshot of today's symbols and today's registrant; the earlier
   registrant filed the earlier 10-Ks under its own CIK. One CIK per
   ticker cannot express this: the map needs a CIK per era.

The 20 `no_xbrl` rows are not all genuinely unfiled. Where the Wikipedia
name is the successor's (APA Corporation for Apache, TechnipFMC for FMC
Technologies, Linde plc for Praxair, L3 Technologies for L-3
Communications, TSYS for Total System Services, Viatris for Mylan,
Walgreens Boots Alliance for Walgreen Co, Alphabet for Google, CR Bard
for `BARD C R INC`) the first-word search cannot see the predecessor,
and those are `map_wrong` in substance: F1b overrides them from the
filer index by hand. Two are real: WPX Energy at 2011-12 (spun off on
2011-12-31, first 10-K in 2012) and First Republic Bank (filed with the
FDIC, never on EDGAR).

The 5 `other` rows are not map problems and F1b leaves them: Honeywell
tagged total assets `AssetsNet` in FY2010-2011; Legg Mason, Plum Creek
and Host Hotels report every balance-sheet line with a `LegalEntity`
segment and no unsegmented consolidated row, which the ingest's
`segments = ''` filter drops. Both are tag-map or ingest questions for
F3, logged there.

## Decision

Proceed to F1b: `data/checks/cik_overrides.csv` with one row per
(ticker, CIK) the audit and the filer index establish, allowing more
than one CIK per ticker so a successor registrant does not erase its
predecessor's filings.

---

# F1b: the overrides, and the result

**Date:** 2026-09-15. **File:** `data/checks/cik_overrides.csv`, 93 rows
over 82 tickers, 44 of them date-ranged. **Test:** `tests/test_cik_overrides.py`.

## What changed in the map

`sectors.cik_map` takes the override rows after the SEC map and the
constituents table and before the name match; a ticker with an override
is never name-matched. The map is now `Frame[ticker, cik, start, end]`
and `sectors.cik_at` resolves the registrant per month: an override's
range beats the base map inside the range, the base map applies
outside, and two ranges for one ticker never overlap (the function
raises). `fundamentals.monthly_panel` and `text.signal` both go through
it, so Disney reads CIK 1001039's filings to 2019-03 and 1744489's after,
with no month reading both.

Every CIK was verified against the SEC's own filer index
(`data/interim/sec_sub.parquet`): the SEC name on the filings, the form
types and the first and last 10-K/10-Q filing dates were checked
against the membership interval before a row was written, and the
`source_url` is the EDGAR filing list for that CIK. Nothing was taken
from a web search alone.

Two cases the F1 audit did not flag but the same mechanism produces,
found while checking the successor pairs:

- **JCI.** Johnson Controls Inc (53669) merged into Tyco International
  plc (833444) on 2016-09-02 and the Tyco registrant took the JCI
  symbol. The SEC map gave JCI 833444, which carried Tyco's fundamentals
  back through JCI's history while TYC was unmatched. Now JCI is 53669
  to 2016-08 and 833444 after; TYC is 833444 to its removal.
- **CB.** Chubb Corp (20171) held the CB symbol until ACE Ltd (896159)
  bought it in January 2016 and took the name and the symbol. CB was
  mapped to 896159 back to 2010, so ACE's balance sheet sat under both
  CB and ACE for six years. Now CB is 20171 to 2015-12 and 896159 after.

The share-class test is applied month by month on the resolved map:
no CIK is held by two index members in the same month unless their
security names share a stem (Alphabet Class A / Class C, Comcast /
Comcast Series K, 21st Century Fox) or `ticker_renames.csv` pairs them.
A rename (AA to ARNC to HWM under CIK 4281) passes because the tickers
are never members together.

## Coverage

Members with a value at the December month-end, before and after:

| concept | 2011 | 2015 | 2020 | 2024 |
|---|---|---|---|---|
| members | 498 | 503 | 504 | 503 |
| assets, before | 436 | 458 | 493 | 496 |
| assets, after | 494 | 501 | 503 | 502 |
| equity, after | 494 | 500 | 503 | 502 |
| net income, after | 481 | 494 | 491 | 499 |
| revenue, before | 374 | 398 | 458 | 475 |
| revenue, after | 429 | 436 | 468 | 481 |
| cogs, after | 294 | 291 | 318 | 313 |
| market cap, before | 262 | 315 | 385 | 421 |
| market cap, after | 280 | 331 | 394 | 426 |

`assets` coverage is at least **97.8%** of members in every month from
2011-01-31 (the minimum, January 2011; median 99.6%), so F1b's bar of
95% is met. The audit rerun on the new panel leaves 8 rows across the
three months:

| ticker | class | why it stays |
|---|---|---|
| HON 2011 | other | total assets tagged `AssetsNet` in FY2010-11; a tag-map question for F3 |
| HST 2011, PCL 2011 and 2015, LM 2015 | other | every balance-sheet line carries a `LegalEntity` segment; the ingest keeps unsegmented rows only |
| WPX 2011 | no_xbrl | spun off 2011-12-31, first 10-K in 2012 |
| FRC 2022, SBNY 2022 | no_xbrl | banks that filed with the FDIC, not the SEC; never on EDGAR |

Revenue and COGS coverage moved with the map but remain the F3 problem
(429 and 294 of 498 in 2011). Market cap moved by 18 to 26 names; the
1bn floor is F2's problem.

The 10-K documents for the 78 newly mapped CIKs were not on disk;
`fetch --step text` was run so the text factor sees the same registrants
as the fundamentals when F4 rebuilds it.
