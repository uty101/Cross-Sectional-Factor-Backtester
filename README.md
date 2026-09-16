# Cross-Sectional Factor Backtester

Point-in-time equity factor research for US large caps, 2010–2026, with
costs, signal decay and overfitting control.

> **Status: built and run.** Every number below comes from
> `reports/results.md`, which `uv run backtester report` writes from saved
> runs and the specification log; nothing is typed from memory. The brief
> is [here](Project%20Outline/01_Factor_Backtester.docx).

## The test that matters

```python
def test_asof_join_excludes_filing_after_signal_date() -> None:
    # A 10-K for FY2019 filed on 2020-02-29 (the month-end itself) and a
    # 10-K for FY2018 filed a year earlier.
    v = _values(
        (1, date(2018, 12, 31), date(2019, 2, 20), 100.0),
        (1, date(2019, 12, 31), date(2020, 2, 29), 200.0),
    )
    out = fx.asof_join(_panel(), v, buffer_days=1).sort("month")
    got = dict(zip(out["month"], out["value"], strict=True))
    assert got[date(2020, 1, 31)] == 100.0  # only FY2018 exists
    assert got[date(2020, 2, 29)] == 100.0  # filed today: NOT available yet
    assert got[date(2020, 3, 31)] == 200.0  # filed 02-29 + 1 day <= 03-31
```

[tests/test_fundamentals.py](tests/test_fundamentals.py). Every fundamental
used at month-end *t* was **filed** on or before *t − 1 day*, joined as-of
filing date, never keyed on period end; the first-filed value wins over
later amendments (`test_first_filed_value_beats_later_amendment`); an
amendment for an older period arriving after a newer filing is ignored.
These are three of nine invariants in [CLAUDE.md](CLAUDE.md), each with a
test written before the code it guards.

## What this is

A monthly-rebalanced factor backtester that treats **data honesty as the
deliverable, not the returns**. It takes point-in-time fundamentals from SEC
filings, a reconstructed historical universe, and daily prices, and produces
decile and long–short portfolios for value, momentum, quality and low
volatility, with costs, turnover and statistical tests on top. The engine
takes any `(month, ticker, z)` frame, so a new signal is a dictionary entry.

## The question

Do value, momentum, quality and low volatility earn a premium on a universe an
outsider can verify, over 2010–2026?

- How much paper return survives turnover, spreads and a 1-day execution lag?
- How fast does each signal decay, and what rebalance frequency follows?
- How much of the result is multiple-testing luck, once N is counted honestly?

**The answer** ([reports/answer.md](reports/answer.md); every number in it
is in a table on this page or in [reports/results.md](reports/results.md)):

Nothing survives. At 10 bp one-way, no factor clears the deflated Sharpe: the highest is quality's 0.38 against the 8 candidate specifications and 0.06 against all 61, on a net Sharpe of 0.22, an IC t-stat of 1.2, and 69% of non-financial members. The largest correction was the market cap: split-adjusted prices met unadjusted share counts, and value reported a 4.7% alpha after HML and a 0.48 net Sharpe; with the count in the price basis it is −1.8% and −0.19. The data cannot say what the 14.6% of member-months without a price history earned; they are disproportionately names that left the index, so every series here is the survivors' until a delisting source is added.

## Results

The table is what the five factors the brief asked for earned over 2010-01
to 2026-08 (200 monthly formations) as equal-weighted long–short deciles,
signals z-scored within sector, 1-day execution lag, **10 bp one-way cost
on every dollar bought or sold**. Read the DSR (cand.) and Coverage
columns first: one says how much of each Sharpe is selection, the other
how much of the index the signal exists for. No line clears either the
deflated Sharpe or an IC t-stat of 1.96; quality is the closest on both.

