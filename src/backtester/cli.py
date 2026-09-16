"""``backtester fetch | build | run | report | site``.

Thin by design: each subcommand is one function call into the package, so
the pipeline can be driven from a notebook or a test the same way.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from backtester import benchmarks, config, fundamentals, prices, shares, text, universe

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
    # Cover-page share counts (SEC companyconcept) and splits (yfinance);
    # build --step fundamentals reads both if present.
    "shares": (
        lambda cfg, as_of: (
            shares.fetch_cover(cfg, as_of)
            + shares.fetch_fallback(cfg, as_of)
            + shares.fetch_float(cfg, as_of)
            + shares.fetch_splits(cfg, as_of)
        ),
        shares.build,
    ),
}
UNIMPLEMENTED: dict[str, str] = {}


def secrets_report(root: str = ".") -> list[str]:
    """One line per key in ``config.SECRET_NAMES``, ``set`` or ``missing``,
    then whether ``gh auth status`` succeeds. No value, and no prefix of
    one, is ever printed: this is FIX_PLAN_2 A7, run before G6."""
    import shutil
    import subprocess

    lines = []
    for name in config.SECRET_NAMES:
        state = "set" if config.secret(name, root) else "missing"
        lines.append(f"{name}: {state} (Part A step {config.SECRET_STEPS[name]})")
    gh = shutil.which("gh")
    if gh is None:
        lines.append("gh auth status: gh not installed (Part A step A5)")
    else:
        ok = (
            subprocess.run(
                [gh, "auth", "status"], capture_output=True, timeout=30
            ).returncode
            == 0
        )
        lines.append(
            "gh auth status: ok" if ok else "gh auth status: not logged in (A5)"
        )
    return lines


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
    sub.add_parser("site", help="docs/index.html from the report (FIX_PLAN_4 J2)")
    sub.add_parser("secrets", help="which API keys are set (never prints a value)")
    sub.add_parser("run-all", help="base run of every reported factor")
    sub.add_parser("sensitivities", help="weighting and holding-period variants")
    sub.add_parser("delisting", help="the terminal-return delisting sensitivity")
    sub.add_parser("hedge", help="beta-hedged variants of low_vol and beta (F5)")
    rerun = sub.add_parser(
        "rerun", help="every specification again, with a note suffix (F4)"
    )
    rerun.add_argument(
        "--note", required=True, help='appended to every note, e.g. " post-F3"'
    )
    sub.add_parser(
        "research-log", help="reports/what_did_not_work.md from the spec log and git"
    )
    agent = sub.add_parser("agent", help="run one agent through the harness")
    agent.add_argument(
        "name",
        choices=[
            "research_log",
            "reporting",
            "tag_map",
            "triage",
            "universe_change",
            "drift",
        ],
    )
    agent.add_argument(
        "--arg", action="append", default=[], help="agent-specific input"
    )

    args = parser.parse_args(argv)
    cfg = config.load(args.config)

    if args.command == "fetch":
        stored = STEPS[args.step][0](cfg, args.as_of)
        print(f"stored {len(stored)} files under data/raw")
        return 0
    if args.command == "build":
        out = STEPS[args.step][1](cfg)
        rows = sum(o.height for o in out) if isinstance(out, tuple) else out.height
        print(f"built {args.step}: {rows} rows")
        return 0

    if args.command == "secrets":
        for line in secrets_report():
            print(line)
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

        from backtester.agents import (
            drift,
            reporting,
            research_log,
            tag_map,
            triage,
            universe_change,
        )

        root, a = Path.cwd(), args.arg
        runners = {
            "research_log": lambda: research_log.run(root),
            "reporting": lambda: reporting.run(root, checks_passed=True),
            "tag_map": lambda: tag_map.run(root, a or ["revenue"]),
            "triage": lambda: triage.run(root, a[0] if a else "manual run"),
            "universe_change": lambda: universe_change.run(root, a[0], a[1]),
            "drift": lambda: drift.run(
                root, a[0] if a else "decisions/drift/latest.md"
            ),
        }
        rec = runners[args.name]()
        print(
            f"{rec['agent']}: {len(rec['tool_calls'])} tool calls, {rec['stop_reason']}"
        )
        print(rec["final_output"])
        return 0
    if args.command == "hedge":
        from backtester import run as runner

        runner.hedged(cfg)
        return 0
    if args.command == "rerun":
        from backtester import run as runner

        runner.rerun(cfg, args.note)
        return 0
    if args.command == "delisting":
        from backtester import run as runner

        runner.delisting(cfg)
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
    if args.command == "site":
        from backtester import report

        print(f"wrote {report.site(cfg)}")
        return 0
    print(f"{args.command}: unknown", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
