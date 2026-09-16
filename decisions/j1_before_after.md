# J1: every reported number before and after the float overrides and the window rule (2026-09-16)

Before is `reports/results.md` at commit ba54d87 (post-H3/H4); after is the same file after `backtester rerun --note " post-J1"` with Exelon's four cover-text floats overriding its XBRL value (`data/checks/public_float_overrides.csv`) and a float-check window that closes at the first later in-band filing. Exclusion rows from the float check: 13 → 9 (Exelon's four gone); priced member-months excluded: 280 → 221 (Exelon's 49 and 10 of Prologis' 13 come back; PLD is out for 2011-06, 2011-07 and 2011-08). The GENZ and PCG float windows also close early (2010-09-07, 2020-07-30), with no effect: GENZ is excluded for its whole membership by the identity check and PCG was not a member. 48 specifications rerun, same keys, N unchanged at 61 (436 rows). A cell marked ← changed.

### Results table

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | Gross ann. | 2.7% | 2.8% ← |
| Momentum 12-1 | Net ann. | 1.2% | 1.3% ← |
| Momentum 12-1 | Vol | 15.6% | 15.6% |
| Momentum 12-1 | Sharpe (net) | 0.08 | 0.08 |
| Momentum 12-1 | DSR (all) | 0.02 | 0.02 |
| Momentum 12-1 | DSR (cand.) | 0.19 | 0.19 |
| Momentum 12-1 | Max DD | -56% | -56% |
| Momentum 12-1 | Turnover | 0.62 | 0.62 |
| Momentum 12-1 | Mean IC | 0.006 | 0.006 |
| Momentum 12-1 | IC t-stat | 0.5 | 0.5 |
| Momentum 12-1 | Break-even cost | 18 bp | 19 bp ← |
| Momentum 12-1 | Coverage | 87% | 87% |
| Value (B/P, E/P) | Gross ann. | -1.3% | -1.4% ← |
| Value (B/P, E/P) | Net ann. | -2.0% | -2.1% ← |
| Value (B/P, E/P) | Vol | 11.0% | 11.0% |
| Value (B/P, E/P) | Sharpe (net) | -0.19 | -0.19 |
| Value (B/P, E/P) | DSR (all) | 0.00 | 0.00 |
| Value (B/P, E/P) | DSR (cand.) | 0.03 | 0.02 ← |
| Value (B/P, E/P) | Max DD | -50% | -50% |
| Value (B/P, E/P) | Turnover | 0.30 | 0.30 |
| Value (B/P, E/P) | Mean IC | -0.004 | -0.004 |
| Value (B/P, E/P) | IC t-stat | -0.5 | -0.5 |
| Value (B/P, E/P) | Break-even cost | none (loses gross) | none (loses gross) |
| Value (B/P, E/P) | Coverage | 84% | 84% |
| Quality (GP/A, accruals) | Gross ann. | 2.5% | 2.5% |
| Quality (GP/A, accruals) | Net ann. | 1.9% | 1.9% |
| Quality (GP/A, accruals) | Vol | 8.8% | 8.8% |
| Quality (GP/A, accruals) | Sharpe (net) | 0.22 | 0.22 |
| Quality (GP/A, accruals) | DSR (all) | 0.06 | 0.06 |
| Quality (GP/A, accruals) | DSR (cand.) | 0.38 | 0.38 |
| Quality (GP/A, accruals) | Max DD | -24% | -23% ← |
| Quality (GP/A, accruals) | Turnover | 0.25 | 0.25 |
| Quality (GP/A, accruals) | Mean IC | 0.007 | 0.007 |
| Quality (GP/A, accruals) | IC t-stat | 1.2 | 1.2 |
| Quality (GP/A, accruals) | Break-even cost | 42 bp | 43 bp ← |
| Quality (GP/A, accruals) | Coverage | 69% of non-fin.¹ | 69% of non-fin.¹ |
| Low volatility | Gross ann. | -4.2% | -4.3% ← |
| Low volatility | Net ann. | -4.8% | -4.9% ← |
| Low volatility | Vol | 18.8% | 18.8% |
| Low volatility | Sharpe (net) | -0.26 | -0.26 |
| Low volatility | DSR (all) | 0.00 | 0.00 |
| Low volatility | DSR (cand.) | 0.01 | 0.01 |
| Low volatility | Max DD | -74% | -74% |
| Low volatility | Turnover | 0.24 | 0.24 |
| Low volatility | Mean IC | 0.002 | 0.002 |
| Low volatility | IC t-stat | 0.1 | 0.1 |
| Low volatility | Break-even cost | none (loses gross) | none (loses gross) |
| Low volatility | Coverage | 87% | 87% |
| Composite | Gross ann. | -3.3% | -3.3% |
| Composite | Net ann. | -4.4% | -4.4% |
| Composite | Vol | 14.3% | 14.3% |
| Composite | Sharpe (net) | -0.31 | -0.31 |
| Composite | DSR (all) | 0.00 | 0.00 |
| Composite | DSR (cand.) | 0.01 | 0.01 |
| Composite | Max DD | -65% | -65% |
| Composite | Turnover | 0.45 | 0.45 |
| Composite | Mean IC | -0.002 | -0.002 |
| Composite | IC t-stat | -0.2 | -0.2 |
| Composite | Break-even cost | none (loses gross) | none (loses gross) |
| Composite | Coverage | 52% | 52% |

