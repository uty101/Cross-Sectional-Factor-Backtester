# Review — Step J2b — The site says which rows are verdicts and which bar is which month

Date: 2026-09-16   Commit: (this commit)   Tests: 189/189   Recompute: not rerun (no number changed; the page reads the same files)

Four fixes to `report.site()` (`src/backtester/site.py`) and
`report/site_template.html`, from the findings in `review/j2.md`.

## What changed

- `src/backtester/site.py` — `_validation` returns `[series, benchmark, corr, bar, kind]`, `kind` being `join` for a row that tests the pipeline against the factor it rebuilds and `info` for the two composites; join rows keep `validation.csv`'s order and the info rows follow them (a stable sort on `kind == "info"`). `_gap_by_year` says what it does: December for every complete year, the latest month the check has for the final, partial one, and it raises if a year before the last does not end in December (a truncated coverage file would otherwise mislabel a bar).
- `src/backtester/report.py` — `NOT_A_JOIN_TEST = frozenset({"value", "quality"})`, the one place that says which validation rows are not join tests; `validation_table` reads it instead of a boolean on each row tuple, and `site._validation` imports it. The rendered table is unchanged (checked below).
- `report/site_template.html` — the factor card's last row reads "join test" (was "vs French"); the validation table draws the pass/fail dot only for a `join` row and a mono "n/a" in its place for an `info` row (`.na` style, one line); the gap panel's subtitle says "December of each year, the latest month for the current one".
- `report/site_data_schema.txt` — the example's validation rows carry the fifth element and the two info rows, so the example matches what the template reads.
- `tests/test_site.py` — 10 → 13: every row's kind matches `NOT_A_JOIN_TEST` and rows are matched by label since the order is no longer the file's; the info rows are exactly the two composites and come last; the template draws `r[4]==="join"` and `n/a` and says "join test", never "vs French"; every complete year's bar is that year's 31 December row and the last bar is `cfg.end`'s row; a synthetic file (2024 complete, 2025 to March) gives December 2024 and March 2025, and the same file without November–December 2024 raises.
- `docs/index.html` — rebuilt by `backtester site`: 191,883 bytes (191,662 before), the `DATA` line and the four template lines changed, the two embedded images byte-identical.

## Findings

> Claim: the two composites are on the page as information, last, with no verdict.
> Number: `DATA.validation` has 7 rows, 5 `join` then 2 `info`; the template's `tb_val` puts a dot on a `join` row and `n/a` on an `info` row.
> Rows (series, benchmark, ρ, bar, kind), in page order:
> Momentum long–short, French UMD, 0.80, 0.70, join
> B/P, cap-wt terciles, French HML big-cap leg, 0.89, 0.60, join
> Pre-tax profit / book, cap-wt terciles, French RMW big-cap leg, 0.64, 0.60, join
> Low beta long–short, AQR BAB, 0.42, 0.50, join
> Low beta long–short, beta-hedged, AQR BAB, 0.46, 0.50, join
> Value composite (not a join test), French HML, 0.55, 0.70, info
> Quality composite (not a join test), French RMW, 0.07, 0.70, info
> Before, the composites sat at rows 2–3 with a fail dot each (0.55 < 0.7, 0.07 < 0.7); `test_info_rows_are_the_two_composites_and_come_last` records that both are under their bar, which is what the dot would have said and what the footnote says is not a verdict.

> Claim: the truth about which rows are join tests lives once.
> Number: `report.NOT_A_JOIN_TEST` is read by `validation_table` (the `results.md` table) and by `site._validation`; `validation_table` rendered against the current inputs is verbatim the table in `reports/results.md` (7 rows, two ending "not a join test: ...").
> Rows: `report.py` −23 +13 lines; the row tuples lose their sixth element.

