# G2: the trial count behind the deflated Sharpe (2026-09-15)

## What was wrong

`reports/specifications.csv` had 335 rows and the deflated Sharpe used
the row count as N (329 all, 55 candidates at the last report). Those
rows were 12 distinct `config_hash` values, because the hash covers the
global config and every sensitivity shares it; and, more to the point,
the three September reruns after the F3 data fixes ("post-F3",
"post-F3 ingest v2", "post-F3 first-filed tie") re-ran the same 48
specifications each and were counted as 144 new trials. Re-running a
specification after a code fix is not a new draw from the space of
strategies. The DSR was deflating against runs, not trials.

## What changed

`speclog.py` (the log moved out of `portfolio.py`; `portfolio` still
re-exports the old names) defines a specification key: sha256 of

    factor, signal, weighting, cost_bps, lag_days, rebalance,
    holding_months, winsor_lo, winsor_hi, n_deciles, sector_neutral,
    start, end, variant

Two of those are new columns. `sector_neutral` was only ever in the
note (" no-sector" appended by `run_factor`) and is now written from the
run's argument. `variant` is not in the plan's tuple and was added
because without it two logged sensitivities key identically to their
base runs: the delisting sensitivity (`terminal`) changes the input
returns, not the config, and the Jaccard text run changes
`text_similarity`, which is not a log column. It is `terminal`,
`cosine`/`jaccard` (text factor only), or blank. Both columns and
`spec_key` were backfilled for the 335 existing rows from the note and
signal; no existing value changed (checked cell by cell against HEAD).

Row 94 is labelled "sensitivity jaccard" and was a cosine run (README,
"What did not work"). It is keyed as labelled. Its correction, row 131,
carries the same key, so the count is unaffected either way.

N is now `count_trials`: distinct keys, 58 in all and 8 candidates. The
dispersion of Sharpe across trials is measured over the latest row of
each key (variance of the monthly Sharpe 0.0050 all, 0.0036 candidates)
rather than over every rerun. The results header prints both counts:
`N = 58 distinct specifications (335 runs logged), 8 candidates`.

The 8 candidate keys: the base run of each of the five reported
factors, beta, the text factor, and momentum without sector
neutralisation (the phase-3 first runs carried no prefix and so are
candidates by the F4 rule; the later "sensitivity nosector" rows share
the key and are diagnostics, and a key with rows of both kinds counts
in both).

## Every DSR before and after

Same saved series; only N and the cross-trial variance changed.

| Factor | Sharpe (net) | DSR (all) before, N=329 | after, N=58 | DSR (cand.) before, N=55 | after, N=8 |
|---|---|---|---|---|---|
| Momentum 12-1 | 0.04 | 0.00 | 0.02 | 0.01 | 0.14 |
| Value (B/P, E/P) | −0.16 | 0.00 | 0.00 | 0.00 | 0.03 |
| Quality (GP/A, accruals) | 0.24 | 0.02 | 0.09 | 0.06 | 0.39 |
| Low volatility | −0.27 | 0.00 | 0.00 | 0.00 | 0.01 |
| Composite | −0.33 | 0.00 | 0.00 | 0.00 | 0.00 |
| 10-K text similarity (appendix) | −0.17 | 0.00 | 0.00 | 0.00 | 0.03 |

The "before" column is the table in `reports/results.md` at commit
`933407f`, whose header still said N = 329 (six rows were logged after
that report and before this one).

## What it does and does not say

Quality's 0.39 against the candidates means: the probability that a net
Sharpe of 0.24 beats the best of eight random strategies with this
dispersion is 39%. That is the honest number and it is still not
evidence of a premium; the IC t-stat of 1.4 has not moved. Nothing
clears 0.5 on either count. The direction of the change is the point:
the previous N was overstating the number of things tried by a factor
of six, which made every DSR look like a rounding error and the control
look stricter than it was.

The README's "what did not work" paragraph on N (131 → 185 → 233 → 329)
describes the row count, which is still true and still what the file
holds; the row count is now reported next to the trial count rather
than as it.
