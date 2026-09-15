# Open decisions for the owner (2026-09-15, after G1–G5)

Each item blocks a step of `FIX_PLAN_2.md`. Answer by editing the plan or
this file; the next Claude Code session reads both after `git pull`.

## 1. Reused yfinance symbols: fix now, or with G6?

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

## 2. G7 needs `report/site_template.html`

The plan says "from the file supplied on 2026-09-15". It is not in the
repo, not in any commit, and not on this machine; `FIX_PLAN.md` has no
F10 section describing it either. Push the template (or say to build the
page from scratch) and G7 can run without any key.

## 3. Part A keys (G6, G8, G9)

`uv run backtester secrets` on this machine, 2026-09-15:

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
