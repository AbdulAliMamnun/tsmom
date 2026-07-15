"""Generate the six README figures from cached data, reproducibly.

Matplotlib only. No seaborn, no dark backgrounds, no chartjunk. Every axis labelled, every
unit stated. 150 dpi, sized to read at GitHub's rendered width.

Every number here is computed from `data/raw/` on the fly (not hard-coded), so the figures
regenerate exactly. The values reproduce docs/RESULTS_LOG.md Runs 2, 4, 5, 7, 8.

Run: PYTHONPATH=src python3 scripts/make_figures.py
"""

from __future__ import annotations

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from tsmom import (
    backtest,
    config,
    data,
    factor_model,
    metrics,
    multiple_testing as mt,
    signals,
    validation,
)

FIGDIR = config.FIGURES
FIGDIR.mkdir(parents=True, exist_ok=True)
DPI = 150

plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": DPI})

# --------------------------------------------------------------------------------------
# Shared inputs (computed once)
# --------------------------------------------------------------------------------------
prices = data.fetch_prices()
returns = data.to_returns(prices)
cfg = config.primary_config()
tradeable = data.tradeable_mask(prices)

pos = signals.target_positions(prices, returns, cfg.lookback, cfg.vol_target, tradeable=tradeable)
pos = signals.scale_to_portfolio_vol(pos, returns)
pos = signals.apply_rebalance_schedule(pos, cfg.rebalance)
res = backtest.run_backtest(prices, pos, cost_model=config.BASE_COST, returns=returns)
primary_ret = res.net_returns

trial_rets = mt.trial_returns(prices, returns)


def _save(fig, name: str) -> None:
    path = FIGDIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path}")


# --------------------------------------------------------------------------------------
# 1. Equity curve: gross vs net, log scale, 2000-2007 shaded, max drawdown marked
# --------------------------------------------------------------------------------------
def fig_equity_curve() -> None:
    eq_gross = res.equity_gross
    eq_net = res.equity_net

    # Max drawdown span on the net curve.
    peak = eq_net.cummax()
    dd = eq_net / peak - 1.0
    trough = dd.idxmin()
    peak_date = eq_net.loc[:trough].idxmax()
    mdd = float(dd.min())

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(eq_gross.index, eq_gross.values, lw=1.3, color="#888888", label="gross")
    ax.plot(eq_net.index, eq_net.values, lw=1.6, color="#1f4e79", label="net (5 bp/side)")
    ax.set_yscale("log")

    # Shade the not-yet-diversified era (Run 1: effective sample starts ~2007).
    lo = eq_net.index[0]
    hi = eq_net.index[eq_net.index.searchsorted(np.datetime64("2008-01-01"))]
    ax.axvspan(lo, hi, color="#d9a441", alpha=0.15)
    ax.text(
        lo, ax.get_ylim()[1] * 0.55,
        " 2000–2007: mostly equities + Treasuries\n (staggered ETF inception; not yet diversified)",
        fontsize=8.5, va="top", color="#8a5a00",
    )

    # Mark the max drawdown.
    ax.plot([peak_date, trough], [eq_net.loc[peak_date], eq_net.loc[trough]],
            color="#c0392b", lw=1.0, ls="--")
    ax.scatter([trough], [eq_net.loc[trough]], color="#c0392b", s=25, zorder=5)
    ax.annotate(f"max drawdown {mdd:.1%}",
                xy=(trough, eq_net.loc[trough]), xytext=(10, -28),
                textcoords="offset points", fontsize=9, color="#c0392b",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.8))

    sharpe = metrics.sharpe_ratio(primary_ret)
    ax.set_title(f"Primary config {cfg.name}: growth of $1 (log scale) — net Sharpe {sharpe:.3f}")
    ax.set_xlabel("year")
    ax.set_ylabel("cumulative value (log, $1 start)")
    ax.legend(loc="upper left")
    _save(fig, "equity_curve.png")


# --------------------------------------------------------------------------------------
# 2. Ablation: net Sharpe by arm, horizontal bars, random arm at zero is the visual
# --------------------------------------------------------------------------------------
def fig_ablation() -> None:
    abl = backtest.ablation(prices, returns, cfg.lookback, cfg.vol_target)
    order = ["vol_scaled_tsmom", "unscaled_tsmom", "vol_scaled_random", "long_only"]
    abl = abl.set_index("arm").loc[order]
    labels = ["vol-scaled TSMOM\n(signal + scaling)", "unscaled TSMOM\n(signal only)",
              "vol-scaled random\n(scaling, NO signal)", "long-only\n(neither)"]
    vals = abl["net_sharpe"].values
    colors = ["#1f4e79", "#3b7dbf", "#c0392b", "#999999"]

    fig, ax = plt.subplots(figsize=(9, 4.2))
    y = np.arange(len(vals))[::-1]
    ax.barh(y, vals, color=colors, height=0.62)
    ax.axvline(0.0, color="black", lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9.5)
    for yi, v in zip(y, vals):
        ax.text(v + (0.015 if v >= 0 else -0.015), yi, f"{v:.3f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=10, fontweight="bold")

    ax.annotate("vol scaling with no signal earns nothing",
                xy=(vals[2], y[2]), xytext=(0.28, y[2] - 0.05), fontsize=9, color="#c0392b",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.8))
    ax.set_xlim(-0.15, 0.95)
    ax.set_title("Ablation: net Sharpe by arm (identical pipeline, net of 5 bp/side)")
    ax.set_xlabel("net Sharpe ratio (annualised)")
    _save(fig, "ablation.png")


