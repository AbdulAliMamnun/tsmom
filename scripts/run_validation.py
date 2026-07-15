"""Run the validation layer on the real (cached) data.

Produces the STEP 4 deliverables (docs/STEP_4_SPEC.md section 7):
  - Walk-forward OOS Sharpe (a point estimate) and selection churn
  - CPCV path-Sharpe distribution (mean / std / min / max)
  - PBO
  - Embargo-sensitivity table across [0, 5, 21, 63]

The interesting question -- deliberately posed, not answered here (that is Thread A, and it
belongs to the author per REASONING_LOG ENTRY 15) -- is whether the walk-forward point
estimate falls INSIDE or OUTSIDE the CPCV path distribution, and where they diverge. The two
methods estimate different estimands (ENTRY 12 vs ENTRY 13); a divergence is a finding, not a
bug to reconcile.

Run: PYTHONPATH=src python3 scripts/run_validation.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tsmom import config, data, metrics, validation

pd.set_option("display.width", 100)


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


prices = data.fetch_prices()
returns = data.to_returns(prices)
configs = config.parameter_grid()

_rule("SAMPLE")
print(f"  tickers      {prices.shape[1]}")
print(f"  bars         {len(prices)}  ({prices.index[0].date()} -> {prices.index[-1].date()})")
print(f"  grid size N  {len(configs)}  (pre-registered, fixed)")

# --------------------------------------------------------------------------------------
# Walk-forward -- the live-trading counterfactual (one path, one number)
# --------------------------------------------------------------------------------------
_rule("WALK-FORWARD (expanding window -- the live-trading counterfactual)")
wf = validation.walk_forward(prices, returns, configs)
wf_sharpe = metrics.sharpe_ratio(wf.oos_returns)

print(f"  OOS Sharpe (point)   {wf_sharpe:.3f}")
print(f"  OOS bars             {len(wf.oos_returns)}")
print(f"  re-selection steps   {wf.n_selections}")
print(f"  selection churn      {wf.selection_churn:.1%}  (fraction of steps the pick changed)")

counts = wf.selections["selected_config"].value_counts()
print("\n  config selection frequency:")
for name, c in counts.items():
    print(f"    {name:16} {c:3d}  ({c / wf.n_selections:.0%})")

# --------------------------------------------------------------------------------------
# CPCV -- the DGP-stability distribution (many paths)
# --------------------------------------------------------------------------------------
_rule("CPCV (combinatorial purged CV -- a distribution, not a point)")
cp = validation.cpcv(prices, returns, configs)
ps = cp.path_sharpes

print(f"  splits               {cp.n_splits}")
print(f"  assembled paths      {cp.n_paths}")
print(f"  path Sharpe mean     {ps.mean():.3f}")
print(f"  path Sharpe std      {ps.std():.3f}")
print(f"  path Sharpe min/max  {ps.min():.3f} / {ps.max():.3f}")
print("\n  per-path Sharpe:")
for name, s in ps.items():
    print(f"    {name:10} {s:.3f}")

# --------------------------------------------------------------------------------------
# PBO + embargo sensitivity (ENTRY 11 -- show whether the conclusion moves)
# --------------------------------------------------------------------------------------
_rule("EMBARGO SENSITIVITY (21 days is a convention, not an optimum -- ENTRY 11)")
emb = validation.embargo_sensitivity(prices, returns, configs)
print("  " + emb.to_string(index=False).replace("\n", "\n  "))

pbo_21 = float(emb.loc[emb["embargo_days"] == config.EMBARGO_DAYS, "pbo"].iloc[0])

# --------------------------------------------------------------------------------------
# The question this whole project is built toward (posed, not answered)
# --------------------------------------------------------------------------------------
_rule("WALK-FORWARD vs CPCV  (the divergence is the finding -- Thread A)")
inside = bool(ps.min() <= wf_sharpe <= ps.max())
pctile = float((ps.to_numpy() < wf_sharpe).mean())
print(f"  walk-forward point Sharpe   {wf_sharpe:.3f}")
print(f"  CPCV path Sharpe range      [{ps.min():.3f}, {ps.max():.3f}]  (mean {ps.mean():.3f})")
print(f"  WF point falls INSIDE CPCV range?   {inside}")
print(f"  WF point percentile within paths    {pctile:.0%}")
print(f"  PBO (embargo={config.EMBARGO_DAYS})               {pbo_21:.3f}")
print(
    "\n  Reminder: these estimate DIFFERENT estimands -- WF a live-trading counterfactual,\n"
    "  CPCV a data-generating-process stability property (ENTRY 12 vs ENTRY 13). Which to\n"
    "  believe is Thread A and is left to the author on purpose (ENTRY 15)."
)