| Factor | Gross ann. | Net ann. | Vol | Sharpe (net) | DSR (all) | DSR (cand.) | Max DD | Turnover | Mean IC | IC t-stat | Break-even cost | Coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Momentum 12-1 | 2.7% | 1.2% | 15.6% | 0.08 | 0.02 | 0.19 | −56% | 0.62 | 0.006 | 0.5 | 18 bp | 87% |
| Value (B/P, E/P) | −1.3% | −2.0% | 11.0% | −0.19 | 0.00 | 0.03 | −50% | 0.30 | −0.004 | −0.5 | none (loses gross) | 84% |
| Quality (GP/A, accruals) | 2.5% | 1.9% | 8.8% | 0.22 | 0.06 | 0.38 | −24% | 0.25 | 0.007 | 1.2 | 42 bp | 69% of non-fin.¹ |
| Low volatility | −4.2% | −4.8% | 18.8% | −0.26 | 0.00 | 0.01 | −74% | 0.24 | 0.002 | 0.1 | none (loses gross) | 87% |
| Composite | −3.3% | −4.4% | 14.3% | −0.31 | 0.00 | 0.01 | −65% | 0.45 | −0.002 | −0.2 | none (loses gross) | 52% |

¹ Quality is computed on 69% of non-financial members in a typical month: gross profitability needs a cost-of-goods line and the rest do not tag one (decisions/tag_coverage_f3.md); financials are excluded by rule, as in Novy-Marx. Coverage is the median across months of the share of members with a signal.

Price history covers 85.4% of member-months; the missing names are
disproportionately those that left the index. See Data.

**DSR** is the deflated Sharpe of Bailey and López de Prado: the probability
that the net Sharpe exceeds the expected maximum of *N* random trials with
the same dispersion, adjusted for skew and kurtosis. *N* is read from
[reports/specifications.csv](reports/specifications.csv), where every run is
logged (388 rows). A trial is a distinct specification key: factor,
signal, weighting, cost, lag, holding period, winsorisation, deciles,
sector flag, window and variant (`spec_key` in the log); re-running one
after a code fix is the same trial, so the 192 reruns after the data
fixes of September 2026 are not new trials. **DSR (all)** counts the 61
distinct specifications (base, sensitivity, diagnostic, the two broken
first attempts at momentum); **DSR (cand.)** counts the 8 whose `kind`
is `candidate`, a specification that could have been reported, rather
than a sensitivity, a replication or a diagnostic
([decisions/g2_trial_count.md](decisions/g2_trial_count.md) has every
DSR before and after this definition). **Break-even
cost** is the one-way cost at which the mean net return is zero.

**These are the numbers after the data fixes** ([FIX_PLAN.md](FIX_PLAN.md)
F1–F3, [decisions/f4_before_after.md](decisions/f4_before_after.md); the
price-identity exclusions of [FIX_PLAN_3.md](FIX_PLAN_3.md) H1–H3,
[decisions/h3_before_after.md](decisions/h3_before_after.md)). The
previous README reported value at a net Sharpe of 0.48 with a 4.7% alpha
(t 2.3) after HML, and called it the factor that worked. It was not. The
market caps behind B/P and E/P met a split-adjusted yfinance price with an
unadjusted SEC share count, so every name that later split (Chipotle
50-for-1, Deckers 6-for-1, Super Micro 10-for-1) carried a cap 6 to 50
times too small for its whole pre-split history, a book-to-price 6 to 50
times too large, and sat in the value long leg. Those are the decade's
winners. The "value alpha" was a momentum position that a $1bn size floor
had been quietly trimming rather than diagnosing. With the count in the
price basis the factor loads 0.42 on HML (t 7.7, R² 0.52, alpha −1.8%,
t −0.9), correlates 0.55 with HML instead of 0.25, and earns what large-cap
value earned over 2010–2026: nothing.

| Value (B/P, E/P), sector-neutral | before F2 (unadjusted count) | after F2 (count in the price basis) |
|---|---|---|
| Net Sharpe | 0.48 | −0.19 |
| Alpha after Mkt-RF, HML, UMD, RMW (t) | 4.7% (2.3) | −1.8% (−0.9) |
| Loading on HML (t) | 0.10 | 0.42 (7.7) |
| Correlation with HML | 0.25 | 0.55 |

