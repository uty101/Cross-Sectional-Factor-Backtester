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

from backtester import portfolio, stats
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
RECESSIONS = [(date(2020, 2, 1), date(2020, 4, 30))]  # NBER, inside the window
HORIZONS = [1, 2, 3, 6, 12]
COST_GRID = list(range(0, 101, 1))


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


def factor_report(
    cfg: Config, factor: str, inp, n_trials: int, sr_var: float
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
    fm = stats.fama_macbeth(z, returns, lags=max(cfg.holding_months - 1, 0))
    att = stats.attribution(ls, inp.french, lags=max(cfg.holding_months - 1, 0))

    g, n = ls["ret_gross"].to_numpy(), ls["ret_net"].to_numpy()
    ann_g, vol = stats.annualised(g)
    ann_n, _ = stats.annualised(n)
    sr_net = stats.sharpe(n)
    skew, kurt = stats.moments(n)
    sr0, dsr = stats.deflated_sharpe(
        sr_net / math.sqrt(12), sr_var, n_trials, len(n), skew, kurt
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
        "| Factor | Gross ann. | Net ann. | Vol | Sharpe (net) | DSR | Max DD | "
        "Turnover | Mean IC | IC t-stat | Break-even cost |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for r in reports:
        x = r.row
        rows.append(
            f"| {x['factor']} | {_f(x['gross_ann'], 1, True)} | {_f(x['net_ann'], 1, True)} | "
            f"{_f(x['vol'], 1, True)} | {_f(x['sharpe_net'])} | {_f(x['dsr'])} | "
            f"{_f(x['max_dd'], 0, True)} | {_f(x['turnover'])} | {_f(x['mean_ic'], 3)} | "
            f"{_f(x['ic_t'], 1)} | {_be(x['breakeven_bps'])} |"
        )
    return head + "\n".join(rows) + "\n"


def validation_table(reports: list[FactorReport]) -> str:
    out = "| Series | French factor | Correlation | Months | Bar |\n|---|---|---|---|---|\n"
    for r in reports:
        v = r.validation
        if not v["french"]:
            continue
        bar = "> 0.7" if r.factor in ("momentum", "value", "quality") else "-"
        ok = "" if v["corr"] is None else (" pass" if v["corr"] > 0.7 else " **fail**")
        out += f"| {LABELS[r.factor]} long-short | {v['french'].upper()} | {_f(v['corr'], 3)}{ok if bar != '-' else ''} | {v['months']} | {bar} |\n"
    return out


def attribution_table(reports: list[FactorReport]) -> str:
    out = "| Factor | Alpha (ann.) | t | Mkt-RF | HML | UMD | RMW | R² |\n|---|---|---|---|---|---|---|---|\n"
    for r in reports:
        a = r.attribution

        def cell(k: str, b: dict = a.betas, t: dict = a.beta_t) -> str:
            return f"{b[k]:.2f} ({t[k]:.1f})"

        out += (
            f"| {LABELS[r.factor]} | {_f(a.alpha_annual, 1, True)} | {a.alpha_t:.1f} | "
            f"{cell('mkt_rf')} | {cell('hml')} | {cell('umd')} | {cell('rmw')} | {a.r2:.2f} |\n"
        )
    return out


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
            + f" | {'none within 5y' if math.isnan(r.half_life) else _f(r.half_life, 1)} |\n"
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
            try:
                cells.append(_f(stats.sharpe(_load(cfg, f, tag)[0]["ret_net"])))
            except FileNotFoundError:
                cells.append("n/a")
        out += f"| {LABELS[f]} | " + " | ".join(cells) + " |\n"
    return out


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


def chart_rolling_ic(reports: list[FactorReport], path, window: int = 36) -> None:
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
    for a, b in RECESSIONS:
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
    n_trials = portfolio.count_specifications(cfg.specifications)
    log = (
        pl.read_csv(cfg.specifications)
        if cfg.specifications.exists()
        else pl.DataFrame()
    )
    sr_var = 0.0
    if log.height > 1 and "sharpe_net" in log.columns:
        s = log["sharpe_net"].cast(pl.Float64, strict=False).drop_nulls()
        if s.len() > 1:
            sr_var = float((s / math.sqrt(12)).var())

    reports = [
        factor_report(cfg, f, inp, n_trials, sr_var)
        for f in factors
        if (cfg.data / "processed" / f"long_short_{f}.parquet").exists()
    ]
    figs = cfg.reports / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    chart_deciles(reports, figs / "chart1_deciles.png")
    chart_rolling_ic(reports, figs / "chart2_rolling_ic.png")
    chart_decay(reports, figs / "chart3_ic_decay.png")
    chart_cost(reports, figs / "chart4_sharpe_vs_cost.png")

    tags = [
        ("cw", "Cap-weighted"),
        ("hold3", "Hold 3m"),
        ("hold6", "Hold 6m"),
        ("hold12", "Hold 12m"),
        ("nosector", "No sector neutralisation"),
    ]
    md = [
        f"# Results\n\nGenerated by `backtester report`. Window {cfg.start} to {cfg.end}; "
        f"base cost {cfg.base_bps:.0f} bp one-way on every dollar traded; weighting {cfg.weighting}; "
        f"execution lag {cfg.lag_days} trading day; deciles {cfg.n_deciles}; "
        f"specifications logged N = {n_trials} (variance of monthly Sharpe across them {sr_var:.4f}).\n",
        "## Results table\n",
        results_table(reports),
        "\nDSR is the deflated Sharpe: the probability that the net Sharpe exceeds the expected maximum "
        "of N random trials with the same dispersion, adjusted for skew and kurtosis. Break-even cost is the "
        "one-way cost at which the mean net return is zero.\n",
        "## Validation against Ken French\n",
        validation_table(reports),
        "\n## Attribution (long-short on Mkt-RF, HML, UMD, RMW; t-stats in brackets)\n",
        attribution_table(reports),
        "\n## IC decay\n",
        decay_table(reports),
        "\n## Net Sharpe by assumed cost\n",
        cost_table(reports, [0, 5, 10, 25, 50]),
        "\n## Variants (net Sharpe)\n",
        variant_table(cfg, [r.factor for r in reports], tags),
        "\nCap-weighted runs hold only the names with a market cap (39% of members in "
        "2010, 86% in 2023); the equal-weighted base holds every name with a signal.\n",
        "\n## With and without the badly covered months\n",
        coverage_split_table(cfg, reports),
        "\n## Fama-MacBeth premia (per unit z, monthly) and IC information ratio\n",
        "| Factor | Premium | t (NW) | IC IR |\n|---|---|---|---|\n"
        + "".join(
            f"| {r.row['factor']} | {_f(r.row['fm_premium'], 2, True)} | {_f(r.row['fm_t'], 1)} | {_f(r.row['ic_ir'])} |\n"
            for r in reports
        ),
        "\n## Charts\n",
        "![deciles](figures/chart1_deciles.png)\n![rolling IC](figures/chart2_rolling_ic.png)\n"
        "![IC decay](figures/chart3_ic_decay.png)\n![Sharpe vs cost](figures/chart4_sharpe_vs_cost.png)\n",
    ]
    text = "\n".join(md)
    (cfg.reports / "results.md").write_text(text, encoding="utf-8", newline="\n")
    from backtester.run import validation_table as validation_csv

    validation_csv(cfg, inp).write_csv(cfg.reports / "validation.csv")
    return text