10 of 60 cells moved.

### Validation

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 long-short | Against | UMD | UMD |
| Momentum 12-1 long-short | Correlation | 0.796 | 0.796 |
| Momentum 12-1 long-short | Months | 198 | 198 |
| Momentum 12-1 long-short | Bar | > 0.7 | > 0.7 |
| Momentum 12-1 long-short |  | pass | pass |
| B/P, cap-weighted terciles (French's construction) | Against | HML, big-cap leg | HML, big-cap leg |
| B/P, cap-weighted terciles (French's construction) | Correlation | 0.889 | 0.889 |
| B/P, cap-weighted terciles (French's construction) | Months | 198 | 198 |
| B/P, cap-weighted terciles (French's construction) | Bar | > 0.6 | > 0.6 |
| B/P, cap-weighted terciles (French's construction) |  | pass | pass |
| Pre-tax income / FY equity, cap-weighted terciles (French's construction) | Against | RMW, big-cap leg | RMW, big-cap leg |
| Pre-tax income / FY equity, cap-weighted terciles (French's construction) | Correlation | 0.638 | 0.637 ← |
| Pre-tax income / FY equity, cap-weighted terciles (French's construction) | Months | 197 | 197 |
| Pre-tax income / FY equity, cap-weighted terciles (French's construction) | Bar | > 0.6 | > 0.6 |
| Pre-tax income / FY equity, cap-weighted terciles (French's construction) |  | pass | pass |
| Low beta long-short, raw | Against | BAB (AQR) | BAB (AQR) |
| Low beta long-short, raw | Correlation | 0.415 | 0.416 ← |
| Low beta long-short, raw | Months | 197 | 197 |
| Low beta long-short, raw | Bar | > 0.5 | > 0.5 |
| Low beta long-short, raw |  | **fail** | **fail** |
| Low beta long-short, beta-hedged | Against | BAB (AQR) | BAB (AQR) |
| Low beta long-short, beta-hedged | Correlation | 0.457 | 0.458 ← |
| Low beta long-short, beta-hedged | Months | 173 | 173 |
| Low beta long-short, beta-hedged | Bar | > 0.5 | > 0.5 |
| Low beta long-short, beta-hedged |  | **fail** | **fail** |
| Value (B/P, E/P) long-short, sector-neutral | Against | HML | HML |
| Value (B/P, E/P) long-short, sector-neutral | Correlation | 0.555 | 0.554 ← |
| Value (B/P, E/P) long-short, sector-neutral | Months | 197 | 197 |
| Value (B/P, E/P) long-short, sector-neutral | Bar | > 0.7 | > 0.7 |
| Value (B/P, E/P) long-short, sector-neutral |  | not a join test: a two-signal sector-neutral composite against a raw one-signal factor | not a join test: a two-signal sector-neutral composite against a raw one-signal factor |
| Quality (GP/A, accruals) long-short, sector-neutral | Against | RMW | RMW |
| Quality (GP/A, accruals) long-short, sector-neutral | Correlation | 0.070 | 0.071 ← |
| Quality (GP/A, accruals) long-short, sector-neutral | Months | 197 | 197 |
| Quality (GP/A, accruals) long-short, sector-neutral | Bar | > 0.7 | > 0.7 |
| Quality (GP/A, accruals) long-short, sector-neutral |  | not a join test: a two-signal sector-neutral composite against a raw one-signal factor | not a join test: a two-signal sector-neutral composite against a raw one-signal factor |

5 of 35 cells moved.

### Attribution (four French factors)

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | Alpha (ann.) | 0.1% | 0.2% ← |
| Momentum 12-1 | t | 0.1 | 0.1 |
| Momentum 12-1 | Mkt-RF | -0.06 (-1.3) | -0.06 (-1.3) |
| Momentum 12-1 | HML | -0.25 (-4.6) | -0.24 (-4.6) ← |
| Momentum 12-1 | UMD | 0.90 (15.9) | 0.90 (15.9) |
| Momentum 12-1 | RMW | -0.08 (-0.8) | -0.08 (-0.8) |
| Momentum 12-1 | R² | 0.67 | 0.67 |
| Value (B/P, E/P) | Alpha (ann.) | -1.8% | -1.9% ← |
| Value (B/P, E/P) | t | -0.9 | -0.9 |
| Value (B/P, E/P) | Mkt-RF | 0.12 (3.0) | 0.12 (3.0) |
| Value (B/P, E/P) | HML | 0.42 (7.7) | 0.42 (7.7) |
| Value (B/P, E/P) | UMD | -0.34 (-7.3) | -0.33 (-7.2) ← |
| Value (B/P, E/P) | RMW | 0.17 (2.3) | 0.17 (2.3) |
| Value (B/P, E/P) | R² | 0.52 | 0.52 |
| Quality (GP/A, accruals)¹ | Alpha (ann.) | 2.4% | 2.4% |
| Quality (GP/A, accruals)¹ | t | 1.1 | 1.1 |
| Quality (GP/A, accruals)¹ | Mkt-RF | -0.03 (-0.6) | -0.03 (-0.6) |
| Quality (GP/A, accruals)¹ | HML | -0.10 (-1.7) | -0.10 (-1.7) |
| Quality (GP/A, accruals)¹ | UMD | 0.07 (1.1) | 0.07 (1.1) |
| Quality (GP/A, accruals)¹ | RMW | 0.10 (1.0) | 0.10 (1.0) |
| Quality (GP/A, accruals)¹ | R² | 0.04 | 0.04 |
| Low volatility | Alpha (ann.) | 1.1% | 1.0% ← |
| Low volatility | t | 0.4 | 0.4 |
| Low volatility | Mkt-RF | -0.67 (-11.3) | -0.67 (-11.3) |
| Low volatility | HML | -0.11 (-1.4) | -0.11 (-1.4) |
| Low volatility | UMD | 0.42 (4.9) | 0.42 (4.9) |
| Low volatility | RMW | 0.93 (8.1) | 0.93 (8.2) ← |
| Low volatility | R² | 0.62 | 0.62 |
| Composite | Alpha (ann.) | -1.7% | -1.7% |
| Composite | t | -0.6 | -0.6 |
| Composite | Mkt-RF | -0.32 (-5.1) | -0.32 (-5.1) |
| Composite | HML | 0.02 (0.2) | 0.02 (0.2) |
| Composite | UMD | 0.39 (5.4) | 0.39 (5.4) |
| Composite | RMW | 0.66 (5.0) | 0.66 (5.0) |
| Composite | R² | 0.42 | 0.42 |

6 of 35 cells moved.

### IC decay

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | IC h=1 | 0.008 | 0.007 ← |
| Momentum 12-1 | IC h=2 | 0.004 | 0.004 |
| Momentum 12-1 | IC h=3 | 0.005 | 0.005 |
| Momentum 12-1 | IC h=6 | 0.007 | 0.007 |
| Momentum 12-1 | IC h=12 | 0.003 | 0.003 |
| Momentum 12-1 | Half-life (months) | n/a | n/a |
| Value (B/P, E/P) | IC h=1 | -0.004 | -0.004 |
| Value (B/P, E/P) | IC h=2 | -0.007 | -0.007 |
| Value (B/P, E/P) | IC h=3 | -0.005 | -0.005 |
| Value (B/P, E/P) | IC h=6 | -0.007 | -0.007 |
| Value (B/P, E/P) | IC h=12 | -0.003 | -0.003 |
| Value (B/P, E/P) | Half-life (months) | n/a | n/a |
| Quality (GP/A, accruals) | IC h=1 | 0.007 | 0.007 |
| Quality (GP/A, accruals) | IC h=2 | 0.007 | 0.007 |
| Quality (GP/A, accruals) | IC h=3 | 0.005 | 0.005 |
| Quality (GP/A, accruals) | IC h=6 | 0.008 | 0.008 |
| Quality (GP/A, accruals) | IC h=12 | 0.011 | 0.011 |
| Quality (GP/A, accruals) | Half-life (months) | n/a | n/a |
| Low volatility | IC h=1 | 0.000 | 0.000 |
| Low volatility | IC h=2 | 0.000 | 0.000 |
| Low volatility | IC h=3 | 0.001 | 0.001 |
| Low volatility | IC h=6 | -0.002 | -0.002 |
| Low volatility | IC h=12 | 0.000 | 0.000 |
| Low volatility | Half-life (months) | n/a | n/a |
| Composite | IC h=1 | -0.001 | -0.001 |
| Composite | IC h=2 | -0.005 | -0.005 |
| Composite | IC h=3 | 0.001 | 0.001 |
| Composite | IC h=6 | 0.001 | 0.001 |
| Composite | IC h=12 | 0.002 | 0.002 |
| Composite | Half-life (months) | n/a | n/a |

1 of 30 cells moved.

### Net Sharpe by cost

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | 0 bp | 0.17 | 0.18 ← |
| Momentum 12-1 | 5 bp | 0.12 | 0.13 ← |
| Momentum 12-1 | 10 bp | 0.08 | 0.08 |
| Momentum 12-1 | 25 bp | -0.07 | -0.06 ← |
| Momentum 12-1 | 50 bp | -0.30 | -0.30 |
| Momentum 12-1 | Break-even | 18 bp | 19 bp ← |
| Value (B/P, E/P) | 0 bp | -0.12 | -0.12 |
| Value (B/P, E/P) | 5 bp | -0.15 | -0.16 ← |
| Value (B/P, E/P) | 10 bp | -0.19 | -0.19 |
| Value (B/P, E/P) | 25 bp | -0.28 | -0.29 ← |
| Value (B/P, E/P) | 50 bp | -0.45 | -0.45 |
| Value (B/P, E/P) | Break-even | -19 bp | -19 bp |
| Quality (GP/A, accruals) | 0 bp | 0.28 | 0.29 ← |
| Quality (GP/A, accruals) | 5 bp | 0.25 | 0.26 ← |
| Quality (GP/A, accruals) | 10 bp | 0.22 | 0.22 |
| Quality (GP/A, accruals) | 25 bp | 0.12 | 0.12 |
| Quality (GP/A, accruals) | 50 bp | -0.05 | -0.05 |
| Quality (GP/A, accruals) | Break-even | 42 bp | 43 bp ← |
| Low volatility | 0 bp | -0.23 | -0.23 |
| Low volatility | 5 bp | -0.24 | -0.25 ← |
| Low volatility | 10 bp | -0.26 | -0.26 |
| Low volatility | 25 bp | -0.30 | -0.31 ← |
| Low volatility | 50 bp | -0.38 | -0.39 ← |
| Low volatility | Break-even | -72 bp | -73 bp ← |
| Composite | 0 bp | -0.23 | -0.23 |
| Composite | 5 bp | -0.27 | -0.27 |
| Composite | 10 bp | -0.31 | -0.31 |
| Composite | 25 bp | -0.42 | -0.42 |
| Composite | 50 bp | -0.61 | -0.61 |
| Composite | Break-even | -31 bp | -31 bp |

13 of 30 cells moved.

### Variants (net Sharpe)

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | Base | 0.08 | 0.08 |
| Momentum 12-1 | Cap-weighted | 0.19 | 0.20 ← |
| Momentum 12-1 | Hold 3m | 0.18 | 0.19 ← |
| Momentum 12-1 | Hold 6m | 0.18 | 0.19 ← |
| Momentum 12-1 | Hold 12m | 0.25 | 0.26 ← |
| Momentum 12-1 | No sector neutralisation | -0.02 | -0.02 |
| Momentum 12-1 | Delisting: terminal return | 0.07 | 0.08 ← |
| Momentum 12-1 | Beta-hedged | n/a | n/a |
| Value (B/P, E/P) | Base | -0.19 | -0.19 |
| Value (B/P, E/P) | Cap-weighted | -0.45 | -0.45 |
| Value (B/P, E/P) | Hold 3m | -0.24 | -0.24 |
| Value (B/P, E/P) | Hold 6m | -0.26 | -0.26 |
| Value (B/P, E/P) | Hold 12m | -0.18 | -0.19 ← |
| Value (B/P, E/P) | No sector neutralisation | -0.12 | -0.12 |
| Value (B/P, E/P) | Delisting: terminal return | -0.19 | -0.19 |
| Value (B/P, E/P) | Beta-hedged | n/a | n/a |
| Quality (GP/A, accruals) | Base | 0.22 | 0.22 |
| Quality (GP/A, accruals) | Cap-weighted | 0.26 | 0.27 ← |
| Quality (GP/A, accruals) | Hold 3m | 0.10 | 0.10 |
| Quality (GP/A, accruals) | Hold 6m | 0.22 | 0.22 |
| Quality (GP/A, accruals) | Hold 12m | -0.00 | -0.00 |
| Quality (GP/A, accruals) | No sector neutralisation | 0.12 | 0.12 |
| Quality (GP/A, accruals) | Delisting: terminal return | 0.22 | 0.22 |
| Quality (GP/A, accruals) | Beta-hedged | n/a | n/a |
| Low volatility | Base | -0.26 | -0.26 |
| Low volatility | Cap-weighted | -0.49 | -0.49 |
| Low volatility | Hold 3m | -0.26 | -0.27 ← |
| Low volatility | Hold 6m | -0.25 | -0.25 |
| Low volatility | Hold 12m | -0.16 | -0.16 |
| Low volatility | No sector neutralisation | -0.34 | -0.34 |
| Low volatility | Delisting: terminal return | -0.25 | -0.26 ← |
| Low volatility | Beta-hedged | 0.39 | 0.39 |
| Composite | Base | -0.31 | -0.31 |
| Composite | Cap-weighted | -0.19 | -0.18 ← |
| Composite | Hold 3m | -0.31 | -0.31 |
| Composite | Hold 6m | -0.11 | -0.11 |
| Composite | Hold 12m | -0.18 | -0.18 |
| Composite | No sector neutralisation | -0.25 | -0.25 |
| Composite | Delisting: terminal return | -0.31 | -0.31 |
| Composite | Beta-hedged | n/a | n/a |

10 of 40 cells moved.

### Beta-hedged

| Row | Column | Before | After |
|---|---|---|---|
| Low volatility, raw | Net Sharpe | -0.26 | -0.26 |
| Low volatility, raw | Market beta (t) | -0.67 (-11.3) | -0.67 (-11.3) |
| Low volatility, raw | Corr. with BAB | 0.41 | 0.41 |
| Low volatility, raw | Months | 197 | 197 |
| Low volatility, beta-hedged | Net Sharpe | 0.39 | 0.39 |
| Low volatility, beta-hedged | Market beta (t) | 0.12 (1.7) | 0.12 (1.7) |
| Low volatility, beta-hedged | Corr. with BAB | 0.45 | 0.45 |
| Low volatility, beta-hedged | Months | 173 | 173 |
| Low beta, raw | Net Sharpe | -0.38 | -0.38 |
| Low beta, raw | Market beta (t) | -0.81 (-12.8) | -0.82 (-12.8) ← |
| Low beta, raw | Corr. with BAB | 0.42 | 0.42 |
| Low beta, raw | Months | 197 | 197 |
| Low beta, beta-hedged | Net Sharpe | 0.27 | 0.28 ← |
| Low beta, beta-hedged | Market beta (t) | 0.10 (1.3) | 0.10 (1.3) |
| Low beta, beta-hedged | Corr. with BAB | 0.46 | 0.46 |
| Low beta, beta-hedged | Months | 173 | 173 |

2 of 16 cells moved.

### With and without the thin months

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | All months | 0.08 (200) | 0.08 (200) |
| Momentum 12-1 | Months with price gap <= 20% (from 2015-12-31) | -0.06 (129) | -0.06 (129) |
| Value (B/P, E/P) | All months | -0.19 (199) | -0.19 (199) |
| Value (B/P, E/P) | Months with price gap <= 20% (from 2015-12-31) | -0.19 (129) | -0.19 (129) |
| Quality (GP/A, accruals) | All months | 0.22 (199) | 0.22 (199) |
| Quality (GP/A, accruals) | Months with price gap <= 20% (from 2015-12-31) | 0.34 (129) | 0.34 (129) |
| Low volatility | All months | -0.26 (200) | -0.26 (200) |
| Low volatility | Months with price gap <= 20% (from 2015-12-31) | -0.36 (129) | -0.36 (129) |
| Composite | All months | -0.31 (199) | -0.31 (199) |
| Composite | Months with price gap <= 20% (from 2015-12-31) | -0.36 (129) | -0.36 (129) |

0 of 10 cells moved.

### Fama-MacBeth

| Row | Column | Before | After |
|---|---|---|---|
| Momentum 12-1 | Premium | 0.04% | 0.04% |
| Momentum 12-1 | t (NW) | 0.5 | 0.5 |
| Momentum 12-1 | IC IR | 0.13 | 0.13 |
| Value (B/P, E/P) | Premium | -0.03% | -0.03% |
| Value (B/P, E/P) | t (NW) | -0.5 | -0.5 |
| Value (B/P, E/P) | IC IR | -0.12 | -0.12 |
| Quality (GP/A, accruals) | Premium | 0.05% | 0.05% |
| Quality (GP/A, accruals) | t (NW) | 1.2 | 1.2 |
| Quality (GP/A, accruals) | IC IR | 0.29 | 0.29 |
| Low volatility | Premium | -0.10% | -0.10% |
| Low volatility | t (NW) | -0.9 | -0.9 |
| Low volatility | IC IR | 0.03 | 0.03 |
| Composite | Premium | -0.05% | -0.05% |
| Composite | t (NW) | -0.7 | -0.7 |
| Composite | IC IR | -0.06 | -0.06 |

0 of 15 cells moved.

### reports/validation.csv

| Series | Benchmark | Before | After | Bar |
|---|---|---|---|---|
| momentum | umd | 0.7962 | 0.796 ← | 0.7 pass |
| value | hml | 0.5547 | 0.5542 ← | 0.7 fail |
| quality | rmw | 0.0704 | 0.0712 ← | 0.7 fail |
| hml_replica | big_hml | 0.8889 | 0.8888 ← | 0.6 pass |
| rmw_replica | big_rmw | 0.638 | 0.6372 ← | 0.6 pass |
| beta | bab | 0.4152 | 0.4164 ← | 0.5 fail |
| beta_hedged | bab | 0.4574 | 0.4576 ← | 0.5 fail |

### Appendix: text factor

| Column | Before | After |
|---|---|---|
| Gross ann. | 0.2% | 0.1% ← |
| Net ann. | -0.5% | -0.6% ← |
| Vol | 5.5% | 5.5% |
| Sharpe (net) | -0.09 | -0.11 ← |
| DSR (all) | 0.00 | 0.00 |
| DSR (cand.) | 0.06 | 0.05 ← |
| Max DD | -26% | -27% ← |
| Turnover | 0.29 | 0.29 |
| Mean IC | 0.003 | 0.003 |
| IC t-stat | 0.6 | 0.6 |
| Break-even cost | 3 bp | 1 bp ← |
| Coverage | 96% | 96% |

### What moved and why

- **Exelon is back** for 2010-12 to 2014-12 (49 member-months). Its four cover-text floats put the pipeline's cap at 1.000, 0.999, 0.999 and 1.000 of the SEC's value; the XBRL $59.09bn was the filer's error, as `review/h1.md` said.
- **Prologis** is out for three month-ends instead of thirteen: the post-merger count (459.0m, dated 2011-08-02, on the 10-Q/A filed 2011-09-08) puts close × count over the float at 1.0.
- Every other cell moves by at most 0.01–0.02 in Sharpe and 0.001 in correlation; the validation rows are unchanged at two decimals (momentum 0.796, B/P replication 0.889, RMW replication 0.637). One name for four years in an equal-weighted 500-name panel is what that looks like.
- **N** stays 61; the log has 436 rows.
