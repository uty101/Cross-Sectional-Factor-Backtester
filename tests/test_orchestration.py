"""The Dagster definitions load, name every stored table, and every check
is attached to an asset that exists (BUILD_PLAN 10.1, 10.5)."""

from backtester.orchestration import definitions as d
from backtester.run import REPORTED


def test_definitions_load_with_every_asset_and_check() -> None:
    graph = d.defs.resolve_asset_graph()
    keys = {k.to_user_string() for k in graph.get_all_asset_keys()}
    for name in (
        "wikipedia_html",
        "sec_zips",
        "edgar_10k_documents",
        "universe_monthly",
        "prices_daily",
        "french_monthly",
        "fundamentals_monthly",
        "text_similarity",
        "sensitivities",
        "delisting",
        "results",
        "research_log",
    ):
        assert name in keys
    for f in REPORTED:
        assert f"factor_{f}" in keys
    check_assets = {c.asset_key.to_user_string() for c in graph.asset_check_keys}
    assert check_assets <= keys
    assert len(list(graph.asset_check_keys)) == 5
    assert {j.name for j in d.defs.jobs} >= {"refresh_prices", "full_pipeline"}


def test_dependencies_follow_the_data_flow() -> None:
    graph = d.defs.resolve_asset_graph()

    def deps(name: str) -> set[str]:
        key = next(k for k in graph.get_all_asset_keys() if k.to_user_string() == name)
        return {k.to_user_string() for k in graph.get(key).parent_keys}

    assert "wikipedia_html" in deps("universe_monthly")
    assert {"sec_zips", "prices_daily", "universe_monthly"} <= deps(
        "fundamentals_monthly"
    )
    assert "fundamentals_monthly" in deps("factor_value")
    assert {"sensitivities", "delisting"} <= deps("results")


def test_every_agent_has_a_job_and_the_sensors_are_wired() -> None:
    jobs = {j.name for j in d.defs.jobs}
    for name in (
        "research_log",
        "reporting",
        "triage",
        "tag_map",
        "universe_change",
        "drift",
    ):
        assert f"{name}_agent" in jobs
    sensors = {s.name for s in d.defs.sensors}
    assert sensors == {
        "results_materialized",
        "pipeline_green",
        "pipeline_failed",
        "four_sigma_months",
    }
