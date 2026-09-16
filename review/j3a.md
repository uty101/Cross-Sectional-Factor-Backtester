# Review — Step J3a — No portfolio at a month-end with nothing to earn; the coverage figures are filled, not typed

Date: 2026-09-16   Commits: 46cdaf9 (the engine rule) and this one (the rerun, the placeholders)   Tests: 193/193   Recompute: matched (8 m 45 s, `decisions/drift/2026-09-16.md` rewritten with the same text)

The two open items in `review/j2c.md`.

## What changed

- `src/backtester/portfolio.py` `backtest` — after the `min_names` filter, a month with no non-null `ret_fwd` for any name is dropped from the signal frame (`semi` join on the months that have one), so no decile is cut, no weight is written, no rebalance is paid and no row is emitted there. The window's last month-end (2026-08-31) is the case: every series carried a formation row with `ret_gross` exactly 0 and `ret_net` of minus the cost. Committed on its own first (46cdaf9) so the rerun's rows name a commit that contains it; the J1 rows were stamped with the commit before their fix.
- `tests/test_portfolio.py` (+1) `test_a_month_with_no_forward_return_forms_no_portfolio` — four names, three month-ends, the third with a signal and no return for anyone: two long-short rows, two decile months, two weight months, turnovers `[1.0, 2.0]` (formation from cash, then every rank reversed); fails on the old engine with three rows.
- `reports/specifications.csv` — 484 rows (was 436): every specification again under `post-J3a`, all 48 stamped `46cdaf9`; 61 distinct keys and 8 candidates as before, so N does not move.
- `data/processed/long_short_*.parquet` — every series ends at 2026-07-31 (was 2026-08-31): momentum, low_vol, beta, hml_replica and every hold-k/cw/terminal/nosector variant 199 rows (was 200), value, quality, composite, rmw_replica 198 (was 199), text_change 186 (was 187).
- `src/backtester/report.py` — `COVERAGE_MAX_GAP_PCT = 20.0` (the split table's default, now named); `coverage_figures(cfg)` reads `gap_pct` from `price_coverage_summary.csv` and prints `gap_pct`, `covered_pct` (its complement) and, from `price_coverage_monthly.csv`, `good_months` and `first_good_month` (the count and first of the months with a gap at or under 20, which is the number the split table prints); `fill_placeholders`, `strip_placeholders`, `PLACEHOLDER = <!--cov:key-->value<!--/cov-->`; `fill_files` rewrites `README.md` and `reports/answer.md` in place, and `build` calls it last. An unknown key raises: a figure nothing computes is a figure typed from memory.
- `README.md`, `reports/answer.md` — the six typed figures are placeholders: `gap_pct` three times (the answer's 14.7%, its copy in the README, the Data table's bold 14.7%), `covered_pct` once (85.3%), `good_months` twice (128), and `first_good_month` twice (2015-12), which was typed next to each 128 and would go stale with it. The markers are HTML comments, invisible on GitHub. The Quality row of the results table is re-pasted (2.6% / 2.0%, was 2.5% / 1.9%).
- `src/backtester/site.py` — the answer and the what-did-not-work bullets are read through `strip_placeholders`, so the markers never reach `DATA.answer` (rendered as `textContent`, where they would have been visible).
- `tests/test_readme.py` (+2) — `test_coverage_figures_in_the_readme_and_answer_are_the_checks`: every placeholder in both files carries the value `coverage_figures` gives now, every key is one the report computes, the key counts are exactly `{gap_pct: 3, covered_pct: 1, good_months: 2, first_good_month: 2}`, a fill is a no-op, and the same figures are the ones `results.md` prints ("Price history covers 85.3%", the split header "(from 2015-12-31)"). `test_placeholders_are_filled_in_place_and_stripped_for_the_page`: the fill, the strip, the unknown key.
- `reports/results.md`, `results.csv`, `methodology.pdf`, charts 1 and 4, `docs/` — regenerated. `validation.csv`, `exclusions.csv`, `weighting_gap.csv`, charts 2 and 3 byte-identical.
- `CLAUDE.md` — 193 tests; 484 spec rows, 288 of them reruns.

## Findings

> Claim: the row the rule removes is the untradeable one and only that one.
> Number: every base series' last month is 2026-07-31 and every series is exactly one row shorter; no other month lost a row (the recompute rebuilds every series from raw and matches to 1e-10).
> Rows (series, rows before, after, last turnover now): momentum 200 → 199, 0.60; value 199 → 198, 0.24; quality 199 → 198, 0.17; low_vol 200 → 199, 0.30; composite 199 → 198, 0.52; text_change 187 → 186, 0.07; beta 200 → 199, 0.23; hml_replica 200 → 199, 0.14; rmw_replica 199 → 198, 0.05. The removed momentum row was 0.0 / −0.0012 / 0.58 (`review/j2c.md`).

> Claim: the change is at the third or fourth decimal of every Sharpe and never at the second except by rounding.
> Number: over the 48 specifications, net Sharpe post-J3a minus post-J1 is in [−0.0010, +0.0014], mean +0.00002; gross in [−0.0012, +0.0008].
> Rows (specification, net post-J1 → post-J3a): momentum base 0.0821 → 0.0827; value base −0.1900 → −0.1902; quality base 0.2222 → 0.2230; low_vol base −0.2612 → −0.2617; composite base −0.3094 → −0.3097; text_change base −0.1144 → −0.1145; beta −0.3813 → −0.3821; quality hold6 0.2185 → 0.2199 (the largest); low_vol cw −0.4914 → −0.4924 (the most negative move); hml_replica −0.2531 → −0.2536; rmw_replica 0.2228 → 0.2234. The hold-k series lose a row too: the last month was a non-rebalance month there, held at zero return and zero turnover, and it is no longer a month.

> Claim: the report's printed numbers move in five cells.
> Number: `git diff reports/results.md` is the header's run count (436 → 484) and five table cells; every other cell, including every validation correlation, is unchanged.
> Rows: Quality gross 2.5% → 2.6% and net 1.9% → 2.0% (0.02541 → 0.02553, 0.01946 → 0.01958 annualised); Value at 0 bp −0.12 → −0.13 (−0.1249 → −0.1252); Low volatility break-even −73 → −74 bp; Composite hold-6 −0.11 → −0.10 (−0.1052 → −0.1044); text cw −0.34 → −0.35. The coverage-split "All months" counts are 199/198 (were 200/199); the 128 well-covered months and every Sharpe in that column are unchanged, because August 2026 left the coverage check in J2c and the series here.

> Claim: the placeholders hold the values the checks give, and the report's own sentence agrees.
> Number: `coverage_figures` returns `{gap_pct: "14.7%", covered_pct: "85.3%", good_months: "128", first_good_month: "2015-12"}` from `gap_pct` 14.71 and 128 monthly rows with `gap_pct <= 20`, the first 2015-12-31; `backtester report` rewrote neither file's figures (already right) and `fill_files` reports 6 placeholders in the README and 1 in the answer.
> Rows: `results.md` line 19 "Price history covers 85.3% of member-months"; the split header "(from 2015-12-31)"; the site's `gap_note` "14.7% of member-months overall"; `DATA.answer` contains no `<!--`.

> Claim: the site's history gained one point and nothing else on the page moved by more than the report did.
> Number: `history.commits` is `[row 5, row 34, 41aa868, c153738, 788662c, b874b37, 319c33f, 46cdaf9]`, values `[0.07, 0.17, 0.16, 0.16, 0.24, 0.22, 0.22, 0.22]`; the current-year gap bar stays 0.2 (July 2026).
> Rows: `docs/index.html` differs in the `DATA` line and the two embedded charts (1 and 4); `docs/results.md`, `docs/methodology.pdf` are the regenerated files.

## Before / after

| Item | Before (8734dab) | After |
|---|---|---|
| Last formation month, every series | 2026-08-31, gross 0, net −2c·turnover | 2026-07-31 |
| Spec-log rows / distinct keys / candidates | 436 / 61 / 8 | 484 / 61 / 8 |
| Quality gross / net ann. | 2.5% / 1.9% | 2.6% / 2.0% |
| Any validation correlation | — | unchanged |
| Coverage figures in README and answer | typed, 6 places | placeholders, 8 (6 figures + 2015-12 twice), filled by `backtester report`, tested |
| Recompute | matched (J1) | matched |
| Tests | 190 | 193 |

## Not verified

- **The page in a browser** — as in every J2 review; the only rendering change is that `DATA.answer` is the stripped string.
- **GitHub's rendering of `**<!--cov:gap_pct-->14.7%<!--/cov--> of universe-months**`** — an HTML comment inside bold in a table cell. CommonMark allows inline HTML inside emphasis; not checked on GitHub itself.
- **The Dagster `results` asset** calls `report.build`, which now writes `README.md` relative to the working directory; `dagster dev` is run from the repo root, as the CLI is, and was not rerun.

## Open

- **The recompute deadlocked once.** Run in the background through the Bash tool, `recompute.full` wrote `fundamentals_monthly.parquet` at 15:44 and then sat for two hours in `text.word_counts`' `ProcessPoolExecutor`: 16 workers each with ~71 s of CPU and every thread waiting, the parent at 1 GB. Killed and rerun in the foreground from PowerShell it took 8 m 45 s and matched. Nothing in the code changed between the two runs. Not diagnosed; noted so the next session that sees a silent recompute checks the process tree before the code.
- **`good_months` is not in `price_coverage_summary.csv`.** The brief for this step said the figures come from the summary; the gap and its complement do, but the summary has no count of well-covered months, so that one is counted from `price_coverage_monthly.csv` against the report's own threshold (20%), which is the right owner of the number: the threshold is a reporting choice, not a prices-build one. Adding it to the summary would tie the prices step to a report constant and need a prices rebuild for a number the report already computes.
- **The README's other typed figures** (turnovers, loadings, the 39% / 86% cap-weighted shares, the 31% and 0% in the Data row) remain typed from the report's outputs. The two tests on the results table and the answer paragraph cover the table and the answer; nothing covers the prose. The same placeholder mechanism takes any key `coverage_figures` (or a sibling) computes.

## Against the plan

- **Both items are `review/j2c.md`'s two open items**, not FIX_PLAN_4. The plan's numbers did not move at two decimals; the spec log grew by 48 rows and N by none.
- **The first_good_month placeholder is a widening** of "six figures": the month is typed beside each of the two 128s and means nothing without it.

## Reviewer reads (max 6, in order)

1. `src/backtester/portfolio.py` `backtest` — the five lines after the `min_names` filter.
2. `tests/test_portfolio.py` `test_a_month_with_no_forward_return_forms_no_portfolio`.
3. `src/backtester/report.py` — `coverage_figures` to `fill_files` (60 lines) and the `fill_files(cfg)` call at the end of `build`.
4. `git diff 8734dab -- README.md reports/answer.md` — seven lines: six placeholders and the Quality row.
5. `tests/test_readme.py` last two tests.
6. `git diff 8734dab -- reports/results.md` — the run count and five cells.