The before column is the previous README as quoted in
[decisions/f4_before_after.md](decisions/f4_before_after.md); the after
column is the attribution and validation tables in
[reports/results.md](reports/results.md).

What the table says, factor by factor:

- **Momentum** is UMD (β 0.90, t 15.9, R² 0.67) and UMD earned nothing in
  this window. Turnover of 0.62 a month puts its break-even at 18 bp.
  Holding for 3–12 months instead of 1 raises the net Sharpe to 0.18–0.25
  by cutting turnover, at the price of tracking UMD less closely.
  Cap-weighted it is 0.19.
- **Value** loses 2.0% a year net. Sector-neutral B/P and E/P on S&P 500
  names is a large-cap HML position (loading 0.42) and HML was flat to
  negative over most of the window. Cap-weighted −0.45; on the 129 months
  from 2015-12 where the price gap is under 20%, −0.19 against −0.19 on all
  months, so the missing delisted names are not hiding a premium.
- **Quality** is the only positive line: net Sharpe 0.22, 0.26 cap-weighted,
  0.34 on the well-covered months, Fama-MacBeth t 1.2, DSR 0.38 against the
  8 candidates. Accruals carry it. The Coverage column is the caveat: the signal
  exists for 69% of non-financial members in a typical month, because
  gross profitability needs a cost-of-goods line and the rest do not tag
  one ([decisions/tag_coverage_f3.md](decisions/tag_coverage_f3.md));
  financials are excluded by rule, as Novy-Marx does. A net Sharpe of 0.22 with
  an IC t-stat of 1.2 is not evidence of much.
- **Low volatility** loses 4.2% a year gross as a long–short. Its
  attribution is the brief's prediction: market beta −0.67 (t −11.3) and
  RMW 0.93 (t 8.1), with alpha of 1.1% (t 0.4). It is a short-beta,
  long-profitability position, and shorting beta lost for sixteen years.
  With the rolling market beta hedged out (`portfolio.beta_hedge`,
  estimated only on months before formation) it nets 0.39, and the low
  beta long–short 0.27: what is left once the short-beta drag is removed,
  reported as variants, not headline rows.
- **Composite** (all six signals) nets −0.31, and −0.19 cap-weighted: with
  value and low volatility both negative there is nothing for the
  composite to average.
Four charts, from [reports/figures/](reports/figures/):

![deciles](reports/figures/chart1_deciles.png)
![rolling IC](reports/figures/chart2_rolling_ic.png)
![IC decay](reports/figures/chart3_ic_decay.png)
![Sharpe vs cost](reports/figures/chart4_sharpe_vs_cost.png)

Signal decay: no half-life is printed, because no factor's h=1 IC t-stat
reaches 1.96 and there is no IC to fit a decay to (the chart draws the
points and no curve). Momentum's IC is small at every horizon; quality's
IC at h=12 is as high as at h=1, which is why holding it for 6–12 months
costs nothing in return and saves most of the turnover (though its 3–12
month holds net −0.00–0.22 against 0.22 monthly, the difference being which
calendar months form the portfolio). The full tables, including net Sharpe at 0, 5, 10, 25 and 50 bp,
the cap-weighted and holding-period variants, and the Fama-MacBeth premia,
are in [reports/results.md](reports/results.md).

### Appendix: text factor

The sixth line in earlier versions of this table was the 10-K text
factor. It is not one of the five the brief asked for, so it lives in
[reports/results.md](reports/results.md) under its own heading, with the
same columns:

| Factor | Gross ann. | Net ann. | Vol | Sharpe (net) | DSR (all) | DSR (cand.) | Max DD | Turnover | Mean IC | IC t-stat | Break-even cost | Coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10-K text similarity | 0.2% | −0.5% | 5.5% | −0.09 | 0.00 | 0.06 | −26% | 0.29 | 0.003 | 0.6 | 3 bp | 96% |

