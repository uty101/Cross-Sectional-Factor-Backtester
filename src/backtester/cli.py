"""``backtester fetch | build | run | report``.

Thin by design: each subcommand is one function call into the package, so
the pipeline can be driven from a notebook or a test the same way.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from backtester import config

PHASES = {
    "fetch": "phases 1, 2 and 5 (universe, prices, SEC)",
    "build": "phases 1, 2 and 5 (parquet from raw)",
    "run": "phase 3 (momentum end to end)",
    "report": "phase 8",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backtester")
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download raw data into data/raw, never overwriting")
    sub.add_parser("build", help="parse data/raw into data/interim and data/processed")
    run = sub.add_parser("run", help="backtest one factor and log the specification")
    run.add_argument("--factor", required=True)
    sub.add_parser("report", help="charts and tables into reports/")

    args = parser.parse_args(argv)
    cfg = config.load(args.config)
    print(
        f"{args.command}: not implemented yet ({PHASES[args.command]}); "
        f"config loaded for {cfg.start} to {cfg.end}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
