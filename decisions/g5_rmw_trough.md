# G5: the RMW replica's 2013-2015 trough (2026-09-15)

**Found.** The trough is one name with the wrong price series. `HAR`
(Harman International, an index member until 2017-03) has a yfinance
history that is not Harman: it begins 2013-01-17 at $11,505, is $5,519
six weeks later, has a median close of $5,620 and monthly moves of
+42%, +43%, −44%, −57%, −35%, −31%. Harman traded at $40-140. Against
Harman's real cover-page count of 68 million shares that price is a
market cap of $0.4-2.3 trillion, so in the cap-weighted replica HAR is
10-16% of the *short* tercile through 2013 and its noise is the tercile's
return. Dropping it (and two more reused symbols, below) takes the
2013-2015 correlation with French's big-cap RMW leg from 0.42 to 0.60
and leaves every other block where it was.

Everything here is `scripts/rmw_trough.py`; its outputs are
`data/checks/rmw_trough_disagreements.csv` and
`data/checks/rmw_trough_blocks.csv`; the four diagnostic runs are rows
in the specification log (`variant` = `exfin`, `equity_avg2`,
`ex_reused_tickers`). No reported result changed.

## Correlation with big-cap RMW by 3-year block (month earned)

| Replica | all | 2010-12 | 2013-15 | 2016-18 | 2019-21 | 2022-26 |
|---|---|---|---|---|---|---|
| as reported | 0.62 | 0.68 | **0.42** | 0.81 | 0.64 | 0.60 |
| Financials excluded | 0.47 | 0.42 | 0.05 | 0.41 | 0.58 | 0.57 |
| equity = mean of last two fiscal years | 0.61 | 0.67 | 0.41 | 0.77 | 0.64 | 0.57 |
| without HAR, EP, COL | 0.64 | 0.68 | **0.60** | 0.81 | 0.64 | 0.60 |

(The plan's 0.69 / 0.38 / 0.83 / 0.62 / 0.61 blocked by formation
month; these block by the month the return is earned, which is the
month the French factor is stamped with.)

Three months carry the trough: formation 2013-08 (replica +4.7%, RMW
−1.3%), 2013-09 (−1.8% vs +1.9%) and 2013-04 (+0.3% vs −3.0%). Without
those three the block is 0.65. In 2013-08 HAR was 15.8% of the short
tercile and returned −31%, contributing +4.9% to the long-short on its
own; in 2013-09 it was 10.7% and returned +14%, contributing −1.5%. The
2013-04 month is the banks: the short tercile was 30% Financials (JPM,
C, BAC, GS in the bottom third on pre-tax income over equity) and they
rose 11-15% that May. That one is a real difference from French, whose
big-cap leg is NYSE-breakpoint terciles over a wider universe, not an
error.

## The three things ruled out

1. **The concept.** Month by month over the 36 trough months the
   replica's terciles were compared with a naive operating-profitability
   sort, net income + interest expense + income tax over the same equity
   (`InterestExpense` and `IncomeTaxExpenseBenefit` read from the SEC
   zips for this; the interest tag exists for 64% of name-months). The
   two agree on 85.2% of tercile memberships, rank-correlate 0.937, and
   cross top-to-bottom 130 times in 16,351 name-months. Of the 20 names
   with the largest rank disagreement, 16 are the interest add-back:
   REITs (AIV, IRM, AMT, WY), telecoms (FTR, WIN, LVLT), utilities
   (AES, CMS) and levered industrials (THC, SEE, OI, MAS), where adding
   interest back moves a name up a third of the ranking. French's OP
   *subtracts* interest expense, so on those the replica's pre-tax
   income is the right side and the naive sort is not French. Two are a
   pre-tax income that is not net income plus tax (AIV, TYC: discontinued
   operations and non-controlling interests), one is the operating-income
   fallback (SWY, no pre-tax tag), one is FY equity against latest equity
   (MSI, buybacks). None of the 20 is in the top-weighted names of either
   tercile, so none moves a cap-weighted return. With `net_income_ttm` in
   place of the annual net income the agreement is 81.4%, lower, because
   the TTM numerator is a different period from the annual tax.
2. **Financials.** Excluding them makes the trough worse (0.05) and the
   whole series worse (0.47): French's RMW includes financials and the
   banks in the short tercile are a large part of what the replica gets
   right in 2016-2018.
3. **Equity.** Averaging the last two fiscal-year equities, the closest
   thing to a smoothed denominator, changes nothing (0.41).

## What was found instead, and what it touches

The price cleaning's reused-symbol rule (`prices.clean`, rule 1) drops a
removed name whose first print is *after* its last membership day. It
cannot see a reused symbol whose new series overlaps the membership
window, and three do:

| Ticker | Was | Removed | yfinance series | Median close | Months as member with the wrong series |
|---|---|---|---|---|---|
| HAR | Harman International | 2017-03 | 2013-01 to 2022-03 | $5,620 | 50 (2013-01 to 2017-02); none before 2013 |
| EP | El Paso Corporation | 2012-05 | 2008-01 to 2026-09 | $1.68 | 28 (2010-01 to 2012-04); monthly std 0.36 |
| COL | Rockwell Collins | 2018-12 | 2012-08 to 2020-11 | $0.135 | 76 (2012-08 to 2018-11); none before 2012-08 |

(`EP` already has one bad-print day removed by rule 2; the series is
wrong throughout.) Three names in 858 is not the whole story: a reused
symbol whose new holder trades at a plausible price and volatility
would pass every rule here and this scan (caps over $600bn before 2018,
three or more member-months over ±40%, median close over $2,000) as
well. The check that would catch every case is the SEC's own market
value: the 10-K cover page carries `dei:EntityPublicFloat` in dollars,
and a price × share count that is 10× or 0.1× the float at the fiscal
year-end is not that filer's price. That is a data-check file and a
cleaning rule, not a heuristic, and it belongs with F6 (a second price
source has the same symbol-reuse problem, so the cross-check is needed
whichever source wins).

**Not done here**, per the plan: no result is changed on the strength of
this. The fix is a candidate row per specification (the F4 rerun
procedure), a recompute that matches, and a note. Until then the
validation table's RMW replication reads 0.62 and its trough is
explained: 0.64 and no trough without the three reused symbols.