**10-K text similarity**, long the names whose annual report changed
  least year on year (Cohen, Malloy and Nguyen's "Lazy Prices"), earns
  nothing here: −0.2% gross, −1.0% net, alpha −0.5% (t −0.4), R² 0.03 on
  the four French factors, so it is at least not a repackaging of them.
  Jaccard instead of cosine gives 0.05 net; every variant is within ±0.3
  of zero. The paper's effect sits in small caps and in the short leg, and
  this is an S&P 500 long-short over 2010–2026. It is in the table because
  the point of building it was the data path (next section), not the return.

## Validation bar

The pipeline is considered wrong until the long–short series clear this:

| Series | Against | Threshold | Result |
|---|---|---|---|
| Momentum long–short | French **UMD** | > 0.7 | **0.80** pass (0.86 without sector neutralisation) |
| B/P, cap-weighted terciles, French's construction | French **HML, big-cap leg** | > 0.6 | **0.89** pass (0.83 vs full HML; 0.85–0.92 in every 3-year block) |
| Pre-tax income / FY equity, cap-weighted terciles, French's construction | French **RMW, big-cap leg** | > 0.6 | **0.64** pass (0.44 vs full RMW) |
| Low beta long–short, raw | AQR **BAB** (US) | > 0.5 | 0.42 fail; a 252-day beta on S&P 500 names against AQR's all-cap, leverage-adjusted factor |
| Low beta long–short, beta-hedged | AQR **BAB** (US) | > 0.5 | 0.46 fail; the raw series carries a market beta of −0.81 and BAB is beta-neutral by construction, so the rolling 36-month beta (estimated on months before formation only) is hedged out first: beta 0.10 after, still short |
| Value and quality long–short, as reported | French **HML** / **RMW** | > 0.7 | 0.55 / 0.07; not a join test: two-signal sector-neutral composites against raw one-signal factors (value was 0.25 before the market-cap fix) |

The first three rows test the fundamentals join. The brief's bar of 0.7 on
the reported value and quality factors stays in the table and is not that
test, because HML and RMW are neither sector-neutral nor composites. The
test of the join is to build French's factor the way French does (one raw
signal, no sector neutralisation, cap-weighted top third minus bottom
third) and compare it with the **big-cap half** of his factor, which he
also publishes, because HML and RMW are half small-cap and this universe
has none (French's own big-cap leg correlates only 0.92 with full HML over
the window). `reports/validation.csv` carries every row above, pass or
fail, from `config.toml [validation]`.

| Replication | vs full factor | vs big-cap leg | from 2016 |
|---|---|---|---|
| B/P, cap-weighted terciles | 0.83 | **0.89** | **0.89** |
| Pre-tax income / FY book equity, cap-weighted terciles | 0.44 | 0.64 | 0.64 |

Both joins clear the 0.6 bar against the like-for-like series. The B/P
replication read 0.78 over the window and 0.90 from 2016 until the
price-identity exclusions ([FIX_PLAN_3.md](FIX_PLAN_3.md)): the early
years were carrying a $0.4–2.3trn Harman International, the wrong series
under a reused symbol in a cap-weighted tercile, and it now reads
0.85–0.92 in every 3-year block. The profitability one was 0.07 in
2010–12 before the CIK fix, rising with XBRL coverage; after it, 0.69 in
2010–12, 0.38 in 2013–15, 0.83 in 2016–18, 0.62 in 2019–21 and 0.61 from
2022, and the 2013–15 trough was the same symbol
([decisions/g5_rmw_trough.md](decisions/g5_rmw_trough.md)); with the
exclusions it is 0.68, 0.59, 0.83, 0.63 and 0.61. The early weakness was
the ticker-to-CIK map (18% of members had no filings attached,
[decisions/cik_audit.md](decisions/cik_audit.md)), not XBRL coverage; the
2013–15 block is still the lowest and the rest of that gap is reported,
not tuned.

## Data

