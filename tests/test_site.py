"""The results site (FIX_PLAN_4 J2) is a function of the report's outputs.

These run against the repo's committed reports/ and data/checks/ files,
the way test_readme does, so they need no data volume; the page is
written to a temporary directory."""

import json
import re
from pathlib import Path

import polars as pl
import pytest

from backtester import config, site

KEY_PATTERN = r"(?<![\d.]){}(?![\d])"


@pytest.fixture(scope="module")
def cfg(repo_root: Path) -> config.Config:
    return config.load(repo_root / "config.toml")


@pytest.fixture(scope="module")
def data(cfg: config.Config, repo_root: Path) -> dict:
    return site.data(cfg, repo_root)


@pytest.fixture(scope="module")
def page(cfg: config.Config, repo_root: Path, tmp_path_factory) -> Path:
    """docs/index.html built in a copy of the repo's inputs, so the test
    never writes into the working tree."""
    root = tmp_path_factory.mktemp("site")
    for rel in ("report", "reports", "data/checks", "decisions/drift", "README.md"):
        src = repo_root / rel
        dst = root / rel
        if src.is_dir():
            dst.parent.mkdir(parents=True, exist_ok=True)
            for f in src.rglob("*"):
                if f.is_file() and ".git" not in f.parts:
                    out = dst / f.relative_to(src)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(f.read_bytes())
        else:
            dst.write_bytes(src.read_bytes())
    return site.build(cfg, root)


def test_every_reported_factor_is_a_card(cfg: config.Config, repo_root: Path, data):
    res = pl.read_csv(repo_root / cfg.reports / "results.csv")
    names = {r["name"] for r in data["factors"]}
    # results.csv carries the appendix row too (J3b); the cards are the headline
    headline = res.filter(pl.col("key").is_in(list(site.KEYS)))
    assert names == set(headline["factor"].to_list())
    assert "10-K text similarity" not in names
    assert [f["key"] for f in data["factors"]] == ["m", "v", "q", "l", "c"]


def test_every_schema_key_is_produced(repo_root: Path, data):
    missing = site.schema_keys(repo_root) - set(data)
    assert not missing, missing
    assert "exclusions" in data  # the template renders it; the example omitted it


def test_no_placeholder_remains_and_the_json_parses_back(page: Path, data):
    html = page.read_text(encoding="utf-8")
    assert not re.search(r"__[A-Z_]+__", html)
    m = re.search(r"const DATA = (\{.*?\});\nconst IMG_DECILES", html, flags=re.S)
    assert m
    assert json.loads(m.group(1).replace("<\\/", "</")) == data
    assert html.count("data:image/jpeg;base64,") == 2


def test_page_is_under_400_kb(page: Path):
    assert page.stat().st_size < site.MAX_BYTES


def test_every_number_in_the_answer_is_on_the_page(cfg, repo_root: Path, data):
    """The answer paragraph quotes the current numbers, or a before-and-
    after decision record when it says what a number used to be."""
    shown = json.dumps(
        {k: v for k, v in data.items() if k not in ("answer", "wdnw")},
        ensure_ascii=False,
    )
    history = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (repo_root / "decisions").glob("*_before_after.md")
    ).replace("−", "-")
    answer = (repo_root / cfg.reports / "answer.md").read_text(encoding="utf-8")
    for n in re.findall(r"-?\d+(?:\.\d+)?", answer.replace("−", "-")):
        pat = KEY_PATTERN.format(re.escape(n))
        assert re.search(pat, shown) or re.search(pat, history), n


def test_validation_lists_every_row_with_its_bar_and_kind(cfg, repo_root: Path, data):
    """Every validation.csv row is on the page as [series, benchmark, corr,
    bar, kind]; a row is matched by its series label, since the page's
    order is not the file's."""
    from backtester.report import NOT_A_JOIN_TEST

    v = pl.read_csv(repo_root / cfg.reports / "validation.csv")
    assert len(data["validation"]) == v.height
    by_label = {
        site.SERIES_LABELS.get(r["series"], r["series"]): r
        for r in v.iter_rows(named=True)
    }
    for row in data["validation"]:
        assert len(row) == 5
        r = by_label[row[0]]
        assert row[2] == round(r["correlation"], 2) and row[3] == round(
            r["threshold"], 2
        )
        assert row[4] == ("info" if r["series"] in NOT_A_JOIN_TEST else "join")


