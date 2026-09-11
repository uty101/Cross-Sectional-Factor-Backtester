"""The backtest engine. Accepts any signal frame shaped (month, ticker, z).

Phase 3, hardened in phase 7. Contract (PLAN.md section 3):

    assign_deciles(z, n) -> Frame[month, ticker, decile]
    weights(deciles, caps, weighting) -> Frame[month, ticker, w]
    drift(w, daily_returns) -> w_minus
    turnover(w, w_minus)      0.5 * sum |w - w_minus|, both legs (invariant 6)
    backtest(signal_z, returns, cfg)
        -> Frame[month, decile | LS, ret_gross, ret_net, turnover]

``backtest`` appends one row to reports/specifications.csv every time it
runs (invariant 8). That file is the N in the deflated Sharpe. Net return is
gross minus one-way cost times turnover.

This module is the reuse surface for projects 2 and 7: swapping in a new
signal must be a change to the caller, not to this file.
"""