| Need | Source | Note |
|---|---|---|
| Universe history | Wikipedia constituents + changes tables | Membership intervals per ticker; cross-checked month by month against the [fja05680/sp500](https://github.com/fja05680/sp500) daily list, 98.4% agreement |
| Fundamentals | SEC Financial Statement Data Sets | 70 quarterly zips 2009q1–2026q2; **filing date is the key**; 19 concepts via an ordered tag map that only grows; a ticker maps to a CIK per era ([data/checks/cik_overrides.csv](data/checks/cik_overrides.csv)) |
| Shares outstanding | SEC companyconcept API; yfinance split events | The cover-page count (FSDS `num.txt` does not carry it), then the balance-sheet count, then the diluted weighted average, each **scaled by every split after its filing date** so it meets yfinance's split-adjusted close; a plausibility guard drops the filings in thousands ([decisions/f2_shares.md](decisions/f2_shares.md)) |
| Prices | yfinance | Stooq is behind a JavaScript wall as of 2026-09. Delisted names are absent: **14.6% of universe-months**, 31% in 2010 falling to 0%. Every price is checked against the filer's own market value (the 10-K's `EntityPublicFloat`) and every removed name's symbol against what yfinance says it is now: 280 member-months over 11 names are excluded ([data/checks/price_identity_exclusions.csv](data/checks/price_identity_exclusions.csv)) |
| Sector map | SIC from the filings | 11 GICS-like buckets by hand; 84.5% agreement with Wikipedia's GICS on current members |
| Benchmarks | Ken French data library | Mkt, SMB, HML, RMW, CMA, UMD, and the six size × B/M and size × OP portfolios for the big-cap legs |
| Risk-free | French RF; FRED DGS1MO kept | Long–short spreads need none |
| 10-K text | EDGAR primary documents, indexed from the FSDS `sub.txt` | One gzip per original 10-K; **filing date is the SEC's**; scored by cosine/Jaccard against the prior year's filing (Cohen, Malloy and Nguyen 2020). Not company websites: no timestamp, restatements overwrite in place, delisted names vanish. Not transcripts: not filed, no point-in-time archive without a vendor. No language model: a model trained after the filing knows the outcome (invariant 10) |

