"""Assets, checks and schedules (BUILD_PLAN 10.1, 10.2, 10.5).

Assets are the stored tables, in the data-flow order the CLI runs them:

    raw fetches         wikipedia_html, price_pulls, benchmark_files,
                        sec_zips, edgar_10k_documents
    interim/processed   universe_monthly, prices_daily, french_monthly,
                        fundamentals_monthly, text_similarity
    runs                factor_<name> for every reported factor,
                        sensitivities, delisting
    reports             results, research_log

Every materialisation of a factor asset is a backtest and therefore a
row in the specification log (invariant 8); that is by design, and the
deflated Sharpe counts it. Fetch assets are resumable: each build
function already skips what is on disk.

Checks (10.5) read the evidence files the builds write. A failing check
blocks what depends on it. Thresholds live in config.toml [checks].

Compute is not incremental (plan 10.3): a full run of every factor
takes under a minute on this data, and the recompute check in 10.4 is
simpler when there is one path. Recorded in decisions/, not hidden.
"""

from datetime import date
from pathlib import Path

import polars as pl
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    DagsterRunStatus,
    Definitions,
    MaterializeResult,
    OpExecutionContext,
    RunConfig,
    RunRequest,
    ScheduleDefinition,
    SkipReason,
    asset,
    asset_check,
    asset_sensor,
    define_asset_job,
    job,
    op,
    run_failure_sensor,
    run_status_sensor,
    sensor,
)
from dagster import (
    Config as OpConfig,
)

from backtester import benchmarks, config, fundamentals, prices, text, universe
from backtester.run import REPORTED

ROOT = Path(__file__).resolve().parents[3]


def cfg() -> config.Config:
    return config.load(ROOT / "config.toml")


def _rows(path: Path) -> int:
    return pl.read_parquet(path).height if path.exists() else 0


# --- raw fetches ------------------------------------------------------------


@asset(group_name="raw")
def wikipedia_html() -> MaterializeResult:
    stored = universe.fetch(cfg(), date.today())
    return MaterializeResult(metadata={"files": len(stored)})


@asset(group_name="raw", deps=[wikipedia_html])
def price_pulls() -> MaterializeResult:
    stored = prices.fetch(cfg(), date.today())
    return MaterializeResult(metadata={"files": len(stored)})


@asset(group_name="raw")
def benchmark_files() -> MaterializeResult:
    stored = benchmarks.fetch(cfg(), date.today())
    return MaterializeResult(metadata={"files": len(stored)})


@asset(group_name="raw")
def sec_zips() -> MaterializeResult:
    stored = fundamentals.fetch(cfg(), date.today())
    return MaterializeResult(metadata={"files": len(stored)})


@asset(group_name="raw", deps=[sec_zips])
def edgar_10k_documents() -> MaterializeResult:
    stored = text.fetch(cfg(), date.today())
    return MaterializeResult(metadata={"new_documents": len(stored)})


# --- tables -----------------------------------------------------------------


@asset(group_name="tables", deps=[wikipedia_html])
def universe_monthly() -> MaterializeResult:
    c = cfg()
    out = universe.build(c)
    return MaterializeResult(metadata={"intervals": out.height})


@asset(group_name="tables", deps=[price_pulls, universe_monthly])
def prices_daily() -> MaterializeResult:
    c = cfg()
    out = prices.build(c)
    return MaterializeResult(metadata={"rows": out.height})


@asset(group_name="tables", deps=[benchmark_files])
def french_monthly() -> MaterializeResult:
    c = cfg()
    out = benchmarks.build(c)
    return MaterializeResult(metadata={"months": out.height})


@asset(group_name="tables", deps=[sec_zips, prices_daily, universe_monthly])
def fundamentals_monthly() -> MaterializeResult:
    c = cfg()
    out = fundamentals.build(c)
    return MaterializeResult(metadata={"rows": out.height})


