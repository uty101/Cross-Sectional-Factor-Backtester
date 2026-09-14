"""Dagster wiring for the pipeline (BUILD_PLAN phase 10).

    definitions.py   one asset per stored table, checks on the evidence
                     files, schedules for the fetches, sensors for agents

Nothing here computes anything: every asset calls the same build
function the CLI calls, and every check reads a file under
``data/checks`` or ``reports`` that the build already wrote. Run with
``uv run dagster dev`` from the repo root (``[tool.dagster]`` in
pyproject names this module).
"""