**Known limitations, stated up front.** The S&P 500 restriction is a
compromise forced by free data: 496–504 names at every month-end and 818
unique names over the window (the brief's ~1,100 was high). Survivorship in
the *universe* is handled by reconstructing membership month by month; the
*prices* of names that were acquired or failed are largely missing from
yfinance, and that is the survivorship that remains: the "with and without"
table in `results.md` gives every factor on the 129 months from 2015-12
where the price gap is under 20%: value −0.19 against −0.19 on all months,
quality 0.34 against 0.22, momentum −0.06 against 0.08. Total assets cover
98% of members from 2011 and a market cap 97% of the members with a price;
the cap-weighted runs hold 39% of members in 2010 and 86% in 2023 because
the rest have no price. A Russell 3000 version needs paid coverage of
delisted names and their filings.

Every hand-verified thing lives in [data/checks/](data/checks/README.md)
with its evidence in the row.

The thresholds live in `config.toml [validation]` and every row above is
recomputed into [reports/validation.csv](reports/validation.csv) by
`backtester report`, pass or fail.

The equal-versus-cap-weighted gap is not a size bet: regressed on SMB
(BUILD_PLAN 8.3, [reports/weighting_gap.csv](reports/weighting_gap.csv))
the R² is 0.035 for quality and under 0.012 for every other factor. In
an all-large-cap universe, weighting changes which large names dominate,
not the size exposure.

## What did not work

Kept as a first-class section, per the brief. The interpretation is
below; the facts behind it are generated: `backtester research-log`
writes [reports/what_did_not_work.md](reports/what_did_not_work.md), one
line per superseded or abandoned specification with the commit that
replaced it (36 of 74 as of 2026-09-14), and the research-log agent adds
what each of those commits changed, from its body, below a marker.

- **Wikipedia's `Date added` column is not an index-addition date for
  long-standing members.** Sempra "2017", T. Rowe Price "2019", Dominion
  "2016", Humana "2012", Freeport "2011", Johnson Controls "2010": all are
  corporate-event dates on names in the index since the 1990s, and every
  Wikipedia-derived dataset repeats them. Trusted only before 2010; in-window
  it is adjudicated by the cross-check and each decision logged.
- **The changes table cannot express share-class events.** Google's 2014
  class C distribution is "GOOGL added" with no removal, so a backwards walk
  loses Google before 2014. Names added under one ticker and removed under
  another (UA→UAA, KORS→CPRI, JOYG→JOY) fall to an unknown start. Four
  override rows with evidence; the walk was not made cleverer.
- **Stooq no longer serves data to a script**, so the delisted names the
  brief hoped to recover from it are simply absent. yfinance is worse than
  absent for them: it stitches the acquired company's history onto whatever
  penny stock later reused the symbol (BEAM is Beam Therapeutics; 43 tickers
  dropped), prints TIE at 11,700 on a 2011 month-end (413 bad prints
  dropped), and returns a corrupt series for five names. Three logged
  cleaning rules, on price ratios rather than signed returns because a fall
  can never exceed −100%.
- **Three cleaning rules cannot see a reused symbol whose new series
  overlaps the membership.** yfinance's `HAR` is a fund quoted at
  $5,000–$34,000 from 2013, which against Harman's 68m shares is a
  $0.4–2.3trn market cap sitting in the short tercile of the RMW
  replication; `GR` is another company at $4, `COL` at $0.13, `EP` is
  Empire Petroleum, `GENZ` is at half Genzyme's price. Found by hand in
  the RMW trough ([decisions/g5_rmw_trough.md](decisions/g5_rmw_trough.md))
  and turned into two rules ([FIX_PLAN_3.md](FIX_PLAN_3.md)): the
  pipeline's cap at the 10-K's float date over the filer's own
  `EntityPublicFloat` must lie in [0.5, 20], and a removed name's series
  must sit at that filer's price and under a symbol yfinance still
  attributes to it. 280 member-months over 11 names are excluded; every
  flagged row is in `data/checks/public_float.csv` and
  `yf_identity.csv`. Two things the rules taught: 49 of the 62 float
  flags are the filer's own float filed in thousands or billions (GE's
  FY2011 float is $201.5m), with the pipeline right, so those are named
  and not excluded; and Yahoo files every delisted symbol under the same
  placeholder code, so what a symbol trades as now says nothing about
  whose history it carries, and only the price level does. The B/P
  replication went from 0.78 to 0.89 against the big-cap HML leg
  ([decisions/h3_before_after.md](decisions/h3_before_after.md)).
- **The first momentum run correlated 0.04 with UMD.** Uncleaned prices
  (above) and a validation join that compared the formation month with the
  same month's UMD, when the return is earned the month after. Both runs
  are in the specification log.
- **Wikipedia's CIK for ExxonMobil is a 2026 entity with no filings.** A
  constituents CIK with no history falls back to the company name.
- **The SEC's own ticker map is a snapshot of today, and applied to a
  removed name it gives you today's holder of the symbol.** Adding
  `company_tickers.json` as the primary CIK source (BUILD_PLAN 4.6)
  first re-pointed twelve removed names: S to SentinelOne instead of
  Sprint, DV to DoubleVerify instead of DeVry, TMC to The Metals Company
  instead of Times Mirror. It now applies to current members only,
  500 of 500, all agreeing with Wikipedia's CIK, and removed names keep
  the name match. Every method is in `data/checks/cik_map.csv`.
- **The market caps were wrong by the split ratio, and the value premium
  was that.** yfinance's close is split-adjusted and an SEC share count
  is not, so every name that later split carried a cap too small by the
  ratio for its whole pre-split history; a $1bn floor trimmed the worst
  of it and was read as a units error (RTX, CMG). Fixed in
  [decisions/f2_shares.md](decisions/f2_shares.md): the cover-page count
  from the SEC API, scaled by every split after its filing date, with a
  plausibility guard for the filings that report counts in thousands
  (Garmin, EchoStar) and the merger shells that report 1 share. Value
  went from 0.48 to −0.16 net and from 0.25 to 0.56 correlated with HML.
