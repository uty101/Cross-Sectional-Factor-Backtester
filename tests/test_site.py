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
    assert names == set(res["factor"].to_list())
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


def test_validation_lists_every_row_with_its_bar(cfg, repo_root: Path, data):
    v = pl.read_csv(repo_root / cfg.reports / "validation.csv")
    assert len(data["validation"]) == v.height
    for row, (corr, bar) in zip(
        data["validation"],
        zip(v["correlation"], v["threshold"], strict=True),
        strict=True,
    ):
        assert row[2] == round(corr, 2) and row[3] == round(bar, 2)


def test_trial_counts_are_the_spec_log_not_an_argument(cfg, repo_root: Path, data):
    from backtester import speclog

    spec = repo_root / cfg.specifications
    assert data["n_specs"] == speclog.count_trials(spec)
    assert data["n_candidates"] == speclog.count_trials(spec, "candidate")
    assert data["n_specs"] > data["n_candidates"] > 0


def test_history_is_one_point_per_code_version(data):
    h = data["history"]
    assert h["label"] == site.HISTORY_LABEL
    assert len(h["dates"]) == len(h["values"]) >= 2
    assert all(re.fullmatch(r"\d{2}-\d{2}", d) for d in h["dates"])


def test_gap_is_one_bar_per_year(cfg, data):
    assert data["gap_years"][0] == cfg.start.year
    assert data["gap_years"][-1] == cfg.end.year
    assert len(data["gap_years"]) == len(data["gap_pct"])
    assert all(0 <= g <= 100 for g in data["gap_pct"])


def test_script_cannot_be_closed_early_by_the_data():
    html = site.render(
        "<script>const DATA = __DATA_JSON__;\n__IMG_DECILES__ __IMG_IC__</script>",
        {"answer": "a </script> in the text"},
        "d",
        "i",
    )
    assert "</script> in" not in html and "<\\/script> in" in html
