"""Agents that read the repo and propose; the pipeline decides.

    base.py      run_agent: the one harness every agent goes through
    tools.py     the tools it may call, each with its allowlist in code

An agent writes only under ``decisions/`` and to pull requests. It never
writes under ``data/``, ``src/``, ``config.toml`` or the specification
log, and it never runs a backtest (BUILD_PLAN phase 11).
"""
