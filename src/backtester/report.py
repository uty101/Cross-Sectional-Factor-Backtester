"""The four charts, the results table, the validation and sensitivity tables.

Writes reports/results.md and reports/figures/. The README is updated by
hand from results.md so that every number is looked at before it is
published; no number in the README is typed from memory.

    chart 1   cumulative log returns of deciles 1-10, one panel per factor
    chart 2   rolling 36-month IC, zero line, shaded recessions
    chart 3   IC decay by horizon with the fitted half-life
    chart 4   net Sharpe against assumed cost, crossing zero at break-even

Everything is read back from data/processed, so a report is a pure
function of saved runs and the specification log.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from backtester import speclog, stats
from backtester.config import Config
from backtester.run import FACTORS, REPORTED, load_inputs, member_panel

LABELS = {
    "momentum": "Momentum 12-1",
    "value": "Value (B/P, E/P)",
    "quality": "Quality (GP/A, accruals)",
    "low_vol": "Low volatility",
    "composite": "Composite",
    "text_change": "10-K text similarity",
}
# Categorical slots, fixed order, validated (dataviz skill). Text stays ink.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#7a5cd6"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
# The fallback when FRED USREC has not been fetched; otherwise every NBER
# recession in the window is read from data/interim/fred_usrec.parquet.
RECESSIONS = [(date(2020, 2, 1), date(2020, 4, 30))]


def recession_spans(cfg: Config) -> list[tuple[date, date]]:
    from backtester.benchmarks import recessions

    p = cfg.data / "interim" / "fred_usrec.parquet"
    if not p.exists():
        return RECESSIONS
    spans = recessions(pl.read_parquet(p).select("date", "rate_pct"))
    in_window = [
        (a, pl.Series([b]).dt.month_end()[0])  # FRED stamps the first of the month
        for a, b in spans
        if b >= cfg.start and a <= cfg.end
    ]
    return in_window or RECESSIONS


HORIZONS = [1, 2, 3, 6, 12]
COST_GRID = list(range(0, 101, 1))
# The cost table's columns; results.csv and the site read the same ones.
COST_TABLE_BPS = [0, 5, 10, 25, 50]
# Validation rows that are not join tests: the reported composites, two
# sector-neutral signals against a raw one-signal French factor. The
# results table marks them and the site renders them as information.
NOT_A_JOIN_TEST = frozenset({"value", "quality"})
# Saved variants of every reported factor: the long_short_<factor>_<tag>
# parquet each sensitivity run writes, and the column it is printed under.
VARIANTS = [
    ("cw", "Cap-weighted"),
    ("hold3", "Hold 3m"),
    ("hold6", "Hold 6m"),
    ("hold12", "Hold 12m"),
    ("nosector", "No sector neutralisation"),
    ("terminal", "Delisting: terminal return"),
    ("hedged", "Beta-hedged"),
]


@dataclass
class FactorReport:
    factor: str
    long_short: pl.DataFrame
    deciles: pl.DataFrame
    ic: pl.DataFrame
    decay: pl.DataFrame
    half_life: float
    row: dict
    attribution: stats.Attribution
    validation: dict


# --- per factor ---------------------------------------------------------


# A half-life is a property of an IC that is there. Under |t| < 1.96 at
# h=1 the mean IC is not distinguishable from zero, so the table prints
# n/a and the chart draws no fitted curve (FIX_PLAN_2 G3).
IC_T_MIN = 1.96
# Factors whose signal excludes Financials by rule (gross profitability,
# as Novy-Marx does): coverage is reported against non-financial members.
NON_FINANCIAL = {"quality", "quality_ttm"}
COVERAGE_FOOTNOTE = (
    "¹ Quality is computed on {pct}% of non-financial members in a typical month: "
    "gross profitability needs a cost-of-goods line and the rest do not tag one "
    "(decisions/tag_coverage_f3.md); financials are excluded by rule, as in Novy-Marx. "
    "Coverage is the median across months of the share of members with a signal."
)


def coverage(
    z: pl.DataFrame, members: pl.DataFrame, sectors: pl.DataFrame | None, non_fin: bool
) -> float:
    """Median across months of (members with a finite z) / (members), the
    denominator restricted to non-financials when the signal excludes them.
    This is what the signal was computed on, read off the saved z frame,
    not the tag coverage the signal was built from."""
    denom = members
    if non_fin and sectors is not None:
        sec = sectors.select("ticker", "sector").unique(subset=["ticker"])
        denom = members.join(sec, on="ticker", how="left").filter(
            pl.col("sector") != "Financials"
        )
    n = denom.group_by("month").len().rename({"len": "n"})
    have = (
        z.filter(pl.col("z").is_finite())
        .join(denom, on=["month", "ticker"], how="inner")
        .group_by("month")
        .len()
        .rename({"len": "have"})
    )
    j = n.join(have, on="month", how="left").with_columns(pl.col("have").fill_null(0))
    if j.height == 0:
        return float("nan")
    return float((j["have"] / j["n"]).median())


def _load(
    cfg: Config, factor: str, tag: str = ""
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    p = cfg.data / "processed"
    s = f"{factor}{('_' + tag) if tag else ''}"
    return (
        pl.read_parquet(p / f"long_short_{s}.parquet"),
        pl.read_parquet(p / f"deciles_{s}.parquet"),
        pl.read_parquet(p / f"signals_z_{s}.parquet"),
    )


def trial_counts(cfg: Config) -> dict:
    """{"all": (N, var), "candidates": (N, var), "rows": runs logged} from
    the specification log. N is the number of *distinct specifications*
    (``speclog.spec_key``): re-running one after a code fix is the same
    trial (FIX_PLAN_2 G2). The variance of the monthly Sharpe is taken
    over one row per key, the latest run. N is never an argument
    (invariant 8); the two counts are the deflated Sharpe's two
    denominators (FIX_PLAN F4)."""
    out: dict = {"rows": speclog.count_specifications(cfg.specifications)}
    for name, kind in (("all", None), ("candidates", "candidate")):
        latest = speclog.latest_per_key(cfg.specifications, kind)
        s = pl.Series(
            [r["sharpe_net"] for r in latest if r["sharpe_net"]], dtype=pl.Utf8
        ).cast(pl.Float64, strict=False)
        var = float((s / math.sqrt(12)).var()) if s.len() > 1 else 0.0
        out[name] = (len(latest), var)
    return out


def factor_report(
    cfg: Config, factor: str, inp, trials: dict[str, tuple[int, float]]
) -> FactorReport:
    ls, dec, z = _load(cfg, factor)
    months = sorted(
        m for m in inp.monthly["month"].unique().to_list() if cfg.start <= m <= cfg.end
    )
    members = member_panel(inp.membership, months)
    returns = inp.monthly.select("month", "ticker", "ret_fwd").join(
        members, on=["month", "ticker"], how="inner"
    )

    ic = stats.ic_series(z, returns)
    ics = stats.ic_summary(ic)
    decay, hl = stats.ic_decay(
        z, inp.monthly.join(members, on=["month", "ticker"], how="inner"), HORIZONS
    )
    if abs(ics["ic_t"]) < IC_T_MIN:
        hl = float("nan")  # no IC at h=1, so nothing to fit a decay to
    fm = stats.fama_macbeth(z, returns, lags=max(cfg.holding_months - 1, 0))
    att = stats.attribution(ls, inp.french, lags=max(cfg.holding_months - 1, 0))

    g, n = ls["ret_gross"].to_numpy(), ls["ret_net"].to_numpy()
    ann_g, vol = stats.annualised(g)
    ann_n, _ = stats.annualised(n)
    sr_net = stats.sharpe(n)
    skew, kurt = stats.moments(n)
    n_all, var_all = trials["all"]
    n_cand, var_cand = trials["candidates"]
    sr0, dsr = stats.deflated_sharpe(
        sr_net / math.sqrt(12), var_all, n_all, len(n), skew, kurt
    )
    _, dsr_cand = stats.deflated_sharpe(
        sr_net / math.sqrt(12), var_cand, n_cand, len(n), skew, kurt
    )
    french = FACTORS[factor]["french"]
    val = {"french": french, "corr": None, "months": 0}
    if french:
        from backtester.run import validate

        val = validate(ls, inp.french, french)
    row = {
        "factor": LABELS.get(factor, factor),
        "gross_ann": ann_g,
        "net_ann": ann_n,
        "vol": vol,
        "sharpe_net": sr_net,
        "sharpe_gross": stats.sharpe(g),
        "dsr": dsr,
        "dsr_candidates": dsr_cand,
        "sr0_monthly": sr0,
        "max_dd": stats.max_drawdown(n),
        "turnover": float(ls["turnover"].mean()),
        "mean_ic": ics["mean_ic"],
        "ic_t": ics["ic_t"],
        "ic_ir": ics["ic_ir"],
        "fm_premium": fm.mean,
        "fm_t": fm.t,
        "breakeven_bps": stats.breakeven_cost(ls) * 1e4,
        "half_life": hl,
        "months": len(n),
        "coverage": coverage(z, members, inp.sectors, factor in NON_FINANCIAL),
        "coverage_of": "non-fin." if factor in NON_FINANCIAL else "members",
    }
    return FactorReport(factor, ls, dec, ic, decay, hl, row, att, val)


# --- tables -------------------------------------------------------------


def _f(x: float | None, nd: int = 2, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{100 * x:.{nd}f}%" if pct else f"{x:.{nd}f}"


def _be(x: float) -> str:
    if math.isnan(x):
        return "n/a"
    return "none (loses gross)" if x < 0 else f"{x:.0f} bp"


def results_table(reports: list[FactorReport]) -> str:
    head = (
        "| Factor | Gross ann. | Net ann. | Vol | Sharpe (net) | DSR (all) | DSR (cand.) | Max DD | "
        "Turnover | Mean IC | IC t-stat | Break-even cost | Coverage |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for r in reports:
        x = r.row
        rows.append(
            f"| {x['factor']} | {_f(x['gross_ann'], 1, True)} | {_f(x['net_ann'], 1, True)} | "
            f"{_f(x['vol'], 1, True)} | {_f(x['sharpe_net'])} | {_f(x['dsr'])} | "
            f"{_f(x['dsr_candidates'])} | "
            f"{_f(x['max_dd'], 0, True)} | {_f(x['turnover'])} | {_f(x['mean_ic'], 3)} | "
            f"{_f(x['ic_t'], 1)} | {_be(x['breakeven_bps'])} | {_cov(r)} |"
        )
    return head + "\n".join(rows) + "\n"


def _cov(r: FactorReport) -> str:
    """ "87%" for a signal on all members; "66% of non-fin.¹" when the
    signal excludes financials by rule, the mark pointing at the footnote."""
    x = r.row
    cell = _f(x["coverage"], 0, True)
    if x["coverage_of"] != "members":
        cell += f" of {x['coverage_of']}{FOOTNOTE_MARK}"
    return cell


FOOTNOTE_MARK = "¹"


def coverage_footnote(reports: list[FactorReport]) -> str:
    """The one-line COGS footnote under a table that has quality in it."""
    q = [r for r in reports if r.factor in NON_FINANCIAL]
    if not q:
        return ""
    return COVERAGE_FOOTNOTE.format(pct=f"{100 * q[0].row['coverage']:.0f}") + "\n"


def validation_table(cfg: Config, inp) -> str:
    """The six-row validation table (FIX_PLAN F8): momentum against UMD,
    the two French replications against the big-cap legs of HML and RMW
    (the like-for-like series), low beta raw and beta-hedged against BAB,
    and the reported value and quality composites against HML and RMW,
    marked as not a join test. Bars are config.toml [validation]."""
    from backtester.run import validate

    bars = dict(cfg.validation)
    rows = [
        ("momentum", "", "umd", "UMD", bars.get("momentum")),
        ("hml_replica", "", "big_hml", "HML, big-cap leg", bars.get("hml_replica")),
        ("rmw_replica", "", "big_rmw", "RMW, big-cap leg", bars.get("rmw_replica")),
        ("beta", "", "bab", "BAB (AQR)", bars.get("beta")),
        ("beta", "hedged", "bab", "BAB (AQR)", bars.get("beta_hedged")),
        ("value", "", "hml", "HML", bars.get("value")),
        ("quality", "", "rmw", "RMW", bars.get("quality")),
    ]
    out = "| Series | Against | Correlation | Months | Bar | |\n|---|---|---|---|---|---|\n"
    for f, tag, col, name, bar in rows:
        sfx = f"_{tag}" if tag else ""
        path = cfg.data / "processed" / f"long_short_{f}{sfx}.parquet"
        if not path.exists() or col not in inp.french.columns:
            continue
        v = validate(pl.read_parquet(path), inp.french, col)
        label = {
            "momentum": "Momentum 12-1 long-short",
            "hml_replica": "B/P, cap-weighted terciles (French's construction)",
            "rmw_replica": "Pre-tax income / FY equity, cap-weighted terciles (French's construction)",
            "beta": "Low beta long-short" + (", beta-hedged" if tag else ", raw"),
            "value": "Value (B/P, E/P) long-short, sector-neutral",
            "quality": "Quality (GP/A, accruals) long-short, sector-neutral",
        }[f]
        verdict = ""
        if bar is not None and v["corr"] is not None:
            verdict = "pass" if v["corr"] >= bar else "**fail**"
        note = (
            verdict
            if f not in NOT_A_JOIN_TEST
            else "not a join test: a two-signal sector-neutral composite against a raw one-signal factor"
        )
        out += (
            f"| {label} | {name} | {_f(v['corr'], 3)} | {v['months']} | "
            f"{'> ' + f'{bar:.1f}' if bar is not None else '-'} | {note} |\n"
        )
    return out


def attribution_table(reports: list[FactorReport]) -> str:
    out = "| Factor | Alpha (ann.) | t | Mkt-RF | HML | UMD | RMW | R² |\n|---|---|---|---|---|---|---|---|\n"
    for r in reports:
        a = r.attribution

        def cell(k: str, b: dict = a.betas, t: dict = a.beta_t) -> str:
            return f"{b[k]:.2f} ({t[k]:.1f})"

        mark = FOOTNOTE_MARK if r.factor in NON_FINANCIAL else ""
        out += (
            f"| {LABELS[r.factor]}{mark} | {_f(a.alpha_annual, 1, True)} | {a.alpha_t:.1f} | "
            f"{cell('mkt_rf')} | {cell('hml')} | {cell('umd')} | {cell('rmw')} | {a.r2:.2f} |\n"
        )
    return out


def _half_life(r: FactorReport) -> str:
    if abs(r.row["ic_t"]) < IC_T_MIN:
        return "n/a"
    return "none within 5y" if math.isnan(r.half_life) else _f(r.half_life, 1)


def decay_table(reports: list[FactorReport]) -> str:
    out = (
        "| Factor | "
        + " | ".join(f"IC h={h}" for h in HORIZONS)
        + " | Half-life (months) |\n"
    )
    out += "|---|" + "---|" * (len(HORIZONS) + 1) + "\n"
    for r in reports:
        ics = dict(zip(r.decay["horizon"], r.decay["mean_ic"], strict=True))
        out += (
            f"| {LABELS[r.factor]} | "
            + " | ".join(_f(ics[h], 3) for h in HORIZONS)
            + f" | {_half_life(r)} |\n"
        )
    return out


def cost_table(reports: list[FactorReport], costs: list[float]) -> str:
    out = (
        "| Factor | " + " | ".join(f"{int(c)} bp" for c in costs) + " | Break-even |\n"
    )
    out += "|---|" + "---|" * (len(costs) + 1) + "\n"
    for r in reports:
        s = stats.sharpe_by_cost(r.long_short, costs)
        out += (
            f"| {LABELS[r.factor]} | "
            + " | ".join(_f(v) for v in s["sharpe_net"])
            + f" | {_f(r.row['breakeven_bps'], 0)} bp |\n"
        )
    return out


def variant_table(cfg: Config, factors: list[str], tags: list[tuple[str, str]]) -> str:
    """Net Sharpe of the base run and each saved variant."""
    out = (
        "| Factor | Base | "
        + " | ".join(name for _, name in tags)
        + " |\n|---|---|"
        + "---|" * len(tags)
        + "\n"
    )
    for f in factors:
        cells = [_f(stats.sharpe(_load(cfg, f)[0]["ret_net"]))]
        for tag, _ in tags:
            path = cfg.data / "processed" / f"long_short_{f}_{tag}.parquet"
            if path.exists():
                cells.append(_f(stats.sharpe(pl.read_parquet(path)["ret_net"])))
            else:
                cells.append("n/a")
        out += f"| {LABELS[f]} | " + " | ".join(cells) + " |\n"
    return out


def hedge_table(cfg: Config, inp) -> str:
    """Low volatility and low beta, raw and beta-hedged (FIX_PLAN F5):
    net Sharpe, the market beta of each series, and the correlation with
    AQR's BAB, which is beta-neutral by construction."""
    from backtester.run import validate

    out = (
        "| Series | Net Sharpe | Market beta (t) | Corr. with BAB | Months |\n"
        "|---|---|---|---|---|\n"
    )
    for f in ("low_vol", "beta"):
        for tag, name in (("", "raw"), ("hedged", "beta-hedged")):
            sfx = f"_{tag}" if tag else ""
            path = cfg.data / "processed" / f"long_short_{f}{sfx}.parquet"
            if not path.exists():
                continue
            ls = pl.read_parquet(path)
            a = stats.attribution(ls, inp.french)
            v = validate(ls, inp.french, "bab")
            label = "Low volatility" if f == "low_vol" else "Low beta"
            out += (
                f"| {label}, {name} | {_f(stats.sharpe(ls['ret_net']))} | "
                f"{a.betas['mkt_rf']:.2f} ({a.beta_t['mkt_rf']:.1f}) | "
                f"{_f(v['corr'])} | {v['months']} |\n"
            )
    return out


