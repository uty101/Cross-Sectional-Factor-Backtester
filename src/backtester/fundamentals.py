"""SEC Financial Statement Data Sets, keyed on filing date.

Phase 5. Contract (PLAN.md section 3):

    ingest_quarter(zip) -> DuckDB                 sub, num, tag, pre loaded raw
    first_filed(num) -> Frame        min(filed) per (cik, concept, period_end, qtrs)
    asof_join(panel, fundamentals, buffer_days=1) -> Frame
    ttm(...), latest_balance(...)                 flow vs stock concepts

``asof_join`` is the point-in-time join: a value used at month-end t must
have been filed on or before t - buffer_days (invariant 1). It is written
once and tested first with a planted filing dated after the signal date.
Amended filings do not rewrite history; the first-filed value wins
(invariant 2). Concepts map to ordered XBRL tag lists in tag_map.toml, with
coverage per year committed to data/checks/tag_coverage.csv.
"""