@asset(group_name="tables", deps=[edgar_10k_documents, fundamentals_monthly])
def text_similarity() -> MaterializeResult:
    c = cfg()
    out = text.build(c)
    return MaterializeResult(metadata={"pairs": out.height})


# --- runs -------------------------------------------------------------------


def _factor_asset(name: str):
    @asset(
        name=f"factor_{name}",
        group_name="runs",
        deps=[prices_daily, french_monthly, fundamentals_monthly, text_similarity],
    )
    def _run(context: AssetExecutionContext) -> MaterializeResult:
        from backtester import run

        c = cfg()
        res = run.run_factor(c, name, note="dagster base")
        run.save(res, c)
        context.log.info(run.summary_line(res))
        return MaterializeResult(
            metadata={
                "months": res.result.long_short.height,
                "corr": res.validation.get("corr") or 0.0,
                "summary": run.summary_line(res),
            }
        )

    return _run


factor_assets = [_factor_asset(f) for f in REPORTED]


@asset(group_name="runs", deps=[AssetKey(f"factor_{f}") for f in REPORTED])
def sensitivities() -> MaterializeResult:
    from backtester import run

    out = run.sensitivities(cfg())
    return MaterializeResult(metadata={"runs": len(out)})


@asset(group_name="runs", deps=[AssetKey(f"factor_{f}") for f in REPORTED])
def delisting() -> MaterializeResult:
    from backtester import run

    out = run.delisting(cfg())
    return MaterializeResult(metadata={"runs": len(out)})


# --- reports ----------------------------------------------------------------


@asset(group_name="reports", deps=[sensitivities, delisting])
def results() -> MaterializeResult:
    from backtester import methodology, report

    c = cfg()
    report.build(c)
    methodology.build(c)
    v = pl.read_csv(c.reports / "validation.csv")
    return MaterializeResult(
        metadata={
            "validation_passed": int(v["passed"].sum()),
            "validation_rows": v.height,
        }
    )


@asset(group_name="reports", deps=[results])
def research_log() -> MaterializeResult:
    from backtester import research_log as rl

    out = rl.build(ROOT, cfg().specifications)
    return MaterializeResult(metadata={"path": str(out)})


# --- checks (10.5) ----------------------------------------------------------


@asset_check(asset=universe_monthly, blocking=True)
def universe_count_in_range() -> AssetCheckResult:
    c = cfg()
    lo, hi = dict(c.checks)["universe_min"], dict(c.checks)["universe_max"]
    counts = pl.read_csv(c.data / "checks" / "membership_monthly_counts.csv")
    bad = counts.filter((pl.col("n_members") < lo) | (pl.col("n_members") > hi))
    return AssetCheckResult(
        passed=bad.height == 0,
        metadata={
            "months_out_of_range": bad.height,
            "min": int(counts["n_members"].min()),
            "max": int(counts["n_members"].max()),
        },
    )


@asset_check(asset=prices_daily, blocking=True)
def recent_price_gap_is_small() -> AssetCheckResult:
    c = cfg()
    cov = pl.read_csv(c.data / "checks" / "price_coverage_monthly.csv")
    recent = cov.tail(12)["gap_pct"].mean()
    return AssetCheckResult(
        passed=recent <= dict(c.checks)["max_recent_price_gap_pct"],
        metadata={"recent_gap_pct": float(recent)},
    )


@asset_check(asset=fundamentals_monthly, blocking=True)
def recent_fundamentals_coverage() -> AssetCheckResult:
    c = cfg()
    cov = pl.read_csv(c.data / "checks" / "fundamentals_coverage.csv").tail(12)
    share = {
        k: float((cov[k] / cov["n_members"]).mean())
        for k in ("assets", "equity", "net_income", "revenue")
    }
    worst = min(share.values())
    return AssetCheckResult(
        passed=worst >= dict(c.checks)["min_recent_fundamentals_coverage"],
        metadata={k: round(v, 3) for k, v in share.items()},
    )


