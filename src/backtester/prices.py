"""Daily adjusted prices for every ticker that ever appeared in the universe.

Phase 2. Contract (PLAN.md section 3):

    fetch(ticker, source) -> raw csv             yfinance first, Stooq fallback
    build_daily(raw_dir) -> prices_daily.parquet
    monthly_returns(daily, lag_days) -> returns_monthly
    coverage_report(membership, daily) -> Frame[month, n_members, n_priced, gap_pct]

Raw pulls are never overwritten (invariant 7). A signal at month-end t is
traded at the close of t + lag_days and earns nothing before then
(invariant 4). Every name that could not be fetched is logged; the gap is
reported as a percentage of universe-months.
"""