def _variant_sharpe(cfg: Config, factor: str, tag: str) -> float:
    path = cfg.data / "processed" / f"long_short_{factor}_{tag}.parquet"
    if not path.exists():
        return float("nan")
    return stats.sharpe(pl.read_parquet(path)["ret_net"])


def results_frame(cfg: Config, reports: list[FactorReport]) -> pl.DataFrame:
    """One row per reported factor with every number the tables print:
    the results row, the attribution, the IC at each horizon, the net
    Sharpe at each cost in ``COST_TABLE_BPS`` and under each saved
    variant. Written to reports/results.csv so the site (FIX_PLAN_4 J2)
    is a function of the report's outputs, not a second computation."""
    rows = []
    for r in reports:
        a = r.attribution
        ics = dict(zip(r.decay["horizon"], r.decay["mean_ic"], strict=True))
        by_cost = stats.sharpe_by_cost(r.long_short, COST_TABLE_BPS)
        row: dict = {"key": r.factor, **r.row}
        row.update(
            {
                "alpha_ann": a.alpha_annual,
                "alpha_t": a.alpha_t,
                **{f"beta_{k}": a.betas[k] for k in ("mkt_rf", "hml", "umd", "rmw")},
                "r2": a.r2,
                **{f"ic_h{h}": ics[h] for h in HORIZONS},
                **{
                    f"sharpe_at_{int(c)}bp": s
                    for c, s in zip(COST_TABLE_BPS, by_cost["sharpe_net"], strict=True)
                },
                **{
                    f"sharpe_{tag}": _variant_sharpe(cfg, r.factor, tag)
                    for tag, _ in VARIANTS
                },
            }
        )
        rows.append(row)
    return pl.DataFrame(rows)


