# BUILD_PLAN.md against the repo as it stands — 2026-09-14

`BUILD_PLAN.md` was written for an empty repository. This file maps every
step of it to what already exists, so the plan can be worked as a delta
rather than a rebuild. Status codes:

- **done** — built, tested, and in `git log`; the name differs from the plan
- **adapt** — built; the plan asks for a specific addition on top
- **new** — not built
- **decline** — conflicts with a documented, validated decision; see §2

Names on the right are the repo's. Package is `backtester`, config is
`config.toml`, evidence lives in `data/checks/` (the plan's `manifests/`),
and this directory is the plan's `decisions/`.

## 1. Step by step

| Step | Plan asks for | Status | Where it is / what is missing |
|---|---|---|---|
| 0.1 | skeleton, Makefile, pre-commit | done | `pyproject.toml` (uv, Python 3.12 pinned), `Makefile`; no pre-commit config; no `make` on this laptop (CLAUDE.md) |
| 0.2 | config loader, `config_hash` | adapt | `config.py` frozen `Config`, `with_()`; **no `config_hash`** |
| 0.3 | spec log with `config_hash, git_commit, config_json` | done 2026-09-14 | `portfolio.log_specification` writes 16 columns, N = row count (74); **no hash / commit columns**. N stays the row count: a rerun of the same config is still a trial |
| 0.4 | README build status | new | trivial once the plan is adopted |
| 1.1 | Wikipedia fetch + parse, manifest | done | `universe.fetch/parse_constituents/parse_changes`; `data/raw/manifest.json` |
| 1.2 | membership intervals, aliases, monthly | done | `universe.build_membership`, `data/checks/ticker_renames.csv`, 4 evidenced overrides; monthly counts 496–504 |
| 1.3 | 20-row spot check with press-release URLs | done | `data/checks/membership_spotcheck.csv`, `test_universe.py` |
| 2.1 | yfinance + Stooq dual source | adapt | yfinance built, retried, manifest; **Stooq is behind a JS wall as of 2026-09** (README). Second source would need a different provider |
| 2.2 | reconcile, gap report | adapt | gap report done (`price_coverage_*.csv`, 14.6%); **no cross-source reconcile** because there is one source |
| 2.3 | market cap | done | `fundamentals.market_caps`, SEC shares from the start (plan's 4.8 already applied) |
| 3.1 | signal schema, restrict to universe | done | `signals.SIGNAL_SCHEMA`, `run.member_panel` inner join |
| 3.2 | momentum 12-1 with lookahead test | done | `signals.momentum_12_1`, `test_momentum_skips_most_recent_month` |
| 3.3 | winsorise, sector z | done | `signals.normalise` |
| 3.4 | deciles, weights, drift, turnover, lag | done | `portfolio.*`, invariants 4 and 6 tested |
| 3.5 | IC, perf, break-even, cost curve | done | `stats.ic_series/ic_summary/sharpe/max_drawdown/breakeven_cost/sharpe_by_cost` |
| 3.6 | French factors, AQR BAB | done 2026-09-14 | `benchmarks.parse_aqr_bab`, `data/interim/aqr_bab.parquet`, USA column |
| 3.7 | end-to-end run, UMD > 0.70 | done | 0.79 (0.85 no-sector); `run.run_factor`, `cli` |
| 4.1 | SEC zips, manifest, rate limit | done | `fundamentals.fetch`, 70 zips |
| 4.2 | DuckDB load | done | `fundamentals.ingest_quarter` (DuckDB `read_csv`), cached to parquet rather than a persistent `.duckdb` |
| 4.3 | originals only, `prevrpt = 0` | decline | see §2.2 |
| 4.4 | tag map + coverage ≥ 0.90 | done | `tag_map.toml` 16 concepts, `data/checks/tag_coverage.csv`. Coverage is **below 0.90 before 2013** and documented as a data limit, not fixed by tag additions |
| 4.5 | TTM from 10-Qs | done 2026-09-14 | `fundamentals.ttm`, `_ttm` panel columns, `value_ttm`/`quality_ttm` logged; moves nothing measurable, reported factors keep annual |
| 4.6 | as-of join, THE test in README, `company_tickers.json` | done 2026-09-14 | `asof_join`, `test_asof_join_excludes_filing_after_signal_date`, README leads with it. CIK map is Wikipedia + name match (`sectors.cik_map`); `company_tickers.json` is the primary source for current members (500/500, no disagreements); removed names keep the name match because the SEC map is today's snapshot |
| 4.7 | SIC → 11 sectors | done | `sectors.py`, 84.5% GICS agreement logged |
| 4.8 | SEC shares for cap | done | from the start |
| 5.1–5.4 | value, quality, low vol, beta, composite | done | `run.FACTORS`; `beta_252` exists, not validated against BAB |
| 5.5 | sector-neutral on, `filed + buffer <= t` assertion in normalise | done 2026-09-14 | sector-neutral on; the assertion lives in `asof_join` tests, **not as a runtime guard in `normalise`** |
| 6.1–6.2 | full grid, cost curves | done | `run.run_all`, `sensitivities`, `stats.sharpe_by_cost` |
| 6.3 | momentum regression baseline | done 2026-09-14 | `tests/fixtures/momentum_baseline.json` = 0.7934; `test_regression.py` within 0.05 and above 0.70 |
| 7.1–7.5 | FM, NW, decay, DSR, attribution | done | `stats.py`; NW cross-checked against statsmodels in tests; DSR worked example |
| 7.6 | wire into results | done | `report.py` tables |
| 8.1 | validation table with thresholds file | done 2026-09-14 | `config.toml [validation]`, `run.validation_table` -> `reports/validation.csv`; beta vs BAB 0.42 (fail, reported) |
| 8.2 | delisting sensitivity `drop` / `terminal −30%` | done 2026-09-14 | `prices.terminal_returns`, `backtester delisting`, variant column in results.md; nine names, ≤ 0.01 Sharpe |
| 8.3 | weighting gap on SMB | done 2026-09-14 | `stats.weighting_gap`, `reports/weighting_gap.csv`; R² ≤ 0.035 |
| 8.4 | what-did-not-work generated from spec log + git log | done 2026-09-14 | `research_log.py`, `backtester research-log`; README keeps the interpretation |
| 9.1 | four charts, USREC shading | done 2026-09-14 | FRED USREC fetched/parsed; `report.recession_spans` reads every NBER span in the window, hard-coded 2020 is the fallback |
| 9.2 | README regenerated from a template | decline | see §2.4 |
| 9.3 | methodology PDF via pandoc | done | `methodology.py` via fpdf2; no pandoc on this machine |
| 10.1, 10.2, 10.5 | Dagster assets, schedules, asset checks | done 2026-09-14 | `backtester.orchestration.definitions`: 20 assets, 5 checks (all green on the current data; validation reported as WARN), 4 schedules. Path is `src/backtester/orchestration/`, not `orchestration/` (ruling 3) |
| 10.3 | incremental compute | declined | every factor recomputes in under a minute; one code path keeps 10.4 honest. Owner can overrule |
| 10.4 | full recompute check | new | needs the `asof_join` tie fix in §5 first |
| 11.1–11.2 | harness, research-log agent | done 2026-09-14 | `agents/base.py`, `agents/tools.py`, `agents/research_log.py`; **no real logged run yet: no API key or gh on this machine** |
| 11.3–11.7 | reporting, tag-map, triage, universe-change, drift agents | done 2026-09-14 | one module each under `agents/`, wiring tests on a scripted model; the 4σ detector found the thin-month defect on first use; no live runs (no API key on this machine) |
| 11.8 | sensors + CI | done 2026-09-14 | four Dagster sensors route results/success/failure/4σ to the agent jobs; `.github/workflows/ci.yml` runs the gate, the tag-map guard (`scripts/check_tag_map.py`) and the spot-check |
| — | 10-K text factor, invariant 10 | done, not in plan | `text.py`, added 2026-09-14 |

## 2. Where the plan and the repo disagree

These are not naming differences. Each is a decision the repo made,
tested, and wrote down; the plan asks for the opposite. **The owner ruled
on all four on 2026-09-14: the recommendations below stand** (recorded at
the top of `BUILD_PLAN.md`).

### 2.1 Cost convention (Appendix: "Net return = gross − cost × turnover")

The repo charges `ret_net = ret_gross − 2c × turnover`, deliberately.
With turnover defined as ½ Σ|Δw|, the plan's formula charges c on half
the dollars traded; the README's "What did not work" names this as the
brief's error and quotes every break-even under the stricter form. The
appendix says this must not change. Switching would raise every net
Sharpe and every break-even in the README, and the deflated Sharpe would
be computed over a spec log whose `sharpe_net` column mixes the two.
**Recommendation: keep `2c`, amend the appendix.**

### 2.2 `prevrpt = 0` (step 4.3)

In the FSDS, `prevrpt = 1` marks a filing that was *later* amended. A
filter of `prevrpt = 0` together with excluding `/A` forms drops both the
original and the amendment, so a restated period has no value at all —
and, worse, it uses knowledge of the future (that an amendment would
come) to decide what the past could see. That is a lookahead. The repo's
rule is first-filed wins (invariant 2, `test_first_filed_value_beats_later_amendment`),
which keeps the original. **Recommendation: do not apply; the plan's
docstring intent ("the first-filed value is used") is already the rule.**

### 2.3 Rename to `factor_backtester`, YAML config, Python 3.11

Pure churn: 17 modules, 79 tests, CLAUDE.md, README, and the spec log's
`config_json`-equivalent all reference `backtester` and `config.toml`.
Python is pinned to 3.12 and the lockfile is the environment.
**Recommendation: keep the names; read the plan's paths as the repo's.**

### 2.4 README regenerated from a template (step 9.2)

The repo's stated rule is that `results.md` is generated and the README
is pasted from it by hand "so that the numbers are looked at before they
are published"; today's session found a DSR that moved 0.15 → 0.14
precisely because of that step. A generated README is fine if the diff
is reviewed; the check that the README table equals `results.md` can be
a test instead. **Recommendation: add the equality test, keep the paste.**

## 3. What is genuinely new, in the order it should be built

Each is one plan step, gated, committed, pushed, per the plan's rule 1.

1. **0.2/0.3** — `config_hash` and `git_commit` columns on the spec log
   (append to the existing 16; N stays the row count).
1a. **11.1** — the agent harness (owner's ruling 5: sooner).
1b. **11.2** — the research-log agent, on the spec log and git log.
2. **4.5** — TTM flows from 10-Qs; value and quality get `_ttm` variants
   as logged sensitivities, the reported factors unchanged unless the
   owner says so.
3. **4.6** — `company_tickers.json` as the primary CIK map, name match
   as fallback, agreement logged in `data/checks/cik_map.csv`.
4. **5.5** — runtime guard in `normalise`: any frame carrying `filed`
   must satisfy `filed + buffer <= month`.
5. **6.3** — stored momentum baseline and a regression test.
6. **3.6/8.1** — AQR BAB and the `beta_252` validation row;
   `validation` thresholds moved into `config.toml`.
7. **8.2** — delisting `terminal` mode (−30% on the last print).
8. **8.3** — weighting gap regression on SMB.
9. **8.4** — generated `what_did_not_work.md` from the spec log and git log.
10. **9.1** — FRED `USREC` recession shading.
11. **2.1** — a second price source, once one that serves a script is
    found (Stooq does not).
12. **10.x** — Dagster.
13. **11.x** — agents.

## 4. Plan rules that already hold, for the record

Rules 2–9 map to invariants 9, DuckDB-only ingest, `as_of` stamping
(named `as_of`, not `asof_date`), invariant 7, invariant 1, invariant 8,
tests-first, polars-first. Rule 1 (one step per session, show the test
output, stop) is adopted from here on.

## 5. Observations for later phases

- `asof_join` picks nondeterministically between two filings of the same
  CIK with the same availability date (unstable sort on `available`). It
  moved one name's market cap in two months of 2018 on a rebuild. Harmless
  now; phase 10.4's full-recompute check will need it fixed first.
