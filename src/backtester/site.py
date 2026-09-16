"""The one-page results site (FIX_PLAN_4 J2): docs/index.html.

``report/site_template.html`` is the page; it renders one ``DATA``
object and two images. ``report/site_data_schema.txt`` is a filled
example of that object and is the schema: every key in it is produced
here (``test_site`` checks). The page is a function of what ``backtester
report`` already wrote (results.csv, validation.csv, exclusions.csv, the
charts, answer.md), the README's what-did-not-work bullets, the
specification log and the coverage check, so no number on it is a second computation.

    build(cfg, root)   -> docs/index.html, methodology.pdf, results.md
    data(cfg, root)    -> the DATA dict
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
from pathlib import Path

import polars as pl

from backtester import speclog
from backtester.config import Config
from backtester.report import COST_TABLE_BPS, HORIZONS

REPO = "uty101/Cross-Sectional-Factor-Backtester"
REPO_URL = f"https://github.com/{REPO}"
PAGES_URL = f"https://{REPO.split('/')[0].lower()}.github.io/{REPO.split('/')[1]}/"
UNIVERSE = "S&P 500, point-in-time membership"
TEMPLATE = Path("report") / "site_template.html"
SCHEMA = Path("report") / "site_data_schema.txt"
# The page's five cards, in the template's colour slots.
KEYS = {"momentum": "m", "value": "v", "quality": "q", "low_vol": "l", "composite": "c"}
SHORT = {
    "momentum": "Momentum 12-1",
    "value": "Value",
    "quality": "Quality",
    "low_vol": "Low volatility",
    "composite": "Composite",
}
# Each factor's own join test in validation.csv: the row that tests the
# pipeline that built it, not the composite against a one-signal factor.
# Low volatility has no French factor; its like-for-like row is the
# beta-hedged low-beta series against AQR's BAB (results.md, F5). The
# composite has none.
JOIN_TEST = {
    "momentum": "momentum",
    "value": "hml_replica",
    "quality": "rmw_replica",
    "low_vol": "beta_hedged",
    "composite": None,
}
SERIES_LABELS = {
    "momentum": "Momentum long–short",
    "hml_replica": "B/P, cap-wt terciles",
    "rmw_replica": "Pre-tax profit / book, cap-wt terciles",
    "beta": "Low beta long–short",
    "beta_hedged": "Low beta long–short, beta-hedged",
    "value": "Value composite (not a join test)",
    "quality": "Quality composite (not a join test)",
}
BENCHMARK_LABELS = {
    "umd": "French UMD",
    "hml": "French HML",
    "rmw": "French RMW",
    "big_hml": "French HML, big-cap leg",
    "big_rmw": "French RMW, big-cap leg",
    "bab": "AQR BAB (US)",
}
# (column header, results.csv variant tag); None is the base run.
VARIANT_COLS = [
    ("Base", None),
    ("Cap-wt", "cw"),
    ("Hold 3m", "hold3"),
    ("Hold 6m", "hold6"),
    ("Hold 12m", "hold12"),
    ("No sector", "nosector"),
    ("Delist {terminal}", "terminal"),
]
GAP_NOTE = (
    "{gap:.1f}% of member-months overall. The missing names are disproportionately "
    "the ones that left the index, so early-window results carry survivorship bias "
    "in a direction the data cannot currently sign."
)
HISTORY_LABEL = "Quality net Sharpe across code versions"
WDNW_HEADING = "## What did not work"
IMAGE_WIDTH, JPEG_QUALITY = 1000, 78
MAX_BYTES = 400_000


def _r(x: float, nd: int) -> float:
    return round(float(x), nd) + 0.0  # -0.0 rounds to 0.0, not "−0.00" on the page


def _pct(x: float, nd: int = 1) -> float:
    return _r(100 * x, nd)


def _be(bps: float) -> str:
    return "none" if bps != bps or bps < 0 else f"{bps:.0f} bp"


def _factor_cards(res: pl.DataFrame, verdicts: dict[str, str]) -> list[dict]:
    out = []
    for r in res.iter_rows(named=True):
        f = r["key"]
        if f not in KEYS:
            continue
        test = JOIN_TEST.get(f)
        out.append(
            {
                "key": KEYS[f],
                "name": r["factor"],
                "gross": _pct(r["gross_ann"]),
                "net": _pct(r["net_ann"]),
                "vol": _pct(r["vol"]),
                "sharpe": _r(r["sharpe_net"], 2),
                "dsr": _r(r["dsr"], 2),
                "dsr_cand": _r(r["dsr_candidates"], 2),
                "mdd": int(round(100 * r["max_dd"])),
                "to": _r(r["turnover"], 2),
                "ic": _r(r["mean_ic"], 3),
                "ict": _r(r["ic_t"], 1),
                "be": _be(r["breakeven_bps"]),
                "cov": int(round(100 * r["coverage"])),
                "val": verdicts.get(test, "n/a") if test else "n/a",
            }
        )
    return out


def _validation(path: Path) -> tuple[list[list], dict[str, str]]:
    """Every row of validation.csv as [series, benchmark, corr, bar] and
    the pass/fail verdict by series."""
    v = pl.read_csv(path)
    rows, verdicts = [], {}
    for r in v.iter_rows(named=True):
        rows.append(
            [
                SERIES_LABELS.get(r["series"], r["series"]),
                BENCHMARK_LABELS.get(r["benchmark"], r["benchmark"]),
                _r(r["correlation"], 2),
                _r(r["threshold"], 2),
            ]
        )
        verdicts[r["series"]] = "pass" if r["passed"] else "fail"
    return rows, verdicts


def _gap_by_year(path: Path) -> tuple[list[int], list[float]]:
    """The last month of each year (December, or the latest month the
    window has for the current year) from price_coverage_monthly.csv."""
    cov = pl.read_csv(path, try_parse_dates=True).sort("month")
    last = (
        cov.with_columns(pl.col("month").dt.year().alias("year"))
        .group_by("year", maintain_order=True)
        .last()
    )
    return last["year"].to_list(), [_r(x, 1) for x in last["gap_pct"].to_list()]


def _bullets(readme: Path, n: int = 5) -> list[str]:
    """The lead sentence of the first ``n`` bullets under the README's
    "What did not work" heading. The plan named reports/what_did_not_work.md,
    but that file is the uninterpreted log, one spec-log row per line (its
    first five are the day-one momentum reruns); the interpretation the
    schema's example bullets have the shape of is the README's section,
    its first sentence the claim. Markdown marks are removed."""
    if not readme.exists():
        return []
    lines = readme.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith(WDNW_HEADING))
    except StopIteration:
        return []
    bullets: list[str] = []
    for ln in lines[start + 1 :]:
        if ln.startswith("## "):
            break
        if ln.startswith("- "):
            bullets.append(ln[2:].strip())
        elif bullets and ln.startswith("  "):
            bullets[-1] += " " + ln.strip()
        if len(bullets) > n:
            break
    out = []
    for b in bullets[:n]:
        plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"", b).replace("`", "")
        plain = plain.replace("**", "")
        out.append(re.split(r"(?<=[.!?])\s+", plain, maxsplit=1)[0].strip())
    return out


def _history(spec_path: Path) -> dict:
    """The quality base specification's net Sharpe at each code version:
    one point per distinct git_commit among its candidate rows, the last
    row logged under that commit. Rows logged before the commit column
    existed (blank) each stand alone."""
    rows = [
        r
        for r in speclog.read(spec_path, "candidate")
        if r["factor"] == "quality" and r["sector_neutral"] == "1" and not r["variant"]
    ]
    points: dict[str, dict] = {}
    for i, r in enumerate(rows):
        points[r["git_commit"] or f"row{i}"] = r
    dates, values = [], []
    for r in points.values():
        dates.append(r["timestamp"][5:10])
        values.append(_r(float(r["sharpe_net"]), 2))
    return {"label": HISTORY_LABEL, "dates": dates, "values": values}


def _recompute(root: Path) -> str:
    drift = sorted((root / "decisions" / "drift").glob("*.md"))
    if not drift:
        return "not run"
    latest = drift[-1]
    ok = "matches within 1e-10" in latest.read_text(encoding="utf-8")
    return f"{'match 1e-10' if ok else 'DRIFT'} ({latest.stem})"


def _exclusions(path: Path) -> str:
    e = pl.read_csv(path).row(0, named=True)
    return (
        f"{e['windows']} ticker-windows over {e['names']} names excluded by the "
        f"public-float and identity checks ({e['priced_member_months']} priced "
        "member-months); list in data/checks/price_identity_exclusions.csv"
    )


def data(cfg: Config, root: Path = Path(".")) -> dict:
    """The DATA object the template renders; every key of the schema."""
    rep = root / cfg.reports
    res = pl.read_csv(rep / "results.csv")
    validation, verdicts = _validation(rep / "validation.csv")
    cards = _factor_cards(res, verdicts)
    keyed = {r["key"]: r for r in res.iter_rows(named=True) if r["key"] in KEYS}
    years, gap = _gap_by_year(root / cfg.data / "checks" / "price_coverage_monthly.csv")
    summary = pl.read_csv(root / cfg.data / "checks" / "price_coverage_summary.csv")
    gap_all = float(summary.filter(pl.col("metric") == "gap_pct")["value"][0])
    spec = root / cfg.specifications
    last_run = max(r["timestamp"] for r in speclog.read(spec))[:10]
    terminal = f"{100 * cfg.delisting_terminal_return:+.0f}%".replace("-", "−")
    return {
        "window": [cfg.start.isoformat(), cfg.end.isoformat()],
        "universe": UNIVERSE,
        "last_run": last_run,
        "n_specs": speclog.count_trials(spec),
        "n_candidates": speclog.count_trials(spec, "candidate"),
        "recompute": _recompute(root),
        "answer": (rep / "answer.md").read_text(encoding="utf-8").strip(),
        "factors": cards,
        "cost_bps": COST_TABLE_BPS,
        "cost_curve": {
            KEYS[f]: [_r(r[f"sharpe_at_{c}bp"], 2) for c in COST_TABLE_BPS]
            for f, r in keyed.items()
        },
        "horizons": HORIZONS,
        "ic_decay": {
            KEYS[f]: [_r(r[f"ic_h{h}"], 3) for h in HORIZONS] for f, r in keyed.items()
        },
        "attribution": [
            [
                SHORT[f],
                _pct(r["alpha_ann"]),
                _r(r["alpha_t"], 1),
                _r(r["beta_mkt_rf"], 2),
                _r(r["beta_hml"], 2),
                _r(r["beta_umd"], 2),
                _r(r["beta_rmw"], 2),
                _r(r["r2"], 2),
            ]
            for f, r in keyed.items()
        ],
        "variant_cols": [c.format(terminal=terminal) for c, _ in VARIANT_COLS],
        "variants": [
            [SHORT[f]]
            + [
                _r(r["sharpe_net"] if tag is None else r[f"sharpe_{tag}"], 2)
                for _, tag in VARIANT_COLS
            ]
            for f, r in keyed.items()
        ],
        "validation": validation,
        "gap_years": years,
        "gap_pct": gap,
        "gap_note": GAP_NOTE.format(gap=gap_all),
        "exclusions": _exclusions(rep / "exclusions.csv"),
        "wdnw": _bullets(root / "README.md"),
        "history": _history(spec),
        "links": {
            "repo": REPO_URL,
            "methodology": "methodology.pdf",
            "results": "results.md",
        },
    }


def schema_keys(root: Path = Path(".")) -> set[str]:
    """The top-level keys of the DATA object in site_data_schema.txt."""
    text = (root / SCHEMA).read_text(encoding="utf-8")
    body = text[text.index("{") :]
    return set(re.findall(r"^\s{2}(\w+):", body, flags=re.M))


def jpeg_data_uri(png: Path) -> str:
    """A PNG re-encoded as a JPEG ``IMAGE_WIDTH`` wide on a white ground."""
    from PIL import Image

    im = Image.open(png)
    bg = Image.new("RGB", im.size, "white")
    bg.paste(im, mask=im.getchannel("A") if im.mode in ("RGBA", "LA") else None)
    h = round(bg.height * IMAGE_WIDTH / bg.width)
    bg = bg.resize((IMAGE_WIDTH, h), Image.LANCZOS)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def render(template: str, payload: dict, deciles: str, ic: str) -> str:
    # The JSON sits inside a <script> tag: the only sequence that can end
    # it early is "</", which JSON lets us spell "<\/".
    js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (
        template.replace("__DATA_JSON__", js)
        .replace("__IMG_DECILES__", deciles)
        .replace("__IMG_IC__", ic)
    )


def build(cfg: Config, root: Path = Path(".")) -> Path:
    """Write docs/index.html and copy methodology.pdf and results.md
    (with its figures) next to it. Returns the page's path."""
    rep = root / cfg.reports
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    payload = data(cfg, root)
    page = render(
        (root / TEMPLATE).read_text(encoding="utf-8"),
        payload,
        jpeg_data_uri(rep / "figures" / "chart1_deciles.png"),
        jpeg_data_uri(rep / "figures" / "chart2_rolling_ic.png"),
    )
    if re.search(r"__[A-Z_]+__", page):
        raise RuntimeError("a template placeholder was not substituted")
    out = docs / "index.html"
    out.write_text(page, encoding="utf-8", newline="\n")
    shutil.copy2(rep / "methodology.pdf", docs / "methodology.pdf")
    shutil.copy2(rep / "results.md", docs / "results.md")
    (docs / "figures").mkdir(exist_ok=True)
    for png in (rep / "figures").glob("*.png"):
        shutil.copy2(png, docs / "figures" / png.name)
    (docs / ".nojekyll").write_text("")
    return out
