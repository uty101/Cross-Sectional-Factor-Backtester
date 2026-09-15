# COGS and revenue tag coverage (FIX_PLAN F3)

**Date:** 2026-09-15. **Script:** `scripts/tag_gap.py`. **Evidence:**
`data/checks/tag_gap_{cogs,revenue}_{2011,2015,2020}.csv`,
`data/checks/tag_coverage.csv`, `data/checks/revenue_derived.csv`,
`data/checks/fundamentals_coverage.csv`. **Tests:** `tests/test_tag_map.py`.
`scripts/check_tag_map.py` confirms tags were only added.

## What the gap script found

For each of cogs and revenue and each of FY2011, FY2015, FY2020, every
universe CIK with a 10-K that year and no value for the concept, and
the tags those filers do use. The plan's threshold is a tag used by 5
or more missing filers, from its priority list.

**COGS** (267, 280, 230 missing filers). The only tag on the plan's list
that clears 5 is `CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization`
(7, 13, 0); added. What the missing filers actually use is
`CostsAndExpenses` (110, 119, 106) and `OperatingCostsAndExpenses` (15,
21, 17), both a single line that includes SG&A and are excluded by the
plan and by the comment now in `tag_map.toml`; then utility lines
(`FuelCosts` 21, `CostOfPurchasedPower` 15), REIT lines
(`CostOfOtherPropertyOperatingExpense`), and `DirectOperatingCosts` (6,
airlines and hotels, not on the list and not a cost of goods). The 14
filers in FY2020 that "use" `CostOfGoodsAndServicesSold` while missing
it are filers that carry the tag in 10-Qs and a different structure in
the 10-K; not a map problem.

**Revenue** (81, 76, 27 missing). `InterestAndDividendIncomeOperating`
(20, 20, 17) is on the plan's list and clears 5, but it is gross
interest income before interest expense, so it is **not added as a
revenue tag**; banks get the derived rule instead (below). Four tags not
on the list clear 5 and are each the whole top line for the filers that
use them, so they were added: `SalesRevenueServicesNet` (12, 14, 0),
`RegulatedAndUnregulatedOperatingRevenue` (5, 5, 6),
`RealEstateRevenueNet` (6, 6, 0), `OilAndGasRevenue` (7, 5, 0).
`InterestAndFeeIncomeLoansAndLeases` (10, 13, 10) and
`OperatingLeasesIncomeStatementLeaseRevenue` (6, 8, 3) are components
and were not.

**Assets.** `AssetsNet` was added as a second tag: Honeywell's total
assets in FY2010-11 (the F1 audit's `other` row).

## The bank rule

Two new concepts, `net_interest_income` (`InterestIncomeExpenseNet`)
and `noninterest_income` (`NoninterestIncome`). `fundamentals.bank_revenue`
fills `revenue` and `revenue_ttm` with their sum for the **Financials
sector only**, only where no revenue tag exists, and stamps
`revenue_source` (`tag` / `derived_bank`). `data/checks/revenue_derived.csv`
logs it per December: 19 members derived in 2011, 10 in 2025; the
Financials with no revenue at all fall from 13 (2010) to 0-5.

`gross_profitability` excludes Financials by rule, as Novy-Marx does;
the signal's docstring says so. Accruals keep them.

## Coverage, before and after

Members with a value at the December month-end
(`fundamentals_coverage.csv`; the cache was re-ingested, which
`CLAUDE.md` warns is needed after a tag-map change):

| year | members | revenue before | revenue after | % | cogs before | cogs after | cogs, non-financials | % of non-financials |
|---|---|---|---|---|---|---|---|---|
| 2011 | 498 | 429 | 464 | 93.2 | 294 | 294 | 292 / 435 | 67.1 |
| 2012 | 498 | 427 | 466 | 93.6 | 292 | 297 | 295 / 435 | 67.8 |
| 2013 | 498 | 433 | 471 | 94.6 | 292 | 298 | 296 / 437 | 67.7 |
| 2014 | 500 | 441 | 477 | 95.4 | 297 | 306 | 303 / 438 | 69.2 |
| 2015 | 503 | 436 | 475 | 94.4 | 291 | 300 | 298 / 442 | 67.4 |
| 2016 | 504 | 444 | 483 | 95.8 | 295 | 305 | 303 / 442 | 68.6 |
| 2017 | 504 | 439 | 479 | 95.0 | 291 | 300 | 298 / 438 | 68.0 |
| 2018 | 504 | 439 | 482 | 95.6 | 304 | 311 | 308 / 439 | 70.2 |
| 2019 | 504 | 474 | 496 | 98.4 | 300 | 311 | 307 / 441 | 69.6 |
| 2020 | 504 | 468 | 489 | 97.0 | 318 | 318 | 314 / 443 | 70.9 |
| 2021 | 504 | 478 | 499 | 99.0 | 318 | 318 | 315 / 442 | 71.3 |
| 2022 | 502 | 477 | 497 | 99.0 | 312 | 312 | 310 / 440 | 70.5 |
| 2023 | 502 | 476 | 495 | 98.6 | 313 | 313 | 311 / 442 | 70.4 |
| 2024 | 503 | 481 | 497 | 98.8 | 313 | 313 | 311 / 441 | 70.5 |
| 2025 | 503 | 483 | 499 | 99.2 | 314 | 314 | 312 / 439 | 71.1 |

Universe CIKs with a 10-K value, per fiscal year (`tag_coverage.csv`):
revenue 611 to 641 in FY2011, 620 to 648 in FY2015, 625 to 631 in
FY2020; cogs 425 to 431, 416 to 429, 422 to 422.

## Against the plan's bar

- **Revenue at or above 95% of members every year from 2011: not met
  for 2011-2013 and 2015** (93.2, 93.6, 94.6, 94.4%), met from 2014
  otherwise and 97-99% from 2019. The 34 members missing in 2011 are
  idiosyncratic: five multi-registrant utilities (FE, PGN, POM, TE, WEC)
  that tag every consolidated line with a `LegalEntity` segment, which
  the ingest drops (the same defect the F1 audit found for Host, Plum
  Creek and Legg Mason), and filers on custom extension tags (CMG,
  CCL, DHI). No remaining revenue tag is used by 5 or more of them.
- **COGS at or above 85% of non-financial members: not met, 67-71%.**
  The gap is structural, not a map gap: about 130 non-financial members
  have no cost-of-goods line in their income statement. They report a
  single `CostsAndExpenses` or `OperatingCostsAndExpenses` (excluded by
  the plan because it includes SG&A), or a utility's fuel and purchased
  power, a REIT's property operating expense, an E&P's lease operating
  expense. Compustat's COGS item standardises those into a cost of
  goods sold; XBRL does not, and deriving one (CostsAndExpenses less
  SG&A less depreciation) would be a fourth definition on top of the
  three the plan lists. Not done; the reported gross profitability is
  computed on the 67-71% of non-financials that report the line and
  the results table must say so (F4).

The bar was not lowered. The tag map only grew, every added tag has
rows in the cache, and nothing was tuned against a result.