- **The ticker-to-CIK map left 18% of members without filings.** Removed
  names whose SEC name carries a suffix (`AETNA INC /PA/`) or collides
  with a second registrant (`ALCOA`), and current names whose
  `company_tickers.json` CIK is a successor entity (Disney 2019,
  BlackRock 2024) or an acquirer that took the symbol (CB, JCI). 93
  hand-verified rows in `data/checks/cik_overrides.csv`, a CIK per era,
  resolved per month; total assets went from 87–91% to 98% of members
  ([decisions/cik_audit.md](decisions/cik_audit.md)).
- **`OperatingIncomeLoss` is not reported by banks or insurers**, which
  left profitability without financials and its French replication at 0.31.
  Pre-tax income over fiscal-year book equity is the closest reported
  line and lifted it to 0.48 against the big-cap leg, and the CIK fix to
  0.62; the early years were the map, not the coverage.
- **Value and quality do not validate against HML and RMW as reported**, and
  the fix was not to change the reported factors until they did; it was to
  replicate French separately and say which half of the gap is
  construction and which half is data.
- **The brief's cost formula charges half the cost.** `r_net = r_gross −
  c·TO` with `TO = ½Σ|Δw|` and `c` one-way charges c per unit of two-way
  volume. Here every dollar bought and sold pays c: `r_net = r_gross −
  2c·TO`. Break-evens are quoted under that stricter convention.
- **The 10-K text factor is flat, and the question that led to it was
  answered on the way.** Asked whether company websites, transcripts and
  annual reports would be a richer source than SEC filings: no, for the
  backtest. A website has no filing timestamp (invariant 1), a restated
  PDF overwrites the original in place (invariant 2), a delisted member's
  site is gone (invariant 3), and transcripts are not filed at all. The
  text comes from EDGAR, one primary document per original 10-K (10,339
  of 10,339 in the index; one was re-numbered by EDGAR and found by form
  and filing date), and is scored by two deterministic similarities. A
  language-model score was ruled out and made invariant 10: a model
  trained after the filing knows what happened next, and no test on the
  timestamps would catch it. Item 1A / Item 7 extraction and the 8-K
  earnings release are the next steps if the text route is pursued.
- **Trailing-twelve-month flows from 10-Qs change nothing you can see.**
  Built as BUILD_PLAN step 4.5 (`fundamentals.ttm`: YTD + last annual −
  prior-year YTD, stamped with the latest of the three filing dates) and
  run as logged sensitivities: after the data fixes, value with TTM
  earnings yield nets −0.22 against −0.19 annual and correlates 0.57
  with HML against 0.55; quality with TTM gross profit and accruals nets
  −0.02 against 0.22 and correlates 0.08 with RMW against 0.07. The
  reported factors keep the annual convention.
- **The first month of the window had fifteen names, and one of them was a
  factor return.** Fundamentals arrive with the FY2009 10-Ks in February
  and March 2010, so January 2010 had 15–23 names with a value or quality
  signal and value's +5.5% that month was one long against two shorts; the
  text factor's first four months had two to five names and printed +18%
  on one stock. The 4σ anomaly detector built for the triage agent
  (BUILD_PLAN 11.5) surfaced it. `config.toml [portfolio] min_names = 50`
  now forms no portfolio in a month thinner than that; every affected
  specification was re-run and logged, and the DSRs in the table fell
  with N as they should.
- **The full recompute found the pipeline was not deterministic, twice.**
  BUILD_PLAN 10.4 rebuilds every table from `data/raw` beside the
  incremental copy and compares to 1e-10. Its first run differed in 27
  tables. Two causes: the recompute tree lacked the hand-written override
  rows (`data/checks/membership_overrides.csv` is an *input* to the
  universe walk, and is now copied in), and `asof_join` broke ties
  between two filings available on the same day by sort order: a 10-K
  carries the year's and the fourth quarter's average share count at one
  date, and which one became market cap was luck. The rule is now the
  shorter, more recent window; it moved value's net Sharpe from 0.49 to
  0.48 and 820 share counts. Every specification was re-run (N 131 →
  185). The second run matched to 1e-10, and the job runs weekly. It
  earned its keep again in September 2026: after the data fixes it
  found the recompute tree's num cache had been built under the old tag
  map (the cache is now stamped with the map's hash and re-ingests
  itself) and one more sort-order tie, two bare rows of one share tag in
  one filing (the larger wins, as a rule), then a third in `first_filed`
  between an FSDS row and the SEC API's fallback row for one filing (the
  FSDS row wins, as a rule). N 233 → 329.
- **The deflated Sharpe was counting reruns as trials.** N was the row
  count of the specification log, and three reruns of the same 48
  specifications after the September data fixes had pushed it from 185
  to 329 without a single new strategy being tried. A trial is now a
  distinct specification key; the log had 61 of them across 340 rows
  (388 after the H3 reruns), 8 of them candidates. Every DSR rose (quality's from 0.06 to 0.39
  against the candidates) and none clears 0.5
  ([decisions/g2_trial_count.md](decisions/g2_trial_count.md)).
- **One specification row is mislabelled, and it stays.** Row 94 says
  "sensitivity jaccard" and is a cosine run: `raw_signal` read the scorer
  from the inputs' config rather than the run's, so a shared `Inputs`
  silently kept the base knob. Fixed and tested; the correct Jaccard run
  is row 131, whose note points back to "row 130", miscounted when it
  was written. Neither row is edited: the log is append-only, and this
  paragraph is the correction.
- **A terminal delisting return changes nothing either.** BUILD_PLAN 8.2's
  `terminal` convention (−30% in the month after a removed name's last
  print, `config.toml [delisting]`) applies to nine names in the window;
  the rest either kept trading after removal or have no prices at all. It
  moves every factor's net Sharpe by at most 0.01. The nine are in
  `data/checks/delisting_terminal.csv`; all were acquired, none failed,
  so −30% is the wrong sign for every one of them and is kept as the
  conservative convention the plan specifies. The real delisting gap is
  the 192 removed names with no price history, above.

## Running it

```bash
uv sync
uv run pytest                                   # 117 tests
uv run backtester fetch --step universe --as-of 2026-09-11
uv run backtester fetch --step prices     --as-of 2026-09-11
uv run backtester fetch --step benchmarks --as-of 2026-09-11
uv run backtester fetch --step fundamentals --as-of 2026-09-11   # ~2.5 GB
uv run backtester fetch --step text --as-of 2026-09-14           # ~10,300 10-K documents, resumable
uv run backtester build --step universe && uv run backtester build --step prices
uv run backtester build --step benchmarks && uv run backtester build --step fundamentals
uv run backtester build --step text && uv run backtester run --factor text_change
uv run backtester run-all && uv run backtester sensitivities && uv run backtester report
uv run dagster dev                              # the same pipeline as assets, with checks and schedules
```

Raw downloads are never overwritten and every one is in
`data/raw/manifest.json` with its sha256. Every knob is in `config.toml`.

## Layout

```
config.toml                    every knob; sensitivity tables loop over this
src/backtester/
  universe.py                  month-by-month S&P 500 membership, cross-checked
  prices.py                    daily prices, cleaning, monthly returns with lag
  benchmarks.py                French factors and their big-cap legs, FRED
  fundamentals.py + tag_map.toml   SEC filings, first-filed, as-of join, caps
  sectors.py                   CIK matching, SIC -> 11 buckets
  text.py                      10-K text from EDGAR, year-on-year similarity, invariant 10
  signals.py                   signals, winsorise, sector z-score, composite
  portfolio.py                 the engine: deciles, drift, turnover, costs, spec log
  stats.py                     IC, decay, Fama-MacBeth, Newey-West, DSR, attribution
  run.py                       one factor end to end; the loops; French replications
  report.py                    four charts and results.md
data/checks/                   committed evidence, one file per question
reports/figures, reports/results.md, reports/specifications.csv, reports/methodology.pdf
```

Build order was momentum first, since it needs no fundamentals, validated
against UMD before the SEC data was touched. [PLAN.md](PLAN.md) has the
phases and gates.
