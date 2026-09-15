"""FIX_PLAN F3: which tags do the filers with no value for a concept use?

    uv run python scripts/tag_gap.py <concept> <fy> [keyword ...]

Lists every universe CIK with no 10-K value for ``concept`` in fiscal
year ``fy`` (from the ingested num cache), then reads that year's raw
zips for those CIKs and counts the tags whose name contains any of the
keywords (default: Cost, Revenue, Sales). The 20 most common are printed
and written to data/checks/tag_gap_<concept>_<fy>.csv with the number of
missing filers using each and an example filer. A tag used by 5 or more
missing filers is a candidate for tag_map.toml; ``CostsAndExpenses`` is
never one for cogs (it includes SG&A).
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

from backtester import config
from backtester import fundamentals as fx

DEFAULT_KEYWORDS = ("Cost", "Revenue", "Sales")


def missing_ciks(
    num: pl.DataFrame, ciks: pl.DataFrame, concept: str, fy: int
) -> list[int]:
    """Universe CIKs that filed a 10-K for ``fy`` but have no ``concept`` row in it."""
    universe = set(int(c) for c in ciks["cik"].unique().to_list())
    filed = (
        num.filter((pl.col("fy") == fy) & pl.col("form").str.starts_with("10-K"))
        .select("cik")
        .unique()
    )
    have = (
        num.filter(
            (pl.col("fy") == fy)
            & pl.col("form").str.starts_with("10-K")
            & (pl.col("concept") == concept)
        )
        .select("cik")
        .unique()
    )
    return sorted(
        c
        for c in filed.join(have, on="cik", how="anti")["cik"].to_list()
        if c in universe
    )


def tag_gap(
    cfg: config.Config,
    concept: str,
    fy: int,
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS,
    top: int = 20,
) -> tuple[list[int], pl.DataFrame]:
    num = pl.read_parquet(cfg.data / "interim" / "sec_num.parquet")
    ciks = pl.read_parquet(cfg.data / "interim" / "sectors.parquet").select("cik")
    missing = missing_ciks(num, ciks, concept, fy)
    cands = fx.candidate_tags(cfg, concept, fy, missing, limit=100_000)
    pattern = "|".join(keywords)
    out = (
        cands.filter(pl.col("tag").str.contains(pattern))
        .sort("n_ciks", descending=True)
        .head(top)
        .with_columns(
            pl.lit(concept).alias("concept"),
            pl.lit(fy).alias("fy"),
            pl.lit(len(missing)).alias("n_missing"),
        )
        .select("concept", "fy", "n_missing", "tag", "n_ciks", "example")
    )
    return missing, out


def main(argv: list[str]) -> int:
    concept, fy = argv[0], int(argv[1])
    keywords = tuple(argv[2:]) or DEFAULT_KEYWORDS
    cfg = config.load()
    missing, out = tag_gap(cfg, concept, fy, keywords)
    path = cfg.data / "checks" / f"tag_gap_{concept}_{fy}.csv"
    out.write_csv(path)
    print(f"{concept} FY{fy}: {len(missing)} universe filers with no value")
    with pl.Config(tbl_rows=25, fmt_str_lengths=80):
        print(out)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.exit(main(sys.argv[1:]))
