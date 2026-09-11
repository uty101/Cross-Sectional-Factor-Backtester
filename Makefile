# Targets run through uv so the lockfile is the environment. On a machine
# without make, run the uv commands directly; they are one line each.

.PHONY: check lint test hooks fetch build run report

check: lint test

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

# nbstripout as a git filter so notebooks are committed without output.
hooks:
	uv run nbstripout --install

fetch:
	uv run backtester fetch

build:
	uv run backtester build

run:
	uv run backtester run

report:
	uv run backtester report
