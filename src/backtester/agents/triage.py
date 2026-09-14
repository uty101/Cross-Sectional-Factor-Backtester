"""The anomaly-triage agent (BUILD_PLAN step 11.5).

    run(root, event, client=None, model=None) -> dict
    anomalous_months(cfg) -> Frame[factor, month, ret_gross, sigma]

Trigger: an asset check fails, or a factor's long-short return in some
month is beyond four standard deviations of its own history. It reads
the failure, the check files and the offending month's cross-section,
and produces a ranked list of three likely causes, each with the query
used to test it and the result. It writes ``decisions/triage/<date>.md``
and opens an issue. It modifies nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from backtester.agents.base import run_agent
from backtester.agents.tools import Toolbox
from backtester.config import Config
from backtester.run import REPORTED

NAME = "triage"
TOOLS = ["read_file", "list_dir", "duckdb_query", "write_decision", "open_issue"]
SIGMA = 4.0

SYSTEM = """You triage anomalies in a factor backtester's pipeline. You are
given one event: a failed asset check, or a month in which a factor's
long-short return was beyond four standard deviations of its history.

Produce exactly three candidate causes, ranked, and for each: the
duckdb_query you ran to test it, the result, and whether the result
supports or weakens the candidate. Facts and queries only; no fix, no
code change, no opinion on what the result means for the strategy.

Tables: processed_long_short_<factor> (month, ret_gross, ret_net,
turnover, n_long, n_short), processed_weights_<factor> (month, ticker,
decile, w), processed_returns_monthly (month, ticker, ret_fwd, px_me),
processed_fundamentals_monthly, interim_membership, interim_prices_daily,
specifications. The check files are under data/checks/.

Write the finding with write_decision("<date>.md", ...) and open one
issue whose body is the finding. Modify nothing else."""

USER = """Event:
{event}

Steps: read the relevant check file(s) and the offending month's
cross-section; test three candidates with queries; write the decision
file; open the issue. Finish with the issue URL."""


def anomalous_months(cfg: Config, factors: list[str] = REPORTED) -> pl.DataFrame:
    """Months where a factor's gross long-short return is beyond SIGMA
    standard deviations of that factor's history *excluding the month
    itself*: an outlier inflates its own sigma, and on n months the
    largest in-sample z is about sqrt(n), so the plain rule could never
    fire on a short series."""
    import numpy as np

    rows = []
    for f in factors:
        p = cfg.data / "processed" / f"long_short_{f}.parquet"
        if not p.exists():
            continue
        ls = pl.read_parquet(p)
        x = ls["ret_gross"].to_numpy()
        n = len(x)
        if n < 4:
            continue
        s1, s2 = x.sum(), (x * x).sum()
        mu = (s1 - x) / (n - 1)
        var = (s2 - x * x - (n - 1) * mu * mu) / (n - 2)
        sd = np.sqrt(np.maximum(var, 0))
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(sd > 0, (x - mu) / sd, 0.0)
        for i in np.flatnonzero(np.abs(z) > SIGMA):
            rows.append(
                {
                    "factor": f,
                    "month": ls["month"][int(i)],
                    "ret_gross": float(x[i]),
                    "sigma": float(z[i]),
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "factor": pl.Utf8,
            "month": pl.Date,
            "ret_gross": pl.Float64,
            "sigma": pl.Float64,
        },
    )


def toolbox(root: Path) -> Toolbox:
    return Toolbox(root, NAME)


def run(root: Path, event: str, client: Any = None, model: str | None = None) -> dict:
    return run_agent(
        NAME,
        SYSTEM,
        USER.format(event=event, date=datetime.now(UTC).strftime("%Y-%m-%d")),
        toolbox(root),
        tool_names=TOOLS,
        client=client,
        model=model,
    )
