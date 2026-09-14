"""``backtester fetch | build | run | report``.

Thin by design: each subcommand is one function call into the package, so
the pipeline can be driven from a notebook or a test the same way.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from backtester import benchmarks, config, fundamentals, prices, text, universe

# step name -> (fetch, build). Phases add themselves here as they land.
STEPS = {
    "universe": (lambda cfg, as_of: universe.fetch(cfg, as_of), universe.build),
    "prices": (lambda cfg, as_of: prices.fetch(cfg, as_of), prices.build),
    "benchmarks": (lambda cfg, as_of: benchmarks.fetch(cfg, as_of), benchmarks.build),
    "fundamentals": (
        lambda cfg, as_of: fundamentals.fetch(cfg, as_of),
        fundamentals.build,
    ),
    "text": (lambda cfg, as_of: text.fetch(cfg, as_of), text.build),
}
UNIMPLEMENTED: dict[str, str] = {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backtester")
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch", help="download raw data into data/raw, never overwriting"
    )
    fetch.add_argument("--step", choices=STEPS, required=True)
    fetch.add_argument("--as-of", type=date.fromisoformat, default=date.today())

    build = sub.add_parser(
        "build", help="parse data/raw into data/interim and data/processed"
    )
    build.add_argument("--step", choices=STEPS, required=True)

    run = sub.add_parser("run", help="backtest one factor and log the specification")
    run.add_argument("--factor", required=True)
    run.add_argument("--note", default="")
    run.add_argument("--no-sector", action="store_true", help="plain cross-sectional z")
    sub.add_parser("report", help="charts and tables into reports/")
    sub.add_parser("run-all", help="base run of every reported factor")
    sub.add_parser("sensitivities", help="weighting and holding-period variants")
    sub.add_parser(
        "research-log", help="reports/what_did_not_work.md from the spec log and git"
    )
    agent = sub.add_parser("agent", help="run one agent through the harness")
    agent.add_argument("name", choices=["research_log"])

    args = parser.parse_args(argv)
    cfg = config.load(args.config)

    if args.command == "fetch":
        stored = STEPS[args.step][0](cfg, args.as_of)
        print(f"stored {len(stored)} files under data/raw")
        return 0
    if args.command == "build":
        out = STEPS[args.step][1](cfg)
        print(f"built {args.step}: {out.height} rows")
        return 0

    if args.command == "run":
        from backtester import run as runner

        res = runner.run_factor(
            cfg, args.factor, note=args.note, sector_neutral=not args.no_sector
        )
        runner.save(res, cfg)
        print(runner.summary_line(res))
        return 0

    if args.command == "run-all":
        from backtester import run as runner

        runner.run_all(cfg)
        return 0
    if args.command == "sensitivities":
        from backtester import run as runner

        runner.sensitivities(cfg)
        return 0
    if args.command == "agent":
        from pathlib import Path

        from backtester.agents import research_log as research_log_agent

        rec = {"research_log": research_log_agent.run}[args.name](Path.cwd())
        print(
            f"{rec['agent']}: {len(rec['tool_calls'])} tool calls, {rec['stop_reason']}"
        )
        print(rec["final_output"])
        return 0
    if args.command == "research-log":
        from pathlib import Path

        from backtester import research_log

        out = research_log.build(Path.cwd(), cfg.specifications)
        print(f"wrote {out}")
        return 0
    if args.command == "report":
        from backtester import report

        report.build(cfg)
        from backtester import methodology

        methodology.build(cfg)
        print(f"wrote {cfg.reports / 'results.md'} and methodology.pdf")
        return 0
    print(f"{args.command}: unknown", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
