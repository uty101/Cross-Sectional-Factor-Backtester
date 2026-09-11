"""Ken French factors and the FRED risk-free rate.

Phase 3 (French, needed to validate momentum against UMD) and phase 4.
Produces data/interim/french_monthly.parquet with columns
month, mkt_rf, smb, hml, rmw, cma, umd, rf.

The validation bar is fixed in the README: each long-short series must
correlate above 0.7 with the matching French factor, or the pipeline is
wrong.
"""
