# Review — Steps G1–G5 — Secrets, trial count, caveats, answer, RMW trough

Date: 2026-09-15   Commit: 16e7b02 (five commits from 4048bd9)   Tests: 161/161

## What changed

- `FIX_PLAN_2.md` — the plan, committed verbatim.
- `src/backtester/config.py` — `SECRET_NAMES`, `SECRET_STEPS`, `require(name)` (raises naming the Part A step).
- `src/backtester/cli.py` — `backtester secrets`: one line per key, `set`/`missing`, plus `gh auth status`; never a value.
- `src/backtester/speclog.py` (new) — the specification log, moved out of `portfolio.py`, which re-exports the old names. **New definition: a trial is a distinct `spec_key` = sha256 of (factor, signal, weighting, cost_bps, lag_days, rebalance, holding_months, winsor_lo, winsor_hi, n_deciles, sector_neutral, start, end, variant), numerics normalised so `10` and `10.0` key the same.** `count_trials` is the N of the deflated Sharpe; `latest_per_key` supplies the cross-trial variance.
- `reports/specifications.csv` — three columns appended (`sector_neutral`, `variant`, `spec_key`), backfilled from note and signal for all 335 rows; every pre-existing cell checked equal to HEAD. Five diagnostic rows added by G5 (two of them duplicates from re-running the script).
- `src/backtester/run.py`, `portfolio.py` — `sector_neutral` and `variant` threaded from `run_factor` to the log; `delisting()` passes `variant="terminal"`; a text-factor row records `cfg.text_similarity`.
- `src/backtester/report.py` — `trial_counts` over distinct keys; `Coverage` column and footnote; **rule: half-life prints `n/a` and the chart draws no fit when |h=1 IC t| < 1.96 (`IC_T_MIN`)**; `coverage()` = median over months of members with a finite z over members (non-financial members for `quality`, `quality_ttm`).
- `src/backtester/methodology.py` — the PDF's N wording.
- `reports/answer.md` (new) — 116 words; README carries it verbatim; a four-row value before/after table added to the README so 4.7% and 0.48 are table-backed.
- `scripts/rmw_trough.py` (new), `data/checks/rmw_trough_*.csv`, `decisions/g5_rmw_trough.md`, `decisions/g2_trial_count.md`.
- `tests/test_secrets.py`, `tests/test_speclog.py` (new); `tests/test_readme.py` (+3 tests); `tests/test_portfolio.py` (one slice pinned to the 16-column header it describes).
- `README.md`, `CLAUDE.md`, `data/checks/README.md` — numbers and pointers.

## Findings