def exclusions_frame(cfg: Config, inp, months: list[date]) -> pl.DataFrame:
    """The price-identity exclusions (FIX_PLAN_3 H1/H2) in one row: windows
    listed, names, member-months inside a window, and how many of those
    had a price (a row in the monthly return panel), which is the count
    that can move a portfolio."""
    from backtester import identity
    from backtester.run import member_panel

    ex = inp.exclusions
    if ex is None:
        ex = identity.load_exclusions(cfg)
    hit = identity.excluded_months(ex, months).join(
        member_panel(inp.membership, months), on=["month", "ticker"], how="inner"
    )
    priced = hit.join(
        inp.monthly.select("month", "ticker"), on=["month", "ticker"], how="inner"
    )
    return pl.DataFrame(
        {
            "windows": [ex.height],
            "names": [ex["ticker"].n_unique() if ex.height else 0],
            "member_months": [hit.height],
            "priced_member_months": [priced.height],
        }
    )


def coverage_split_table(
    cfg: Config, reports: list[FactorReport], max_gap_pct: float = 20.0
) -> str:
    """Net Sharpe on all months and on the months where price coverage is good."""
    cov = pl.read_csv(
        cfg.data / "checks" / "price_coverage_monthly.csv", try_parse_dates=True
    )
    good = set(cov.filter(pl.col("gap_pct") <= max_gap_pct)["month"].to_list())
    first_good = min(good) if good else None
    out = f"| Factor | All months | Months with price gap <= {max_gap_pct:.0f}% (from {first_good}) |\n|---|---|---|\n"
    for r in reports:
        sub = r.long_short.filter(pl.col("month").is_in(list(good)))
        out += f"| {LABELS[r.factor]} | {_f(stats.sharpe(r.long_short['ret_net']))} ({r.long_short.height}) | {_f(stats.sharpe(sub['ret_net']))} ({sub.height}) |\n"
    return out


