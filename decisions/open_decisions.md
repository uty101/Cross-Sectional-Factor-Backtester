# Open decisions for the owner (2026-09-16, after H1–H4)

Each item blocks a step of `FIX_PLAN_3.md`. Answer by editing the plan or
this file; the next Claude Code session reads both after `git pull`.

**Resolved by FIX_PLAN_3 H1–H3 (2026-09-16):** item 1 below was taken as
option (a). The public-float check (`data/checks/public_float.csv`) and
the identity check (`yf_identity.csv`) are rules; 280 member-months over
11 names are excluded (`price_identity_exclusions.csv`), every
specification is rerun, the recompute matches, and the B/P replication
went from 0.78 to 0.89 against the big-cap HML leg, the RMW one from
0.62 to 0.64. `review/h1.md`–`h4.md` and `decisions/h3_before_after.md`.
Items 2 and 3 stand, renumbered by the plan as H5 (site) and H6–H7
(keys); H5 also needs the `DATA.exclusions` line the plan describes,
which is one number from `price_identity_exclusions.csv` (55 rows).

## 1. Reused yfinance symbols: fix now, or with G6? (resolved: (a), see above)

**What.** G5 found three removed names whose yfinance symbol now
resolves to a different security, with the wrong series overlapping the
membership window so `prices.clean` rule 1 does not catch it
(`decisions/g5_rmw_trough.md`):

| Ticker | Was | Wrong series | Member-months affected | In cap-weighted runs? |
|---|---|---|---|---|
| HAR | Harman International | $5,620 median, 2013-01 on | 50 (2013-01 to 2017-02) | yes, at a $0.4–2.3trn cap |
| EP | El Paso Corporation | $1.68 median, ±50% months | 28 (2010-01 to 2012-04) | no (no cap row) |
| COL | Rockwell Collins | $0.135 median | 76 (2012-08 to 2018-11) | no (no cap row) |

**Effect known so far.** RMW replica vs big-cap RMW 0.62 → 0.64 overall,
2013–15 block 0.42 → 0.60. Equal-weighted reported factors: not
measured (one name in ~50 per decile with ±50% months, for the months
above).

**Options.**
- (a) **Fix now.** Add an `EntityPublicFloat` cross-check as a cleaning
  rule (10-K cover-page float vs price × cover-page shares at fiscal
  year-end; ratio outside [0.1, 10] drops the ticker's series for that
  era), write the flagged list to `data/checks/`, then the F4 procedure:
  rerun every specification with a note suffix, `recompute.full` to
  1e-10, regenerate the report and README. About 30–40 minutes of
  compute; every reported number moves a little.
- (b) **With G6.** Tiingo has the same symbol-reuse problem, so the
  cross-check is needed there anyway; build the rule in G6 and rerun
  once. Until then the validation table shows 0.62 with the trough
  explained in `g5_rmw_trough.md`.

**Recommendation:** (a) if the keys are more than a few days away, (b)
otherwise; either way the cross-check is the same code.

## 2. H5 (was G7) needs `report/site_template.html` — resolved 2026-09-16

The template and `report/site_data_schema.txt` were pasted on
2026-09-16 and committed verbatim (03b9512); FIX_PLAN_4 J2 is built:
`backtester site` writes `docs/index.html` from `reports/results.csv`
(new, written by `report`), `validation.csv`, `exclusions.csv`, the
spec log and the coverage check. Two readings of the plan are
recorded in `site.py`: the "what did not work" bullets come from the
README's section, not `reports/what_did_not_work.md` (that file is the
uninterpreted log; its first five lines are the day-one momentum
reruns), and the schema example's `history` (value) is the plan text's
(quality). One thing still needs the owner: enable GitHub Pages once,
Settings > Pages, source "GitHub Actions"; the workflow is
`.github/workflows/pages.yml`.

## 3. Part A keys (H6 = G6, H7 = G8 and G9)

`uv run backtester secrets` on this machine, 2026-09-16, unchanged since 2026-09-15:

```
SEC_USER_AGENT: missing (Part A step A1)
TIINGO_API_KEY: missing (Part A step A2)
ALPHAVANTAGE_API_KEY: missing (Part A step A3)
ANTHROPIC_API_KEY: missing (Part A step A4)
FB_AGENT_MODEL: missing (Part A step A4)
NASDAQ_DATA_LINK_API_KEY: missing (Part A step A6)
gh auth status: gh not installed (Part A step A5)
```

`SEC_USER_AGENT` has a hard-coded default in `fundamentals.py` and
`shares.py` and does not need a `.env` line; the other five do. G8
(Sharadar) is optional and skipped if A6 is absent.
