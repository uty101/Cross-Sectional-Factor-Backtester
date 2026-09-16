# FIX_PLAN_4.md — Float overrides, stubs, then the site

Follows `FIX_PLAN_3.md`. Same rules as `CLAUDE.md`; `review/<step>.md`
per step. Two files ship with this plan and must be committed before
Step J2 starts:

- `report/site_template.html` — the page. `const DATA = __DATA_JSON__;`
  and two image placeholders `__IMG_DECILES__`, `__IMG_IC__`.
- `report/site_data_schema.txt` — a filled example of the `DATA` object
  with the 2026-09-15 numbers. It is the schema; every key in it must be
  produced by `report.site()`.

---

## Step J1 — Float overrides, exclusion window, stubs, silent duplicates

**Build**
- `data/checks/public_float_overrides.csv`: `ticker, fy, float_date,
  public_float, source_url, note`. Populate for EXC FY2010–2013 from the
  10-K cover text already in `data/raw/edgar/10k/` (the four values in
  `review/h1.md`). `fundamentals.public_float_check` applies an override
  before computing the ratio and records `float_source = override`.
- Exclusion window rule: an exclusion from the float check ends at the
  earlier of 12 months after the float date and the first subsequent
  filing whose count puts the ratio back inside [0.5, 20]. PLD's window
  should collapse to 2011-06 to 2011-08.
- Refetch AVB and EA under a fresh as-of date; both must have full
  daily history to their removal in 2026-08. If yfinance still returns
  a stub, log it in `price_fetch_missing.csv` with the row count and
  leave them in the gap.
- `speclog.log_specification`: when it returns an existing row, print
  one line `duplicate: <key> at <commit> already logged, returning it`.
- Rerun every specification (`note = post-J1`), `recompute.full`,
  regenerate `results.md`, validation, charts, README, `answer.md`.

**Test**
- `tests/test_public_float.py`: an override replaces the XBRL float; a
  window ends at the next in-band filing.
- `tests/test_speclog.py`: the duplicate message is printed.

**Done when** EXC has no exclusion rows, PLD's is 3 months or fewer,
AVB and EA either have history or a logged reason, and
`decisions/j1_before_after.md` is generated.

## Step J2 — Results site

**Build**
- `report.site()`:
  - Builds `DATA` with every key in `report/site_data_schema.txt`:
    `window, universe, last_run, n_specs, n_candidates, recompute,
    answer, factors[], cost_bps, cost_curve, horizons, ic_decay,
    attribution, variant_cols, variants, validation, gap_years, gap_pct,
    gap_note, exclusions, wdnw, history, links`.
  - `answer` is the text of `reports/answer.md`.
  - `factors[].dsr` is DSR (all). `factors[].val` is `pass`, `fail`, or
    `n/a` from `validation.csv` for the factor's own join-test row.
  - `validation` is every row of `validation.csv` including the two
    "not a join test" composites, with `bar` as the fourth element.
  - `gap_years`/`gap_pct` from `price_coverage_monthly.csv`, December
    of each year; `gap_note` from the results header line.
  - `exclusions`: "<rows> ticker-windows over <n> names excluded by the
    public-float and identity checks (<m> priced member-months); list in
    data/checks/price_identity_exclusions.csv".
  - `wdnw`: first 5 bullets of `reports/what_did_not_work.md`.
  - `history`: for the quality base spec key, one point per distinct
    `git_commit` in the log, date and `sharpe_net`; label
    "Quality net Sharpe across code versions".
  - `links`: repo URL, `methodology.pdf`, `results.md`.
  - Writes `docs/index.html` by substituting `__DATA_JSON__`
    (`json.dumps`, no HTML escaping issues since it sits in a script
    tag; escape `</` as `<\/`) and the two chart PNGs as base64 JPEG at
    width 1000, quality 78. Copies `methodology.pdf` and `results.md`
    into `docs/`.
- CLI: `backtester site`.
- Dagster asset `site`, downstream of `figures` and `validation`,
  blocked when any check failed.
- `.github/workflows/pages.yml`: on push to `main`, upload `docs/` and
  deploy to GitHub Pages (`actions/upload-pages-artifact`,
  `actions/deploy-pages`). Owner enables Pages in Settings, source
  "GitHub Actions", once.
- README status line at the top: the Pages URL.

**Test**
- `tests/test_site.py`: every factor in `results.csv` is in
  `DATA.factors`; every key in the schema is present; no `__` placeholder
  remains; every number in `answer.md` appears in `DATA`; file under
  400 KB; the JSON parses back.

**Done when** `docs/index.html` opens from disk with the current numbers,
the Pages workflow is green, and changing `cost_bp_base` in
`config.toml` then `backtester run && backtester report && backtester
site` changes the page with no manual edit.

## Step J3 — H6 to H7 (keys)

Unchanged from `FIX_PLAN_3.md`. Do not start until `uv run backtester
secrets` shows the required lines as `set`.

---

## Definitions that stand

- A float-check exclusion ends at the next in-band filing or 12 months,
  whichever is first. An override with a filing URL replaces the XBRL
  float.
- Everything in `FIX_PLAN_3.md`'s definitions.
