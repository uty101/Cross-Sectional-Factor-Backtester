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