def test_info_rows_are_the_two_composites_and_come_last(data):
    kinds = [row[4] for row in data["validation"]]
    assert set(kinds) == {"join", "info"}
    assert kinds == ["join"] * kinds.count("join") + ["info"] * 2
    assert [row[0] for row in data["validation"] if row[4] == "info"] == [
        site.SERIES_LABELS["value"],
        site.SERIES_LABELS["quality"],
    ]
    # An info row's correlation against its bar is not a verdict; the
    # dot the template draws for a join row is what would have called
    # both of them "fail".
    assert all(row[2] < row[3] for row in data["validation"] if row[4] == "info")


def test_template_draws_a_verdict_for_join_rows_and_n_a_for_info(repo_root: Path):
    html = (repo_root / site.TEMPLATE).read_text(encoding="utf-8")
    val = html[html.index('$("tb_val")') :].split("\n\n")[0]
    assert 'r[4]==="join"' in val
    assert '<span class="na">n/a</span>' in val
    assert "join test" in html and "vs French" not in html


def test_trial_counts_are_the_spec_log_not_an_argument(cfg, repo_root: Path, data):
    from backtester import speclog

    spec = repo_root / cfg.specifications
    assert data["n_specs"] == speclog.count_trials(spec)
    assert data["n_candidates"] == speclog.count_trials(spec, "candidate")
    assert data["n_specs"] > data["n_candidates"] > 0


def test_history_is_one_point_per_code_version_labelled_by_commit(cfg, repo_root, data):
    """A point per distinct commit, labelled by its short hash; a row
    logged before the commit column existed is labelled by its spec-log
    row number (1-based, the header not counted, as CLAUDE.md cites)."""
    from backtester import speclog

    h = data["history"]
    assert h["label"] == site.HISTORY_LABEL
    assert len(h["commits"]) == len(h["values"]) >= 2
    assert len(set(h["commits"])) == len(h["commits"])
    rows = speclog.read(repo_root / cfg.specifications)
    for label in h["commits"]:
        if m := re.fullmatch(r"row (\d+)", label):
            r = rows[int(m.group(1)) - 1]
            assert r["factor"] == "quality" and r["git_commit"] == ""
        else:
            assert re.fullmatch(r"[0-9a-f]{7}", label), label
            assert any(r["git_commit"].startswith(label) for r in rows)


def test_gap_is_one_bar_per_year(cfg, repo_root: Path, data):
    """December for every complete year; for the current one the coverage
    check's last month, which is the last month with a forward return,
    not the window's end."""
    assert data["gap_years"][0] == cfg.start.year
    assert data["gap_years"][-1] == cfg.end.year
    assert len(data["gap_years"]) == len(data["gap_pct"])
    assert all(0 <= g <= 100 for g in data["gap_pct"])
    cov = pl.read_csv(
        repo_root / cfg.data / "checks" / "price_coverage_monthly.csv",
        try_parse_dates=True,
    ).sort("month")
    for year, gap in zip(data["gap_years"][:-1], data["gap_pct"][:-1], strict=True):
        dec = cov.filter(pl.col("month") == pl.date(year, 12, 31))
        assert dec.height == 1 and gap == round(dec["gap_pct"][0], 1)
    last = cov.row(-1, named=True)
    assert last["month"] < cfg.end and last["n_fwd_return"] > 0
    assert data["gap_pct"][-1] == round(last["gap_pct"], 1)


def test_current_year_bar_is_the_latest_month_not_december(tmp_path: Path):
    """A complete year contributes December; a partial year its last
    month; a complete year without a December is a truncated file."""
    rows = ["month,n_members,n_priced,n_fwd_return,gap_pct"]
    rows += [f"2024-{m:02d}-28,500,{500 - m},1,{m / 5:.1f}" for m in range(1, 13)]
    rows += [f"2025-{m:02d}-28,500,{500 - m},1,{m / 5 + 10:.1f}" for m in range(1, 4)]
    path = tmp_path / "cov.csv"
    path.write_text("\n".join(rows) + "\n")
    years, gap = site._gap_by_year(path)
    assert years == [2024, 2025]
    assert gap == [2.4, 10.6]  # December 2024, March 2025
    truncated = tmp_path / "truncated.csv"
    truncated.write_text(
        "\n".join(rows[:12] + rows[13:]) + "\n"
    )  # 2024 ends in November
    with pytest.raises(ValueError, match="December"):
        site._gap_by_year(truncated)


def test_script_cannot_be_closed_early_by_the_data():
    html = site.render(
        "<script>const DATA = __DATA_JSON__;\n__IMG_DECILES__ __IMG_IC__</script>",
        {"answer": "a </script> in the text"},
        "d",
        "i",
    )
    assert "</script> in" not in html and "<\\/script> in" in html
