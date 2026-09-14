"""CI guard for tag_map.toml (BUILD_PLAN 11.4/11.8): a pull request may
add tags to a concept, never remove or reorder one, never drop a
concept, never change a kind. Coverage itself needs the SEC data and is
recomputed locally by the fundamentals build and its Dagster check.

    python scripts/check_tag_map.py <base.toml> <head.toml>
"""

import sys
import tomllib
from pathlib import Path


def main(base_path: str, head_path: str) -> int:
    base = tomllib.loads(Path(base_path).read_text(encoding="utf-8"))["concept"]
    head = tomllib.loads(Path(head_path).read_text(encoding="utf-8"))["concept"]
    problems = []
    for concept, spec in base.items():
        if concept not in head:
            problems.append(f"{concept}: concept removed")
            continue
        if head[concept].get("kind") != spec.get("kind"):
            problems.append(f"{concept}: kind changed")
        old, new = spec["tags"], head[concept]["tags"]
        if new[: len(old)] != old:
            problems.append(f"{concept}: existing tags removed or reordered")
        else:
            for t in new[len(old) :]:
                print(f"{concept}: + {t}")
    for concept in head:
        if concept not in base:
            print(f"new concept {concept}: {head[concept]['tags']}")
    for p in problems:
        print("FAIL", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
