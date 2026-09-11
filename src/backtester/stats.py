"""Statistics on portfolio and signal series.

Phase 4. Contract (PLAN.md section 3):

    ic_series                         Spearman rank IC per month
    ic_decay(horizons=[1,2,3,6,12])   fitted exponential -> half_life
    fama_macbeth                      cross-sectional premia per month
    newey_west(lags=holding - 1)      HAC variance of the mean premium
    sharpe, max_drawdown
    deflated_sharpe(sr, n_trials, T, skew, kurt)   Bailey & Lopez de Prado
    attribution(ls_returns, french) -> alpha, betas, t-stats
    breakeven_cost                    one-way cost at which net Sharpe is zero

Newey-West is written by hand from the formula in the brief and
cross-checked against statsmodels in a test; statsmodels is not a runtime
dependency.
"""
