"""Month-by-month S&P 500 membership, reconstructed from the Wikipedia
component-changes table.

Phase 1. Contract (PLAN.md section 3):

    parse_wikipedia_changes(html) -> Frame[ticker, added, removed, reason]
    build_membership(changes, current_members) -> Frame[ticker, start, end]
    members_at(membership, date) -> list[str]

Membership is stored as closed intervals per ticker. A ticker is in the
cross-section at t only if t falls inside one of its intervals (invariant 3).
Twenty changes are spot-checked against press releases and the results
committed to data/checks/membership_spotcheck.csv.
"""