@asset_check(asset=AssetKey("factor_momentum"), blocking=True)
def momentum_validates_against_umd() -> AssetCheckResult:
    from backtester import run

    c = cfg()
    ls = pl.read_parquet(c.data / "processed" / "long_short_momentum.parquet")
    inp = run.load_inputs(c)
    v = run.validate(ls, inp.french, "umd")
    bar = dict(c.validation)["momentum"]
    return AssetCheckResult(
        passed=v["corr"] is not None and v["corr"] >= bar,
        metadata={"corr": float(v["corr"] or 0.0), "bar": bar},
    )


@asset_check(asset=results)
def every_validation_row_is_present() -> AssetCheckResult:
    """One row per configured threshold; a fail is reported, not blocked
    (CLAUDE.md: the bar is not lowered, and neither is the pipeline
    halted for a factor that is documented as failing it)."""
    c = cfg()
    v = pl.read_csv(c.reports / "validation.csv")
    expected = [k for k, _ in c.validation]
    missing = sorted(set(expected) - set(v["series"].to_list()))
    failing = v.filter(~pl.col("passed"))["series"].to_list()
    return AssetCheckResult(
        passed=not missing,
        severity=AssetCheckSeverity.WARN,
        metadata={"missing": missing, "failing": failing},
    )


# --- schedules (10.2) -------------------------------------------------------

prices_job = define_asset_job(
    "refresh_prices", selection=AssetSelection.assets(price_pulls, prices_daily)
)
universe_job = define_asset_job(
    "refresh_universe",
    selection=AssetSelection.assets(wikipedia_html, universe_monthly),
)
sec_job = define_asset_job(
    "refresh_sec",
    selection=AssetSelection.assets(
        sec_zips, edgar_10k_documents, fundamentals_monthly, text_similarity
    ),
)
benchmarks_job = define_asset_job(
    "refresh_benchmarks",
    selection=AssetSelection.assets(benchmark_files, french_monthly),
)
full_job = define_asset_job("full_pipeline", selection=AssetSelection.all())

schedules = [
    ScheduleDefinition(job=prices_job, cron_schedule="0 6 * * 0"),  # Sunday
    ScheduleDefinition(job=universe_job, cron_schedule="0 6 1 * *"),  # 1st
    ScheduleDefinition(job=sec_job, cron_schedule="0 6 2 * *"),  # monthly; fetch skips
    ScheduleDefinition(job=benchmarks_job, cron_schedule="0 6 3 * *"),
]

# --- agent jobs and sensors (11.8) ------------------------------------------
#
# Each agent is an op in its own job; a sensor decides when it runs. The
# agents need ANTHROPIC_API_KEY and gh; without them the job fails and
# the failure is visible in the UI, which is the honest outcome.


class AgentEvent(OpConfig):
    event: str = ""


@op
def research_log_op(context: OpExecutionContext) -> None:
    from backtester.agents import research_log as agent

    rec = agent.run(ROOT)
    context.log.info(rec["final_output"])


@op
def reporting_op(context: OpExecutionContext) -> None:
    from backtester.agents import reporting as agent

    rec = agent.run(ROOT, checks_passed=True)
    context.log.info(rec["final_output"])


@op
def triage_op(context: OpExecutionContext, config: AgentEvent) -> None:
    from backtester.agents import triage as agent

    rec = agent.run(ROOT, config.event)
    context.log.info(rec["final_output"])


@op
def tag_map_op(context: OpExecutionContext, config: AgentEvent) -> None:
    from backtester.agents import tag_map as agent

    rec = agent.run(ROOT, config.event.split(",") or ["revenue"])
    context.log.info(rec["final_output"])


@op
def universe_change_op(context: OpExecutionContext, config: AgentEvent) -> None:
    from backtester.agents import universe_change as agent

    error, _, html = config.event.partition("|")
    rec = agent.run(ROOT, error, html or "data/raw/wikipedia")
    context.log.info(rec["final_output"])


