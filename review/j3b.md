# Review — Step J3b — The word-count pool cannot hang silently; the README's prose figures are filled, not typed

Date: 2026-09-16   Commit: (this commit)   Tests: 196/196   Recompute: matched (9 m 57 s, foreground; `decisions/drift/2026-09-16.md` rewritten with the same text)

The two open items in `review/j3a.md`. No specification was rerun and no series changed; `reports/specifications.csv` is untouched.

## What changed

- `src/backtester/text.py` `word_counts` — the `ProcessPoolExecutor` is built on `multiprocessing.get_context("spawn")` explicitly; the documents go in chunks of `WORD_COUNT_CHUNK = 8` as one future each, and the parent waits `WORD_COUNT_TIMEOUT_S = 600` seconds per future. A chunk that is not back raises `TimeoutError` naming the chunk and its first file; the pending futures are cancelled and the pool is shut down without waiting for the workers. The docstring records the J3a deadlock. `_count_many` is the per-chunk function (a module-level function, as spawn needs).
- `tests/test_text.py` (+1) — 52 gzipped documents through the pool with two workers and a 120 s timeout equal the sequential count, key by key.
- `src/backtester/report.py` — `prose_figures(cfg)`: `coverage_figures` plus `gap_first` / `gap_last` (the monthly check's first and last `gap_pct`, integer percent), `cap_shares` (`cap_share_<year>`: mean over the year's month-ends of `market_cap / n_members` in `fundamentals_coverage.csv`), per factor from `results.csv` (`gross_ann_`, `net_ann_`, `turnover_`, `breakeven_`, `sharpe_net_`, `alpha_`, `alpha_t_`, `r2_`, `beta_<k>_`, `t_<k>_`) and `corr_<series>_<benchmark>` from `validation.csv`; formats are the tables' (`_f`, `_be`) with the README's minus sign (`MINUS`, U+2212). `fill_files` fills from it. `results_frame` adds `t_mkt_rf`, `t_hml`, `t_umd`, `t_rmw` (the attribution table printed them; the csv did not carry them) and `build` writes the appendix row into `results.csv` too, so the text bullet has a source. The variants note in `results.md` had "39% of members in 2010, 86% in 2023" typed into the f-string; it now prints `cap_shares`.
- `README.md` — 40 placeholders (was 6): the value attribution sentence and the after column of its before/after table (`beta_hml_value`, `t_hml_value`, `r2_value`, `alpha_value`, `alpha_t_value`, `corr_value_hml`, `sharpe_net_value`), the momentum bullet (`beta_umd_momentum`, `t_umd_momentum`, `r2_momentum`, `turnover_momentum`, `breakeven_momentum`), the value bullet's loading, the low-volatility bullet (`beta_mkt_rf_low_vol`, `t_mkt_rf_low_vol`, `beta_rmw_low_vol`, `t_rmw_low_vol`, `alpha_low_vol`, `alpha_t_low_vol`), the text bullet (`gross_ann_`, `net_ann_`, `alpha_`, `alpha_t_`, `r2_text_change`), the Data row (`gap_first`, `gap_last`) and the cap-weighted shares (`cap_share_2010`, `cap_share_2023`). 27 distinct new keys.
- `tests/test_readme.py` (+2, and the J3a test now reads `prose_figures`) — `test_prose_figures_in_the_readme_are_the_reports`: every placeholder carries the value the report computes, the 27 keys are all present, the momentum and low-volatility loadings equal the attribution table's cells to the digit, the cap-weighted shares are the sentence `results.md` prints and equal a by-hand mean over 2010, and `results.csv` has the four t columns and the text row. `test_prose_figures_are_formatted_like_the_tables`: a synthetic `results.csv` and `validation.csv` in a temp reports dir give the expected strings, U+2212 only.
- `tests/test_site.py` — the cards are the headline keys of `results.csv`, not every row; the text row is asserted not to be a card.
- `reports/results.csv` (+4 columns, +1 row), `reports/results.md` and `docs/results.md` (the one sentence), `methodology.pdf` (regenerated, same size), `CLAUDE.md` (196 tests). `docs/index.html` byte-identical: the site reads none of the changed cells.

