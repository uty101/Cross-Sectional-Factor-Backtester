"""``backtester fetch | build | run | report``.

Thin by design: each subcommand is one function call into the package, so
the pipeline can be driven from a notebook or a test the same way.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from backtester import config, universe

# step name -> (fetch, build). Phases add themselves here as they land.
STEPS = {
    "universe": (lambda cfg, as_of: universe.fetch(cfg, as_of), universe.build),
}
UNIMPLEMENTED = {
    "run": "phase 3 (momentum end to end)",
    "report": "phase 8",
}


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
    sub.add_parser("report", help="charts and tables into reports/")

    args = parser.parse_args(argv)
    cfg = config.load(args.config)

    if args.command == "fetch":
        for p in STEPS[args.step][0](cfg, args.as_of):
            print(f"stored {p}")
        return 0
    if args.command == "build":
        out = STEPS[args.step][1](cfg)
        print(f"built {args.step}: {out.height} rows")
        return 0

    print(
        f"{args.command}: not implemented yet ({UNIMPLEMENTED[args.command]}); "
        f"config loaded for {cfg.start} to {cfg.end}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