@op
def drift_op(context: OpExecutionContext, config: AgentEvent) -> None:
    from backtester.agents import drift as agent

    rec = agent.run(ROOT, config.event or "decisions/drift/latest.md")
    context.log.info(rec["final_output"])


@job
def research_log_agent():
    research_log_op()


@job
def reporting_agent():
    reporting_op()


@job
def triage_agent():
    triage_op()


@job
def tag_map_agent():
    tag_map_op()


@job
def universe_change_agent():
    universe_change_op()


@job
def drift_agent():
    drift_op()


def _event(op_name: str, text: str) -> RunConfig:
    return RunConfig(ops={op_name: AgentEvent(event=text)})


@asset_sensor(asset_key=AssetKey("results"), job=research_log_agent)
def results_materialized(context, asset_event):
    """11.2: after every pipeline run."""
    return RunRequest(run_key=str(asset_event.run_id))


@run_status_sensor(
    run_status=DagsterRunStatus.SUCCESS,
    monitored_jobs=[full_job],
    request_job=reporting_agent,
)
def pipeline_green(context):
    """11.3: a full run that finished with every blocking check passed."""
    return RunRequest(run_key=context.dagster_run.run_id)


@run_failure_sensor(monitored_jobs=[full_job, sec_job, universe_job, prices_job])
def pipeline_failed(context):
    """11.5 / 11.4 / 11.6: route a failure to the agent that handles it."""
    text = context.failure_event.message or ""
    run = context.dagster_run
    if run.job_name == universe_job.name:
        yield RunRequest(
            job_name=universe_change_agent.name,
            run_key=run.run_id,
            run_config=_event("universe_change_op", f"{text}|data/raw/wikipedia"),
        )
        return
    if "recent_fundamentals_coverage" in text:
        yield RunRequest(
            job_name=tag_map_agent.name,
            run_key=run.run_id,
            run_config=_event("tag_map_op", "revenue,cogs,net_income,cfo"),
        )
        return
    yield RunRequest(
        job_name=triage_agent.name,
        run_key=run.run_id,
        run_config=_event(
            "triage_op", f"run {run.run_id} of {run.job_name} failed: {text}"
        ),
    )


@sensor(job=triage_agent, minimum_interval_seconds=6 * 3600)
def four_sigma_months(context):
    """11.5: a factor month beyond four leave-one-out sigmas, once each."""
    from backtester.agents.triage import anomalous_months

    hits = anomalous_months(cfg())
    if hits.is_empty():
        return SkipReason("no anomalous months")
    seen = set((context.cursor or "").split(";")) - {""}
    for r in hits.iter_rows(named=True):
        key = f"{r['factor']}:{r['month']}"
        if key in seen:
            continue
        seen.add(key)
        yield RunRequest(
            run_key=key,
            run_config=_event(
                "triage_op",
                f"{r['factor']} long-short {r['month']}: "
                f"{r['ret_gross']:+.3f} ({r['sigma']:+.1f} sigma)",
            ),
        )
    context.update_cursor(";".join(sorted(seen)))


defs = Definitions(
    assets=[
        wikipedia_html,
        price_pulls,
        benchmark_files,
        sec_zips,
        edgar_10k_documents,
        universe_monthly,
        prices_daily,
        french_monthly,
        fundamentals_monthly,
        text_similarity,
        *factor_assets,
        sensitivities,
        delisting,
        results,
        research_log,
    ],
    asset_checks=[
        universe_count_in_range,
        recent_price_gap_is_small,
        recent_fundamentals_coverage,
        momentum_validates_against_umd,
        every_validation_row_is_present,
    ],
    jobs=[
        prices_job,
        universe_job,
        sec_job,
        benchmarks_job,
        full_job,
        research_log_agent,
        reporting_agent,
        triage_agent,
        tag_map_agent,
        universe_change_agent,
        drift_agent,
    ],
    schedules=schedules,
    sensors=[results_materialized, pipeline_green, pipeline_failed, four_sigma_months],
)