> Claim (G2): the same specification was being counted as a new trial on every rerun.
> Number: 335 rows are 58 distinct keys (61 after G5's diagnostics); 8 candidate keys, not 55.
> Rows (date, note, git_commit, sharpe_net, spec_key) — quality, ew, sector-neutral, base:
> 2026-09-14, base min_names=50, 41aa868, 0.1567, 2b08bbb50803
> 2026-09-14, base after asof tie rule, c153738, 0.1567, 2b08bbb50803
> 2026-09-14, base quarter-wins shares rule, c153738, 0.1567, 2b08bbb50803
> 2026-09-15, base post-F3, 788662c, 0.2378, 2b08bbb50803
> 2026-09-15, base post-F3 ingest v2, 788662c, 0.2378, 2b08bbb50803
> (a sixth, "post-F3 first-filed tie", same key; one trial, six rows)

> Claim (G3): quality is computed on 70% of non-financial members.
> Number: median over 200 months 0.701; 0.51 in 2010 rising to 0.72.
> Rows (month, non-financial members, with a quality z, share):
> 2010-12, 434, 223, 0.514
> 2013-12, 437, 297, 0.680
> 2016-12, 442, 306, 0.692
> 2020-12, 443, 315, 0.711
> 2025-12, 439, 317, 0.722

> Claim (G3): no reported factor has an h=1 IC distinguishable from zero, so no half-life is printed.
> Number: 5 of 5 factors have |IC t| < 1.96 (max 1.4, quality).
> Rows (factor, IC t-stat, half-life before, after):
> Momentum 12-1, 0.6, 27.2, n/a
> Value, −0.5, none within 5y, n/a
> Quality, 1.4, none within 5y, n/a
> Low volatility, 0.2, 19.8, n/a
> Composite, −0.2, none within 5y, n/a

> Claim (G5): the RMW replica's 2013–15 trough is HAR's price series, which is not Harman International.
> Number: 2013–15 correlation with big-cap RMW 0.42 with HAR, 0.60 without (HAR, EP, COL); no other block moves by more than 0.01.
> Rows (month, yfinance close, cover-page shares, cap, ret_cal) — Harman traded at $40–140 and had ~$5bn of equity:
> 2013-04, 34,178.90, 67.9m, 2.32trn, −43.7%
> 2013-06, 25,814.10, 68.0m, 1.75trn, −56.5%
> 2013-07, 11,225.10, 68.0m, 0.76trn, −25.8%
> 2013-08, 8,325.27, 68.1m, 0.57trn, −33.7%
> 2013-09, 5,519.00, 68.1m, 0.38trn, +6.8%

> Claim (G5): the naive net income + interest + tax sort is not French's OP, and its disagreements with the replica are the interest add-back.
> Number: 85.2% tercile agreement, rank correlation 0.937; 16 of the 20 largest gaps are interest.
> Rows (ticker, sector, months, mean rank gap, top/bottom crossings, replica OP, driver):
> AIV, Real Estate, 36, 0.77, 35, 0.034, pretax_income (discontinued ops / NCI)
> THC, Health Care, 36, 0.50, 13, 0.226, interest add-back
> FTR, Communication Services, 36, 0.37, 0, 0.045, interest add-back
> HCBK, Financials, 34, 0.36, 0, 0.064, interest add-back
> SWY, Consumer Staples, 24, 0.35, 11, 0.343, pretax_income missing (operating income used)

## Before / after

| Metric | Before (4048bd9) | After (16e7b02) | Step |
|---|---|---|---|
| N for DSR (all) | 329 rows | 61 distinct keys (340 rows) | G2, G5 |
| N for DSR (cand.) | 55 rows | 8 distinct keys | G2 |
| Cross-trial variance of monthly Sharpe (all / cand.) | 0.0056 / 0.0060 over rows | 0.0049 / 0.0036 over latest row per key | G2 |
| Momentum DSR (all / cand.) | 0.00 / 0.01 | 0.02 / 0.14 | G2 |
| Value DSR | 0.00 / 0.00 | 0.00 / 0.03 | G2 |
| Quality DSR | 0.02 / 0.06 | 0.09 / 0.39 | G2 |
| Low volatility DSR | 0.00 / 0.00 | 0.00 / 0.01 | G2 |
| Composite DSR | 0.00 / 0.00 | 0.00 / 0.00 | G2 |
| Text similarity DSR (appendix) | 0.00 / 0.00 | 0.00 / 0.03 | G2 |
| Coverage column | absent | 87% / 84% / 70% of non-fin. / 87% / 52% (momentum, value, quality, low-vol, composite); text 98% | G3 |
| Half-life printed | momentum 27.2, low-vol 19.8, three "none within 5y" | n/a ×5 | G3 |
| Every other results-table cell (Sharpe, IC, turnover, break-even, attribution, validation) | — | unchanged | — |
| RMW replica vs big-cap RMW (validation table) | 0.62 | 0.62 (unchanged by rule; 0.64 without the reused symbols, diagnostic only) | G5 |

## Not verified

- **That the three reused symbols are the only ones.** The scan was caps over $600bn before 2018, three or more member-months over ±40%, and median close over $2,000. A reused symbol whose new holder trades at a plausible price and volatility passes all three. The check that would settle it: `dei:EntityPublicFloat` from the 10-K cover page against price × cover-page shares at the fiscal year-end for every (ticker, year); flag ratios outside [0.1, 10].
- **What the HAR/EP/COL series actually are.** Not identified; not needed for the finding (whatever they are, they are not Harman, El Paso or Rockwell Collins at those prices). A look at yfinance's `info` for each would settle it.
- **EP and COL's effect on the reported (equal-weighted) factors.** Both have no market cap (`market_cap.parquet` has zero rows for either: no share count matched), so they are absent from every cap-weighted run and present in equal-weighted deciles only as one name in ~50 with ±50% months. Not measured; one equal-weighted rerun of each reported factor without them would settle it, and belongs with the fix.
- **The `sector_neutral` backfill for the three "phase 6 first run" rows** (2026-09-11: value, quality, low_vol) assumed sector-neutral because the note lacks "no-sector", although the next row is labelled "phase 6 sector-neutral" as if the first three were not; `run_factor` has always appended that string, but the phase-6 rows predate the log's `kind` column and were not re-derived from code.
- **`sector_neutral` for row 94** (labelled jaccard, actually cosine) is keyed as labelled; the key count is unaffected because row 131 carries the same key.
- The `secrets` command's `gh auth status` branch was tested only on the "gh not installed" path, since gh is not on this machine.

## Open

- **The 2013-04 formation month** (replica +0.3%, big-cap RMW −3.0%) is not HAR. The short tercile was 30% Financials (JPM, C, BAC, GS in the bottom third on pre-tax income / equity) and they rose 11–15% in May 2013. That is a universe/breakpoint difference from French (NYSE breakpoints over a wider universe), consistent with the replica's 0.62 rather than 0.9 overall; not an error, not resolved.
- **Why HAR's wrong series starts in 2013-01 and not 2017.** A reused symbol should start after the original delists. Whatever `HAR` resolves to on yfinance was trading (at ~$10,000+) while Harman was still listed, which suggests a different exchange or instrument class, not a US reuse. Not pursued.
- **The 2013–15 block after the fix is 0.60, still the lowest block** (others 0.64–0.81). Part of that is the 2013-04 month above; the rest was not decomposed.

## Against the plan

- **G2 key tuple.** The plan's tuple was extended with `variant`. Without it the delisting-terminal sensitivity (6 rows) and the Jaccard text run key identically to their base specifications, undercounting trials by 7. Stated in `decisions/g2_trial_count.md`.
- **G3 coverage source.** The plan said `fundamentals_coverage.csv` for fundamentals signals and price coverage for price signals; the column is instead read off the saved z frames (what the signal was actually computed on, after every filter), which is why quality reads 70% rather than the tag-level 67–71%.
- **G4 "every number in a table on the page."** Two numbers (58/61 distinct specifications) are only in prose on the README and in `results.md`'s header; the test checks `results.md` text ∪ README tables, and the README says so. "No adjectives" was read as no evaluative ones; "largest", "split-adjusted", "non-financial" remain.
- **G5 naive sort.** Built with the annual 10-K net income rather than `net_income_ttm`, to match the annual tax and interest (the TTM version is also computed: 81.4% agreement vs 85.2%). Two extra XBRL tags were read from the zips for the diagnostic and not added to `tag_map.toml`, so no cache re-ingest and no change to the fundamentals panel.
- **G5 "no result may be changed."** Honoured; the finding is a data defect that will change results when fixed. The RMW replication bar (0.6 vs big-cap leg) is met at 0.62 as reported and would read 0.64 after the fix. No bar in this step is unmet.
- **Plan rule "one step per session, stop after each."** Lifted by the owner on 2026-09-14; five steps in one session, one commit each.
- **Diagnostic rows logged twice.** `rmw_trough.py` ran to completion twice, so `exfin` and `equity_avg2` each have two rows. Same key, so N is unaffected; the rows stay.

## Reviewer reads (max 6, in order)

1. `decisions/g5_rmw_trough.md` — the finding, the blocks table, and the three things ruled out; the one thing in this session that changes what the pipeline needs next.
2. `src/backtester/speclog.py` — `KEY_FIELDS`, `variant_of`, `sector_neutral_of`: the trial definition and every backfill assumption, in 250 lines.
3. `decisions/g2_trial_count.md` — every DSR before and after, and why 8 candidate keys.
4. `reports/results.md` (header, results table, IC decay) — the regenerated page the README is pasted from; check the `Coverage` cells and the `n/a` column against the rule.
5. `scripts/rmw_trough.py` §3 and §6 — the cap-weight concentration that exposed HAR, and the reused-ticker rerun.
6. `tests/test_readme.py` — what is now enforced between README, `answer.md` and `results.md`.