> Claim: the current year's bar is the latest month and that is now a rule, not an accident.
> Number: `gap_pct` is unchanged, `[29.9, ..., 1.0, 0.0]`; the 2026 bar is the 2026-08-31 row (`cfg.end`), the 2010–2025 bars are each year's 31 December row (`test_gap_is_one_bar_per_year` checks every one against the CSV).
> Rows (synthetic, `test_current_year_bar_is_the_latest_month_not_december`): 2024 January–December with gap m/5 and 2025 January–March with gap m/5 + 10 → `[2.4, 10.6]` (December 2024, March 2025); the same file without 2024's last two months → `ValueError` naming December.

> Claim: the card no longer says "vs French" for a row that is the factor's own join test.
> Number: "vs French" occurs 0 times in the template and the page; "join test" twice in the template (the label and the footnote's "not a join test") and four times on the page (those two and the two info series names).
> Rows: card verdicts are unchanged — momentum pass, value pass, quality pass, low volatility fail, composite n/a — since `_factor_cards` reads `verdicts` by `JOIN_TEST` series, not the row list.

> Claim: no number moved.
> Number: `git diff docs/index.html` is 4 −, 5 +: the `.na` style, the subtitle, the `DATA` line, the card label, the `tb_val` line. `results.md`, `results.csv`, `validation.csv`, the charts and the PDF are untouched.
> Rows: `uv run pytest -q` 189 passed; `ruff check` and `ruff format --check` clean.

## Before / after

| Item | Before (7a6f7cb) | After |
|---|---|---|
| Validation row | `[series, benchmark, ρ, bar]` | `[series, benchmark, ρ, bar, kind]` |
| Composites on the page | rows 2–3, fail dot | rows 6–7, "n/a" |
| Card label | vs French | join test |
| Gap subtitle | "by year" | "December of each year, the latest month for the current one" |
| `_gap_by_year` on a truncated year | silent | raises |
| Which rows are not join tests | a boolean per row tuple in `report.py` | `report.NOT_A_JOIN_TEST` |
| `docs/index.html` | 191,662 bytes | 191,883 bytes |
| Tests | 186 | 189 |

## Not verified

- **The page in a browser.** As in `review/j2.md`: the tests read the template text and the JSON; the dot-or-`n/a` branch is JavaScript and was not rendered here. The expression is a ternary on `r[4]==="join"` in the same template literal that already drew the dot.
- **The recompute** was not rerun; nothing it compares was touched.

## Open

- **The last bar is 0.0 for August 2026** (every member priced, no forward return possible). It is what the coverage check writes for the window's last month; the panel now says which month it is, and whether that month should be July's 0.2 is a question for the check, not the page.
- **"n/a" sits where the dot was**, in the series cell, rather than in a verdict column of its own. The table has no verdict column; the dot is the verdict. A column would be clearer if the table grows.
- **`CLAUDE.md` says "176 tests"**; the suite is 189.

## Against the plan

- **FIX_PLAN_4 J2 says `gap_years`/`gap_pct` are "December of each year".** The window ends in August 2026, so the current year has no December; the plan's sentence is kept for every complete year and the final year takes its latest month, as J2 already did and this step names and tests.
- **The plan's validation row has `bar` as the fourth element** and nothing after it; the fifth, `kind`, is added so the template can tell a verdict from information without a list of series names in the JavaScript. The schema example carries it.
- **The plan has no card label**; "vs French" was the template's and "join test" is what the value is (`review/j2.md`, finding 2).

## Reviewer reads (max 6, in order)

1. `report/site_template.html` `$("tb_val")` — the one line: dot for `join`, `n/a` for `info`.
2. `src/backtester/site.py` `_validation` — the fifth element and the sort, 12 lines.
3. `src/backtester/report.py` `NOT_A_JOIN_TEST` and its use in `validation_table`.
4. `src/backtester/site.py` `_gap_by_year` — the December guard.
5. `tests/test_site.py` `test_current_year_bar_is_the_latest_month_not_december` — the synthetic partial year and the truncated file.
6. `git diff 7a6f7cb -- docs/index.html` — five lines; the `DATA` line's `validation` is the table above.