# --------------------------------------------------------------------------------------
# 3. DSR vs assumed N, with effective-N estimates marked; no flip point in range
# --------------------------------------------------------------------------------------
def fig_dsr_vs_n() -> None:
    curve = mt.dsr_curve(primary_ret, trial_rets)
    t = curve.table
    est = mt.all_effective_n(trial_rets).set_index("method")["estimate"]
    marks = [("participation", est["participation"]), ("entropy", est["entropy"]),
             ("rho_bar", est["rho_bar"]), ("clustering", est["clustering"]),
             ("naive", est["naive"])]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(t["assumed_n"], t["dsr"], color="#1f4e79", lw=1.8, label="DSR(primary)")
    ax.axhline(0.95, color="#c0392b", lw=1.2, ls="--", label="95% threshold")

    # participation (1.78) and entropy (2.51) sit close together; label participation to the
    # LEFT of its line and entropy to the RIGHT so the text does not overlap.
    side = {"participation": ("right", -0.08), "entropy": ("left", 0.08),
            "rho_bar": ("left", 0.08), "clustering": ("left", 0.08), "naive": ("right", -0.08)}
    for name, n in marks:
        ax.axvline(n, color="#666666", lw=0.7, ls=":")
        ha, dx = side[name]
        ax.text(n + dx, 0.9515, f"{name} {n:.2f}", rotation=90, va="bottom", ha=ha,
                fontsize=7.5, color="#333333")

    dsr12 = float(t.loc[t["assumed_n"] == 12.0, "dsr"].iloc[0])
    ax.annotate(f"N=12: DSR {dsr12:.3f} vs 0.95\n(passes — but narrowly)",
                xy=(12, dsr12), xytext=(7.6, 0.972), fontsize=9,
                arrowprops=dict(arrowstyle="->", color="#333333", lw=0.8))
    ax.text(1.2, 0.9995, "no flip point in [1, 12] — passes at every N", fontsize=9.5,
            color="#1f4e79", va="top")

    ax.set_ylim(0.949, 1.001)
    ax.set_xlim(1, 12.2)
    ax.set_title("Deflated Sharpe Ratio vs assumed number of trials N")
    ax.set_xlabel("assumed N (effective-N estimates marked)")
    ax.set_ylabel("DSR  (P[true SR > expected max of N])")
    ax.legend(loc="lower left")
    _save(fig, "dsr_vs_n.png")


