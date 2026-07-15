"""Thread B on the real (cached) data: multiple-testing, effective-N, DSR sensitivity.

Produces the STEP 5 deliverables (docs/STEP_5_SPEC.md section 9):
  - all 12 config Sharpes (disclosed regardless of outcome -- pre-registration 5.1)
  - the trial-return correlation matrix
  - every effective-N estimate WITH bootstrap CIs
  - DSR at N=12 (naive) and at each N_eff estimate
  - the DSR-vs-N curve and the interpolated flip point
  - Harvey-Liu haircuts
  - factor regression with Newey-West (if the Ken French file is present)
  - sub-period and vol-regime tables

The question to hold (ENTRY 16): where does the flip point fall relative to the plausible
range of N_eff? If it falls INSIDE that range, the honest conclusion is that the sample
cannot resolve whether the strategy has an edge -- a legitimate, reportable finding, not a
failure. This script computes the pieces; it does not draw the conclusion. That is the
author's (ENTRY 16 deliberately has none).

Run: PYTHONPATH=src python3 scripts/run_multiple_testing.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tsmom import config, data, factor_model, metrics, multiple_testing as mt

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 20)


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


prices = data.fetch_prices()
returns = data.to_returns(prices)
configs = config.parameter_grid()
primary = config.primary_config().name

_rule("SAMPLE")
print(f"  tickers {prices.shape[1]}   bars {len(prices)}   "
      f"({prices.index[0].date()} -> {prices.index[-1].date()})")
print(f"  grid N = {len(configs)} (pre-registered, fixed)   primary = {primary}")

# --------------------------------------------------------------------------------------
tr = mt.trial_returns(prices, returns, configs)

_rule("ALL 12 CONFIG SHARPES (disclosed regardless of outcome -- pre-registration 5.1)")
sharpes = pd.DataFrame(
    {
        "config": tr.columns,
        "net_sharpe": [metrics.sharpe_ratio(tr[c]) for c in tr.columns],
        "ann_vol": [metrics.annualized_vol(tr[c]) for c in tr.columns],
        "is_primary": [c == primary for c in tr.columns],
    }
).sort_values("net_sharpe", ascending=False)
print("  " + sharpes.to_string(index=False).replace("\n", "\n  "))

# --------------------------------------------------------------------------------------
_rule("TRIAL-RETURN CORRELATION MATRIX (why N=12 overstates the number of bets)")
corr = mt._corr(tr)
print("  " + corr.round(2).to_string().replace("\n", "\n  "))
print(f"\n  mean off-diagonal correlation: {mt._mean_offdiag_corr(corr):.3f}")

# --------------------------------------------------------------------------------------
_rule("EFFECTIVE-N ESTIMATES WITH BOOTSTRAP CIs (stationary bootstrap; ENTRY 16)")
unc = mt.effective_n_uncertainty(tr, n_boot=1000, seed=config.SEED)
print("  " + unc.round(2).to_string(index=False).replace("\n", "\n  "))
print("\n  Cluster count vs distance threshold -- the threshold IS the finding, so the CURVE is")
print(f"  the honest form; the point above uses threshold {mt.CLUSTER_THRESHOLD} (merge rho > 0.955,")
print("  i.e. near-perfect duplicates), which returns 6 = the count of DISTINCT strategies.")
print("  (The old default 1.0 sat past total collapse and reported 1 with CI [1,1] -- the")
print("  threshold, not the data.)")
print("  " + mt.clustering_curve(tr).to_string(index=False).replace("\n", "\n  "))

# --------------------------------------------------------------------------------------
_rule("DSR: NAIVE (N=12) vs EACH EFFECTIVE-N ESTIMATE")
primary_ret = tr[primary]
trial_sharpes = np.array([metrics.sharpe_ratio(tr[c]) for c in tr.columns])
sr_var = float(np.var(trial_sharpes, ddof=1))
psr_vs_zero = metrics.probabilistic_sharpe_ratio(primary_ret, 0.0)


def _dsr_at(n: float) -> tuple[float, float]:
    sr0 = max(0.0, metrics.expected_max_sharpe(float(n), sr_var))
    return sr0, metrics.probabilistic_sharpe_ratio(primary_ret, benchmark_sr=sr0)


print(f"  primary net Sharpe {metrics.sharpe_ratio(primary_ret):.3f}   "
      f"PSR vs 0 (N=1) {psr_vs_zero:.3f}   var(trial Sharpes) {sr_var:.4f}")
est_table = mt.all_effective_n(tr).set_index("method")["estimate"]
dsr_rows = []
for method in ["naive", "rho_bar", "participation", "variance_95", "entropy", "clustering"]:
    n_eff = float(est_table[method])
    sr0, dsr = _dsr_at(n_eff)
    dsr_rows.append(
        {"accounting": method, "N_eff": n_eff, "sr0": sr0, "dsr": dsr, "passes_95": dsr > 0.95}
    )
print("  " + pd.DataFrame(dsr_rows).round(3).to_string(index=False).replace("\n", "\n  "))

# --------------------------------------------------------------------------------------
_rule("DSR-vs-N CURVE AND FLIP POINT (the money output)")
curve = mt.dsr_curve(primary_ret, tr)
# Print a readable subset (integer N plus the neighbourhood of the flip).
shown = curve.table[curve.table["assumed_n"].isin(np.arange(1.0, 13.0))]
print("  " + shown.round(3).to_string(index=False).replace("\n", "\n  "))
flip = curve.flip_point
if np.isnan(flip):
    verdict = "DSR fails at 95% even at N=1 -- no crossing (edge not established at any N)."
elif np.isinf(flip):
    verdict = "DSR passes at 95% across the whole N in [1,12] -- no crossing in range."
else:
    verdict = f"DSR verdict flips at N = {flip:.2f}."
print(f"\n  FLIP POINT: {verdict}")

# --------------------------------------------------------------------------------------
_rule("HARVEY-LIU HAIRCUTS (independence assumed -- reported alongside DSR, not instead)")
hl = mt.harvey_liu_haircuts(tr, primary)
print("  " + hl.round(4).to_string(index=False).replace("\n", "\n  "))

# --------------------------------------------------------------------------------------
_rule("FACTOR REGRESSION (Newey-West, lag 21): is 0.706 alpha or repackaged factor beta?")
try:
    ff = data.load_ff_factors()
    fr = factor_model.factor_regression(primary_ret, ff, nw_lags=21)
    print(f"  alpha (annualised) {fr.alpha_annual:.4f}   t-stat {fr.alpha_tstat:.2f}   "
          f"R^2 {fr.r_squared:.3f}   N {fr.n_obs}")
    print("  " + fr.table.round(4).to_string().replace("\n", "\n  "))
    print("\n  (Watch UMD: heavy loading on cross-sectional momentum would be an awkward result.)")

    # --- Per-sleeve attribution: is the UMD loading mechanical (equity) or structural? ---
    _rule("PER-SLEEVE FACTOR REGRESSION (each sleeve separately vol-targeted to 10%)")
    sleeves = factor_model.sleeve_factor_regressions(prices, returns, config.primary_config(), ff)
    print("  " + sleeves.round(4).to_string(index=False).replace("\n", "\n  "))
    print("\n  Mechanical story: UMD loading concentrates in the equity sleeve (UMD is an equity")
    print("  factor; 7 of 25 instruments are equity ETFs). Structural story: UMD loads across all")
    print("  four sleeves -- which would be genuinely strange (no equity-momentum factor in the yen).")

    # --- Alpha robustness to the Newey-West lag (headline p=0.0488 sits on the 5% line) ---
    _rule("ALPHA ROBUSTNESS TO NEWEY-WEST LAG (all lags reported -- no tuning)")
    lag_tbl = factor_model.alpha_lag_robustness(primary_ret, ff)
    print("  " + lag_tbl.round(4).to_string(index=False).replace("\n", "\n  "))
    print("\n  A longer lag admits more return autocovariance into the SE (typically widening it")
    print("  for positively autocorrelated returns, though not strictly monotonic). If passes_5pct")
    print("  flips as the lag grows, the crossing is the finding -- report it, do not tune to it.")
except FileNotFoundError as exc:
    print(f"  [skipped] {exc}")
    print("  Download the daily FF5+Momentum CSV to data/raw/ff_factors_daily.csv to enable this,")
    print("  including the per-sleeve attribution and the alpha-vs-lag robustness table.")

# --------------------------------------------------------------------------------------
_rule("SUB-PERIOD & VOL-REGIME DECOMPOSITION (pre-registration 5.1)")
sub = mt.subperiod_analysis(primary_ret)
print("  " + sub.round(3).to_string(index=False).replace("\n", "\n  "))