# --- charts -------------------------------------------------------------


def _style(ax) -> None:
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.title.set_color(INK)
    ax.yaxis.label.set_color(INK2)
    ax.xaxis.label.set_color(INK2)


def chart_deciles(reports: list[FactorReport], path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import colormaps

    n = len(reports)
    cols = min(3, n)
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.4 * cols, 3.6 * rows), sharey=True)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[n:]:
        ax.set_visible(False)
    cmap = colormaps["Blues"]
    for ax, r in zip(axes[:n], reports, strict=True):
        d = r.deciles.sort("decile", "month")
        ndec = int(d["decile"].max())
        for k in range(1, ndec + 1):
            s = d.filter(pl.col("decile") == k)
            cum = np.log1p(s["ret_gross"].to_numpy()).cumsum()
            months = s["month"].to_list()
            ax.plot(
                months,
                cum,
                color=cmap(0.25 + 0.7 * (k - 1) / (ndec - 1)),
                linewidth=1.2,
            )
            if k in (1, ndec):
                ax.annotate(
                    f"D{k}",
                    (months[-1], cum[-1]),
                    fontsize=8,
                    color=INK2,
                    xytext=(3, 0),
                    textcoords="offset points",
                    va="center",
                )
        ax.set_title(LABELS[r.factor], fontsize=10)
        _style(ax)
    for ax in axes[::cols]:
        ax.set_ylabel("cumulative log return (gross)")
    fig.suptitle(
        "Decile portfolios, equal-weighted, formed monthly (D1 lowest score, D10 highest)",
        fontsize=10,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_rolling_ic(
    reports: list[FactorReport],
    path,
    window: int = 36,
    spans: list[tuple[date, date]] = RECESSIONS,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4))
    for i, r in enumerate(reports):
        ic = r.ic.sort("month")
        roll = ic["ic"].rolling_mean(window_size=window, min_samples=window)
        months = ic["month"].to_list()
        ax.plot(
            months,
            roll.to_numpy(),
            color=SERIES[i % len(SERIES)],
            linewidth=1.6,
            label=LABELS[r.factor],
        )
        last = roll.drop_nulls()
        if last.len():
            ax.annotate(
                LABELS[r.factor],
                (months[-1], last[-1]),
                fontsize=8,
                color=INK2,
                xytext=(3, 0),
                textcoords="offset points",
                va="center",
            )
    for a, b in spans:
        ax.axvspan(a, b, color=GRID, alpha=0.8, linewidth=0)
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.set_title(
        f"Rolling {window}-month mean rank IC (shaded: NBER recession)", fontsize=10
    )
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_decay(reports: list[FactorReport], path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    hs = np.linspace(1, 12, 100)
    for i, r in enumerate(reports):
        c = SERIES[i % len(SERIES)]
        ax.plot(
            r.decay["horizon"].to_numpy(),
            r.decay["mean_ic"].to_numpy(),
            "o",
            color=c,
            markersize=7,
            label=LABELS[r.factor],
        )
        if not math.isnan(r.half_life):
            tau = r.half_life / math.log(2)
            a = r.decay["mean_ic"][0] * math.exp(1 / tau)
            ax.plot(hs, a * np.exp(-hs / tau), color=c, linewidth=1.2, alpha=0.8)
            ax.annotate(
                f"half-life {r.half_life:.1f}m",
                (12, a * math.exp(-12 / tau)),
                fontsize=8,
                color=INK2,
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
            )
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("horizon h (months ahead)")
    ax.set_ylabel("mean rank IC with the return in month t+h")
    ax.set_title("IC decay by horizon with an exponential fit", fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_cost(reports: list[FactorReport], path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    for i, r in enumerate(reports):
        c = SERIES[i % len(SERIES)]
        s = stats.sharpe_by_cost(r.long_short, COST_GRID)
        ax.plot(
            s["cost_bps"].to_numpy(),
            s["sharpe_net"].to_numpy(),
            color=c,
            linewidth=1.6,
            label=LABELS[r.factor],
        )
        be = r.row["breakeven_bps"]
        if not math.isnan(be) and 0 <= be <= COST_GRID[-1]:
            ax.plot([be], [0], "o", color=c, markersize=6)
            ax.annotate(
                f"{be:.0f} bp",
                (be, 0),
                fontsize=8,
                color=INK2,
                xytext=(3, 6),
                textcoords="offset points",
            )
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("assumed one-way cost (bp), every dollar bought or sold")
    ax.set_ylabel("net Sharpe (annualised)")
    ax.set_title("Net Sharpe against cost; the marker is the break-even", fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


# --- entry --------------------------------------------------------------


def build(cfg: Config, factors: list[str] = REPORTED) -> str:
    inp = load_inputs(cfg)
    trials = trial_counts(cfg)
    (n_trials, sr_var), (n_cand, sr_var_cand) = trials["all"], trials["candidates"]

    reports = [
        factor_report(cfg, f, inp, trials)
        for f in factors
        if (cfg.data / "processed" / f"long_short_{f}.parquet").exists()
    ]
    # The headline table is the five factors the brief asked for; the
    # 10-K text factor is an appendix (FIX_PLAN F8).
    headline = [r for r in reports if r.factor != "text_change"]
    appendix = [r for r in reports if r.factor == "text_change"]
    cov = pl.read_csv(cfg.data / "checks" / "price_coverage_summary.csv")
    gap = float(cov.filter(pl.col("metric") == "gap_pct")["value"][0])
    figs = cfg.reports / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    chart_deciles(headline, figs / "chart1_deciles.png")
    chart_rolling_ic(
        headline, figs / "chart2_rolling_ic.png", spans=recession_spans(cfg)
    )
    chart_decay(headline, figs / "chart3_ic_decay.png")
    chart_cost(headline, figs / "chart4_sharpe_vs_cost.png")

    tags = VARIANTS
    md = [
        f"# Results\n\nGenerated by `backtester report`. Window {cfg.start} to {cfg.end}; "
        f"base cost {cfg.base_bps:.0f} bp one-way on every dollar traded; weighting {cfg.weighting}; "
        f"execution lag {cfg.lag_days} trading day; deciles {cfg.n_deciles}; "
        f"N = {n_trials} distinct specifications ({trials['rows']} runs logged); "
        f"{n_cand} candidates. The candidate count is a floor: diagnostic runs informed "
        f"which specifications became candidates. Variance of monthly Sharpe across the "
        f"latest run of each: {sr_var:.4f} all, {sr_var_cand:.4f} candidates.\n",
        "## Results table\n",
        results_table(headline),
        "\n" + coverage_footnote(headline),
        f"\nPrice history covers {100 - gap:.1f}% of member-months; the missing names are "
        "disproportionately those that left the index. See Data.\n",
        "\nDSR is the deflated Sharpe: the probability that the net Sharpe exceeds the expected maximum "
        "of N random trials with the same dispersion, adjusted for skew and kurtosis. A trial is a distinct "
        "specification key (factor, signal, weighting, cost, lag, holding period, winsorisation, deciles, "
        "sector flag, window, variant); re-running one after a code fix is the same trial. DSR (all) counts "
        "every distinct specification in the log; DSR (cand.) counts the candidate ones only (a sensitivity, "
        "a replication or a diagnostic is not a candidate for the table). Break-even cost is the "
        "one-way cost at which the mean net return is zero.\n",
        "## Validation against Ken French and AQR\n",
        validation_table(cfg, inp),
        "\n## Attribution (long-short on Mkt-RF, HML, UMD, RMW; t-stats in brackets)\n",
        attribution_table(headline),
        "\n## IC decay\n",
        decay_table(headline),
        f"\nHalf-life is n/a where the h=1 IC t-stat is under {IC_T_MIN} in absolute value: "
        "there is no IC to decay. The chart draws a fitted curve only where one is printed.\n",
        "\n## Net Sharpe by assumed cost\n",
        cost_table(headline, COST_TABLE_BPS),
        "\n## Variants (net Sharpe)\n",
        variant_table(cfg, [r.factor for r in headline], tags),
        "\nCap-weighted runs hold only the names with a market cap (39% of members in "
        "2010, 86% in 2023); the equal-weighted base holds every name with a signal.\n",
        "\n## Beta-hedged low volatility and low beta\n",
        hedge_table(cfg, inp),
        "\nThe hedge is the rolling 36-month beta to Mkt-RF estimated on months strictly before the "
        "formation month, applied to the next month's Mkt-RF (portfolio.beta_hedge); the first 24 "
        "months have no beta and are dropped. BAB is beta-neutral by construction, so the hedged row "
        "is the like-for-like comparison; the bar in config.toml is 0.5 for both.\n",
        "\n## With and without the badly covered months\n",
        coverage_split_table(cfg, headline),
        "\n## Fama-MacBeth premia (per unit z, monthly) and IC information ratio\n",
        "| Factor | Premium | t (NW) | IC IR |\n|---|---|---|---|\n"
        + "".join(
            f"| {r.row['factor']} | {_f(r.row['fm_premium'], 2, True)} | {_f(r.row['fm_t'], 1)} | {_f(r.row['ic_ir'])} |\n"
            for r in headline
        ),
        "\n## Charts\n",
        "![deciles](figures/chart1_deciles.png)\n![rolling IC](figures/chart2_rolling_ic.png)\n"
        "![IC decay](figures/chart3_ic_decay.png)\n![Sharpe vs cost](figures/chart4_sharpe_vs_cost.png)\n",
    ]
    if appendix:
        md += [
            "\n## Appendix: text factor\n",
            "Year-on-year similarity of the 10-K text (Cohen, Malloy and Nguyen 2020), long the "
            "names whose filing changed least. Built for the data path (EDGAR primary documents, "
            "filing-dated, deterministic scorer); not one of the five factors the brief asked for.\n",
            results_table(appendix),
            "\n" + coverage_footnote(appendix),
            "\nAttribution:\n",
            attribution_table(appendix),
            "\nVariants (net Sharpe):\n",
            variant_table(cfg, ["text_change"], tags + [("jaccard", "Jaccard scorer")]),
        ]
    text = "\n".join(md)
    (cfg.reports / "results.md").write_text(text, encoding="utf-8", newline="\n")
    from backtester.run import validation_table as validation_csv

    validation_csv(cfg, inp).write_csv(cfg.reports / "validation.csv")
    results_frame(cfg, headline).write_csv(cfg.reports / "results.csv")
    months = sorted(
        m for m in inp.monthly["month"].unique().to_list() if cfg.start <= m <= cfg.end
    )
    exclusions_frame(cfg, inp, months).write_csv(cfg.reports / "exclusions.csv")
    weighting_gap_table(cfg, [r.factor for r in reports], inp).write_csv(
        cfg.reports / "weighting_gap.csv"
    )
    return text


def weighting_gap_table(cfg: Config, factors: list[str], inp) -> pl.DataFrame:
    """Per factor with both a base and a cap-weighted run: the equal-minus-
    cap spread on SMB (BUILD_PLAN 8.3)."""
    rows = []
    for f in factors:
        cw = cfg.data / "processed" / f"long_short_{f}_cw.parquet"
        if not cw.exists():
            continue
        eq = pl.read_parquet(cfg.data / "processed" / f"long_short_{f}.parquet")
        a = stats.weighting_gap(
            eq, pl.read_parquet(cw), inp.french, lags=max(cfg.holding_months - 1, 0)
        )
        rows.append(
            {
                "factor": f,
                "alpha_ann": round(a.alpha_annual, 4),
                "alpha_t": round(a.alpha_t, 2),
                "beta_smb": round(a.betas["smb"], 3),
                "t_smb": round(a.beta_t["smb"], 2),
                "r2": round(a.r2, 3),
                "months": a.months,
            }
        )
    return pl.DataFrame(rows)


def site(cfg: Config, root=None):
    """docs/index.html from this report's outputs (FIX_PLAN_4 J2)."""
    from pathlib import Path

    from backtester import site as _site

    return _site.build(cfg, Path(root) if root is not None else Path("."))
