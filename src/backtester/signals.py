"""Raw signals and the one normaliser that turns them into z-scores.

Phases 3 and 6. Each signal is a function returning Frame[month, ticker, value]:

    momentum_12_1        cumulative return t-12 -> t-1, month t skipped (invariant 5)
    book_to_price, earnings_yield
    gross_profitability, accruals, asset_growth
    volatility_252, beta

Then:

    normalise(raw, sectors, winsor) -> Frame[month, ticker, z]
        winsorise at the config percentiles, demean within sector, divide
        by sector standard deviation, using only data available at t.
    composite(zs) -> z
        average of z-scores, re-standardised.
"""
