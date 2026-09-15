# Before and after the data fixes (FIX_PLAN F4)

**Date:** 2026-09-15. Every candidate and sensitivity specification was
run again on the panel after F1 (CIK map), F1b (CIK per era), F2 (share
counts in the price basis) and F3 (tags and the bank rule); the 48 new
rows carry the note suffix `post-F3` in `reports/specifications.csv`,
and 48 more `post-F3 ingest v2` after the first recompute found the
ingest's tie between two bare rows of one tag was broken by sort order
(now the larger value, as a rule) and the num cache was not stamped with
the tag map it was built under (now it is, and re-ingests itself), and
48 more `post-F3 first-filed tie` after the second recompute found the
same kind of tie in `first_filed` between an FSDS row and the SEC API's
fallback row (the FSDS row wins, as a rule). N = 329, 55 candidates.
Neither rerun changed a reported number except quality's DSR against
candidates, 0.07 to 0.06, which is N doing its job. The third
`recompute.full` matched to 1e-10.
"Before" is `reports/results.md` and `reports/validation.csv` as
committed at `788662c`; "after" is what `backtester report` writes now.

## Reported factors (equal-weighted, sector-neutral, 10 bp)

| Factor | Net Sharpe before | after | Mean IC before | after | Validation before | after |
|---|---|---|---|---|---|---|
| Momentum 12-1 | 0.05 | 0.04 | 0.007 | 0.006 | 0.793 vs UMD | 0.784 |
| Value (B/P, E/P) | **0.48** | **−0.16** | 0.011 | −0.004 | 0.245 vs HML | **0.556** |
| Quality (GP/A, accruals) | 0.16 | 0.24 | 0.009 | 0.008 | 0.070 vs RMW | 0.070 |
| Low volatility | −0.25 | −0.27 | 0.003 | 0.003 | — | — |
| Composite | 0.32 | −0.33 | 0.018 | −0.002 | — | — |
| 10-K text similarity | −0.15 | −0.17 | 0.003 | 0.004 | — | — |
| Low beta | — | −0.40 | — | — | 0.420 vs BAB | 0.418 |

## The join tests

| Replication | vs full factor before | after | vs big-cap leg before | after |
|---|---|---|---|---|
| B/P, cap-weighted terciles | 0.648 | 0.722 | 0.74 | 0.781 (0.896 from 2016) |
| Pre-tax income / FY equity, cap-weighted terciles | 0.281 | 0.436 | 0.48 | 0.623 |

RMW replication against the big-cap leg by period: 0.69 in 2010–12 (was
0.07), 0.38 in 2013–15 (was 0.31), 0.83 in 2016–18 (was 0.67), 0.62 in
2019–21 (was 0.74), 0.61 from 2022.

## What moved, and why

**Value reversed sign, and that is the finding.** Before F2 every name
that later split carried a market cap too small by the split ratio for
its whole pre-split history (Chipotle 50-for-1 in 2024: a 2015 cap of
297m instead of 15bn), because yfinance's close is split-adjusted and the
SEC count is not. Book-to-price and earnings yield are divided by that
cap, so the decade's biggest winners (CMG, DECK, SMCI, CPRT, CSGP, TECH,
ENPH, ...) sat in the value long leg with a B/P 6 to 50 times too large.
The old value factor was part momentum, and the old README's "value
alpha of 4.7% (t 2.3) after HML, with an HML loading of only 0.10" was
that. Now the loading on HML is 0.42 (t 7.7), R² 0.52, the alpha is
−1.5% (t −0.7), and the correlation with HML went from 0.25 to 0.56
without any change to the signal's definition. Large-cap value earned
nothing over 2010–2026 and the factor now says so.

The composite followed value down (0.32 to −0.33): with value, low
volatility and text negative there is nothing left to average.

**Quality rose from 0.16 to 0.24** and its cap-weighted variant from 0.41
to 0.30. Three things changed underneath it: 18% more members have
fundamentals at all (F1b), gross profitability excludes financials by
rule and is computed on 67–71% of non-financials with the one added cogs
tag (F3), and accruals use the same larger panel. The RMW correlation of
the sector-neutral composite is unchanged at 0.07; the replication built
French's way is what moved (0.48 to 0.62 against the big-cap leg), and
its early-years weakness turned out to be the CIK map, not XBRL
coverage: 2010–12 went from 0.07 to 0.69. The 2013–15 trough (0.38) is
not understood and is reported as it is.

**Momentum and low volatility barely moved** (0.05 to 0.04, −0.25 to
−0.27): they read prices, and the only thing that touched them is the
sector map for the tickers whose CIK changed. The momentum-UMD
correlation moved 0.009, under the 0.02 at which
`tests/fixtures/momentum_baseline.json` would be updated; it was not.

**Text** moved from −0.15 to −0.17 with 646 more 10-K documents fetched
for the newly mapped CIKs.

## Against the plan's bars, for the record

- Momentum vs UMD > 0.7: 0.784, pass.
- Value vs HML > 0.7: 0.556, fail (was 0.245). Quality vs RMW > 0.7:
  0.070, fail. Both are sector-neutral two-signal composites; the join
  is tested by the replications in `reports/validation.csv`, against the
  full French factors with a bar of 0.6: B/P 0.722, pass (was 0.648);
  operating profitability 0.436, fail (was 0.281). Against the big-cap
  legs, the like-for-like series, they are 0.78 and 0.62.
- Low beta vs BAB > 0.5: 0.418, fail; F5 adds the beta-hedged series.

Nothing was tuned. The signals, the costs, the windows and the universe
are what they were on `788662c`; only the data underneath changed.