# --------------------------------------------------------------------------------------
# 4. Factor loadings with Newey-West CIs — UMD dominates. THE HEADLINE FIGURE.
# --------------------------------------------------------------------------------------
def fig_factor_loadings(ff) -> None:
    fr = factor_model.factor_regression(primary_ret, ff, nw_lags=21)
    factors = factor_model.FACTOR_COLUMNS  # Mkt-RF, SMB, HML, RMW, CMA, UMD
    coef = np.array([fr.table.loc[f, "coef"] for f in factors])
    tval = np.array([fr.table.loc[f, "tstat"] for f in factors])
    se = np.abs(coef / tval)
    ci = 1.96 * se

    fig, ax = plt.subplots(figsize=(9, 4.8))
    y = np.arange(len(factors))[::-1]
    colors = ["#3b7dbf"] * len(factors)
    colors[factors.index("UMD")] = "#c0392b"
    ax.errorbar(coef, y, xerr=ci, fmt="o", color="none", ecolor="#555555", elinewidth=1.2,
                capsize=3, zorder=2)
    ax.scatter(coef, y, c=colors, s=55, zorder=3)
    ax.axvline(0.0, color="black", lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(factors)
    for fi, yi, c, tt in zip(factors, y, coef, tval):
        ax.text(c, yi + 0.22, f"t={tt:.2f}", ha="center", fontsize=8.5,
                color="#c0392b" if fi == "UMD" else "#333333",
                fontweight="bold" if fi == "UMD" else "normal")

    ax.set_title("Factor loadings on FF5 + UMD (Newey-West 95% CIs, lag 21)\n"
                 f"alpha = {fr.alpha_annual:.2%}/yr, p = {fr.table.loc['alpha','pvalue']:.4f}"
                 f"   |   R² = {fr.r_squared:.3f}")
    ax.set_xlabel("regression coefficient (beta)")
    ax.text(coef[factors.index("UMD")], y[factors.index("UMD")] - 0.42,
            "UMD (cross-sectional momentum) dominates", fontsize=9, color="#c0392b", ha="center")
    _save(fig, "factor_loadings.png")


# --------------------------------------------------------------------------------------
# 5. UMD t-stat by sleeve — the currency bar is the point
# --------------------------------------------------------------------------------------
def fig_umd_by_sleeve(ff) -> None:
    sl = factor_model.sleeve_factor_regressions(prices, returns, cfg, ff).set_index("sleeve")
    order = ["equity", "fixed_income", "commodity", "currency"]
    tvals = [float(sl.loc[s, "umd_tstat"]) for s in order]

    fig, ax = plt.subplots(figsize=(9, 4.2))
    x = np.arange(len(order))
    colors = ["#3b7dbf", "#3b7dbf", "#3b7dbf", "#c0392b"]
    ax.bar(x, tvals, color=colors, width=0.6)
    ax.axhline(1.96, color="#c0392b", lw=1.1, ls="--", label="t = 1.96 (5% significance)")
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace("_", " ") for s in order])
    for xi, tt in zip(x, tvals):
        ax.text(xi, tt + 0.2, f"{tt:.2f}", ha="center", fontsize=10, fontweight="bold")
    ax.annotate("no mechanical channel —\nUMD is a US equity factor",
                xy=(3, tvals[3]), xytext=(2.05, tvals[3] + 2.0), fontsize=9, color="#c0392b",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.8))
    ax.set_title("UMD (momentum) t-stat by asset-class sleeve (each vol-targeted to 10%)")
    ax.set_ylabel("UMD t-statistic (Newey-West, lag 21)")
    ax.legend(loc="upper right")
    _save(fig, "umd_by_sleeve.png")


# --------------------------------------------------------------------------------------
# 6. Alpha t-stat vs Newey-West lag — dips below 1.96 at lag 63
# --------------------------------------------------------------------------------------
def fig_alpha_lag(ff) -> None:
    tbl = factor_model.alpha_lag_robustness(primary_ret, ff)
    lags = tbl["nw_lag"].to_numpy()
    tvals = tbl["alpha_tstat"].to_numpy()
    alpha_ann = float(tbl["alpha_annual"].iloc[0])

    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(range(len(lags)), tvals, "-o", color="#1f4e79", lw=1.6, markersize=7)
    ax.axhline(1.96, color="#c0392b", lw=1.1, ls="--", label="t = 1.96 (5% significance)")
    ax.set_xticks(range(len(lags)))
    ax.set_xticklabels([str(int(l)) for l in lags])
    for i, (l, tt, p) in enumerate(zip(lags, tvals, tbl["p_value"])):
        if p >= 0.05:  # below threshold: label to the side to clear the axis tick
            ax.annotate(f"t={tt:.2f}, p={p:.4f}", (i, tt), textcoords="offset points",
                        xytext=(12, 10), ha="left", fontsize=8.5, color="#c0392b")
        else:
            ax.annotate(f"t={tt:.2f}\np={p:.4f}", (i, tt), textcoords="offset points",
                        xytext=(0, 12), ha="center", fontsize=8.5, color="#333333")
    below = tbl[tbl["p_value"] >= 0.05]
    if len(below):
        i = int(np.where(lags == below["nw_lag"].iloc[0])[0][0])
        ax.scatter([i], [tvals[i]], color="#c0392b", s=80, zorder=5)

    ax.set_title(f"Alpha significance vs Newey-West lag — point estimate lag-invariant at "
                 f"{alpha_ann:.2%}/yr\n(only the standard error moves; it crosses 5% at lag 63)")
    ax.set_xlabel("Newey-West maximum lag (trading days)")
    ax.set_ylabel("alpha t-statistic")
    ax.legend(loc="lower left")
    _save(fig, "alpha_lag_robustness.png")


# --------------------------------------------------------------------------------------
def main() -> None:
    print("Figures -> results/figures/")
    fig_equity_curve()
    fig_ablation()
    fig_dsr_vs_n()
    try:
        ff = data.load_ff_factors()
    except FileNotFoundError as exc:
        print(f"  [factor figures skipped] {exc}")
        return
    fig_factor_loadings(ff)
    fig_umd_by_sleeve(ff)
    fig_alpha_lag(ff)
    print("done.")


if __name__ == "__main__":
    main()
