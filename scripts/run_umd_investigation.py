"""Run the full UMD investigation on real (cached) data. Tables only -- no conclusions.

Answers a machinery question, not an interpretive one: why does UMD load on a trend strategy
trading currencies? Every regression reports beta, t, p, corr, R^2, n_obs; daily and monthly
are shown side by side; every test runs on the full sample, the live-ETF period (>= the date
all sleeves trade), and the pre-live backfilled period.

Per STEP_7 §11, this script prints NO conclusion. The author reads the tables and forms the
position.

Run: PYTHONPATH=src python3 scripts/run_umd_investigation.py
"""

from __future__ import annotations

import pandas as pd

from tsmom import config, umd_investigation as ui

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 200)


def rule(title: str) -> None:
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)


def show(df: pd.DataFrame, nd: int = 4) -> None:
    print("  " + df.round(nd).to_string(index=False).replace("\n", "\n  "))


def show_idx(df: pd.DataFrame, nd: int = 3) -> None:
    print("  " + df.round(nd).to_string().replace("\n", "\n  "))


inp = ui.load_inputs()

rule("SETUP")
print(f"  primary config        {config.primary_config().name}")
print(f"  live-ETF start        {inp.live_start.date()}  (max over sleeves of first-active date)")
print(f"  windows               full | live (>= {inp.live_start.date()}) | pre (< {inp.live_start.date()})")

# --------------------------------------------------------------------------------------
rule("§2  DATA VERIFICATION — the backfill problem")
print("\n  Ticker inception (first_tradeable should trail first_price by ~MIN_HISTORY_DAYS):")
show(ui.ticker_inception(inp))
print("\n  Date alignment (French ends before prices — regressions trim to the overlap):")
show(ui.date_alignment(inp))
print("\n  Currency within-sleeve correlation (raw daily returns) — UUP overlaps FXE/FXY/FXB:")
show_idx(ui.currency_within_correlation(inp))

# --------------------------------------------------------------------------------------
rule("§1  FREQUENCY — full-portfolio UMD, daily vs monthly (the R^2 is the point)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.full_portfolio_umd(inp, w))

# --------------------------------------------------------------------------------------
rule("§1 + §3  PER-SLEEVE UMD — univariate (UMD's own variance explained = R^2)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.sleeve_umd_regressions(inp, w))

rule("§3  PER-SLEEVE FF5+UMD (reproduces Finding 9 daily; extends to monthly)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.sleeve_ff5_umd_regressions(inp, w))

# --------------------------------------------------------------------------------------
rule("§4  SLEEVE CORRELATION MATRIX (monthly, each sleeve vol-targeted to 10%)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show_idx(ui.sleeve_correlation_matrix(inp, w))

# --------------------------------------------------------------------------------------
rule("§5  PAIRWISE SLEEVE REGRESSIONS (monthly)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.pairwise_sleeve_regressions(inp, w))

# --------------------------------------------------------------------------------------
rule("§6  LEAVE-ONE-OUT COMMON TREND — sleeve ~ UMD + other_three_avg (monthly)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.leave_one_out_common_trend(inp, w))

# --------------------------------------------------------------------------------------
rule("§7  MACRO CONTROLS — UMD coefficient under each control (monthly)")
print("  (endogenous=True means the control is an instrument the sleeve contains — contaminated)")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.macro_controls(inp, w))

# --------------------------------------------------------------------------------------
rule("§8  TAIL & OUTLIER CONCENTRATION — sleeve-vs-UMD correlation by condition")
for w in ui.WINDOWS:
    print(f"\n  window = {w}")
    show(ui.tail_concentration(inp, w))

# --------------------------------------------------------------------------------------
rule("§9  STABILITY OVER TIME — per-sleeve monthly UMD regression by period")
show(ui.stability_by_period(inp))
path = ui.plot_rolling_betas(inp)
print(f"\n  rolling 3y/5y UMD-beta plot -> {path}")

# --------------------------------------------------------------------------------------
rule("§10  ECONOMIC IMPORTANCE")
print("\n  Variance of each sleeve explained by UMD (R^2), daily vs monthly:")
for w in ("full", "live"):
    print(f"\n  window = {w}")
    show(ui.variance_explained(inp, w))
print("\n  Portfolio risk, raw vs UMD-hedged (residual of portfolio ~ UMD), daily:")
for w in ("full", "live"):
    print(f"\n  window = {w}")
    show(ui.umd_hedged_portfolio(inp, w))
print("\n  Correlation of sleeve DRAWDOWN paths (do they lose money together?), full:")
show_idx(ui.sleeve_drawdown_correlation(inp, "full"))