## Findings

> Claim: the cap-weighted shares in the README and in results.md were three fixes stale.
> Number: "39% of members in 2010, 86% in 2023" was typed on 2026-09-11 (f126d7f, then as "Fundamentals coverage is 39% ... 86%"), reworded in c728570 to "Cap-weighted runs hold only the names with a market cap (...)" with the same two numbers, and never regenerated. The share of members with a market cap is 61% in 2010 and 95% in 2023 today (`fundamentals_coverage.csv`, `market_cap / n_members`, mean over the year's month-ends).
> Rows (year, mean, median, first month, last month): 2010, 61.2, 58.4, 55.0, 68.3; 2023, 94.8, 95.0, 93.8, 95.2. On the 11 September file the same column gives 45.7 and 82.7 (39.1 in January 2010), so the original 39/86 was not this statistic either, or not this file; the definition that produced it is not recoverable and is not reproduced. What the sentence claims — the names a cap-weighted run can hold — is this column.

> Claim: the text bullet quoted a run three fixes old, and nothing had caught it.
> Number: it read "−0.2% gross, −1.0% net, alpha −0.5% (t −0.4), R² 0.03"; the appendix table two sections below it, in the same file, said 0.1%, −0.6%, −0.2% (−0.2), 0.04. The fill wrote the table's values. `test_every_number_in_the_answer_is_in_a_table` covers the answer paragraph only, and the appendix row was not in `results.csv`.
> Rows (figure, README before, after): gross ann. −0.2% → 0.1%; net ann. −1.0% → −0.6%; alpha −0.5% → −0.2%; alpha t −0.4 → −0.2; R² 0.03 → 0.04. Two more in the same bullet were wrong and are outside the mechanism (no `results.csv` column): "Jaccard instead of cosine gives 0.05 net" (the variants table says 0.01) and "every variant is within ±0.3 of zero" (cap-weighted is −0.35); both corrected by hand from the table, 0.01 and ±0.35.

> Claim: every other prose figure J3b wrapped was already the report's.
> Number: 33 of the 40 placeholders were filled with the value they already carried; the seven that changed are the two cap shares and the five text figures above.
> Rows (key, value): beta_umd_momentum 0.90, t_umd_momentum 15.9, r2_momentum 0.67, turnover_momentum 0.62, breakeven_momentum 19 bp; beta_hml_value 0.42, t_hml_value 7.7, r2_value 0.52, alpha_value −1.9%, alpha_t_value −0.9, corr_value_hml 0.55, sharpe_net_value −0.19; beta_mkt_rf_low_vol −0.67, t_mkt_rf_low_vol −11.3, beta_rmw_low_vol 0.93, t_rmw_low_vol 8.2, alpha_low_vol 1.0%, alpha_t_low_vol 0.4; gap_first 31%, gap_last 0%.

> Claim: the Data row's "31% in 2010 falling to 0%" is the first and last month of the coverage check.
> Number: `gap_pct` at 2010-01-31 is 30.85 and at 2026-07-31 is 0.2; December 2010 (the site's bar) is 29.9 and the 2010 mean is 30.2, neither of which rounds to 31. First-to-last is the only reading of the sentence that gives both numbers, and it is now the definition (`gap_first`, `gap_last`).
> Rows: 2010-01-31, 496 members, 343 priced, 30.85; 2026-07-31, 503, 502, 0.2.

> Claim: the pool path counts what the in-process path counts.
> Number: 52 documents, 2 workers, 7 chunks; the dict equals the sequential one and one document's counter is checked by hand. The recompute ran the real path (thousands of 10-Ks, 16 workers) and matched.
> Rows: `test_word_counts_in_a_spawned_pool_match_the_sequential_count`, 1.1 s.

## Before / after

| Item | Before (fc08a65) | After |
|---|---|---|
| `word_counts` pool | `pool.map`, default context, no timeout | spawn context, one future per 8 documents, 600 s each, cancel-and-raise on timeout |
| README placeholders | 6 (coverage) | 40 (coverage, loadings, turnover, break-even, shares, gaps) |
| Cap-weighted shares (README, results.md) | 39% / 86% | 61% / 95% |
| Text bullet | −0.2% / −1.0% / −0.5% (−0.4) / 0.03 / 0.05 / ±0.3 | 0.1% / −0.6% / −0.2% (−0.2) / 0.04 / 0.01 / ±0.35 |
| `results.csv` | 5 rows, 46 columns | 6 rows, 50 columns |
| Any Sharpe, correlation or spec-log row | — | unchanged |
| Recompute | matched, 8 m 45 s | matched, 9 m 57 s |
| Tests | 193 | 196 |

## Not verified

- **The timeout path** was not exercised: no chunk timed out in the recompute, and there is no unit test for it (a chunk that hangs on demand would need a hanging function in `src/`, and the spawned child imports the module fresh, so a monkeypatched one does not reach it).
- **Whether the explicit spawn context changes anything on this machine.** Windows has no other start method, so `get_context("spawn")` is the default here; it is explicit so the code says what it assumes on a machine that has `fork`. The J3a hang is therefore not explained by the context, and the per-future timeout is the part that would have surfaced it. The cause of the hang is still not known.
- **The page in a browser** — `docs/index.html` did not change.

## Open

- **Prose figures still typed** (from `results.md`, the convention for what has no placeholder): the variant Sharpes in the factor bullets (momentum "0.19–0.26" and "0.20", value "−0.45", quality "0.27", "0.34", low volatility "0.39" and "0.28", composite "−0.18", the text bullet's Jaccard 0.01 and ±0.35), the results-table figures restated in prose ("loses 2.1% a year net", "loses 4.3% a year gross", "net Sharpe 0.22", "Fama-MacBeth t 1.2", "DSR 0.06 / 0.38", "69%"), the before-F2 column of the value table (0.48, 4.7% (2.3), 0.10, 0.25 — historical, from `decisions/f4_before_after.md`), the "0.55 instead of 0.25", and the Data section's "496–504", "818", "98%", "97%". `results.csv` has `sharpe_<tag>` columns for the variants, so those are one line each in `prose_figures`; the Jaccard variant has no column.
- **`cap_share_<year>` is a new definition**, not a recovery of the old one. If the 39/86 came from somewhere specific (a cw run's holdings over members, say), that source is not in the repo and the sentence now says what `fundamentals_coverage.csv` says.

## Against the plan

- **Both items are `review/j3a.md`'s open items.** The step brief named turnovers, loadings, the cap-weighted shares and the Data row's gaps; also wrapped, because they sit in the same sentences and were the same mechanism: break-even (beside the turnover), R², alpha and its t (inside the loading parentheses), the value table's after column and the HML correlation (the same sentence and the same table row as the loading), and the text bullet's gross and net (which turned out wrong). Stated here rather than done quietly.
- **The appendix row entering `results.csv`** changed a file the site reads; the site filters to its five keys and the page is byte-identical, and `test_every_reported_factor_is_a_card` now says so.

## Reviewer reads (max 6, in order)

1. `src/backtester/text.py` `word_counts` — 35 lines, the docstring first.
2. `src/backtester/report.py` `cap_shares` and `prose_figures` — 70 lines.
3. `git diff fc08a65 -- README.md` — 30 lines, seven of them with a changed number.
4. `git diff fc08a65 -- reports/results.md` — the one sentence.
5. `tests/test_readme.py` `PROSE_KEYS` and the two new tests.
6. `git log -p f126d7f c728570 -- README.md | grep 39%` — where the shares came from.
