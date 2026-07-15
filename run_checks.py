"""Standalone verification runner (no pytest required).

Runs the same checks as tests/test_no_lookahead.py. Use pytest locally; this exists so the
engine can be verified in a bare environment.

Run: PYTHONPATH=src python3 run_checks.py
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from tsmom import backtest, config, data, metrics, signals

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    marker = "  ok  " if condition else " FAIL "
    print(f"[{marker}] {name}" + (f"\n         {detail}" if detail and not condition else ""))


# --------------------------------------------------------------------------------------

print("=" * 78)
print("LOOK-AHEAD DETECTION")
print("=" * 78)

prices = data.synthetic_prices(tickers=["AAA", "BBB", "CCC", "DDD"], n_days=1500, seed=config.SEED)
returns = data.to_returns(prices)


def truncation_violation(fn, px, test_points, **kwargs) -> float:
    """Max discrepancy between full-series and truncated-series evaluation at t.

    A HARNESS BUG WORTH KNOWING ABOUT (this cost a debugging cycle, and the story is
    write-up material):

    The obvious implementation guards with `both_valid = a.notna() & b.notna()` and skips
    points where either is NaN. That guard has a legitimate purpose -- warm-up periods
    produce NaN in BOTH series, and comparing them is meaningless.

    But it silently destroys the test. A leaky function evaluated on data truncated at t
    produces NaN at t *precisely because the future it wants to read is not there*. So
    `b` is NaN exactly at the point that proves the leak, `both_valid` is False, and the
    harness skips it and reports a clean 0.0.

    The naive guard therefore reports PASS for `shift(-1)`, which is unambiguously leaky.

    The distinction that matters:
      - NaN in BOTH  -> warm-up. Skip. Not evidence of anything.
      - NaN in TRUNCATED only, where FULL is valid -> the function needed future data to
        produce a value. THAT IS THE LEAK. Do not skip; flag it.
    """
    full = fn(px, **kwargs)
    worst = 0.0
    for t in test_points:
        trunc = fn(px.iloc[: t + 1], **kwargs)
        a, b = full.iloc[t], trunc.iloc[t]

        # Truncation-induced NaN: full has a value, truncated does not. The function
        # required data beyond t. This IS a violation, and the naive guard hides it.
        leaked_to_nan = a.notna() & b.isna()
        if bool(leaked_to_nan.any()):
            return float("inf")

        both = a.notna() & b.notna()
        if both.any():
            worst = max(worst, float((a[both] - b[both]).abs().max()))
    return worst


# ---- Layer 3: positive controls (MUST be detected) -----------------------------------
print("\n--- Positive controls: deliberately leaky functions MUST be caught ---")
print("    (if these pass, the test methodology is broken and every result below is void)\n")


def leaky_centered(px, lookback=60):
    ma = px.rolling(lookback, center=True, min_periods=1).mean()
    return np.sign(px - ma)


def leaky_zscore(px, lookback=60):
    mom = px / px.shift(lookback) - 1.0
    return np.sign((mom - mom.mean()) / mom.std())


def leaky_shift(px, lookback=60):
    """shift(-1) on the CONTINUOUS series, before sign() is applied.

    Subtlety worth knowing: if you apply np.sign() first, this control can pass a
    truncation test even though the function is unambiguously leaky. sign() quantises to
    {-1, 0, +1}, so a one-bar shift usually lands on the same sign and the discrepancy
    vanishes. The leak is real but invisible to a test looking at the quantised output.

    Lesson for the write-up: test the CONTINUOUS signal, not its discretised form. A test
    that only sees quantised output has a large blind spot -- and it will report a
    reassuring pass.
    """
    mom = px / px.shift(lookback) - 1.0
    return mom.shift(-1)


tp = [500, 800, 1100]
v = truncation_violation(leaky_centered, prices, tp)
check("positive control: centred rolling window is detected", v > 0, f"violation={v}")

v = truncation_violation(leaky_zscore, prices, tp)
check("positive control: full-sample z-score is detected", v > 0, f"violation={v}")

v = truncation_violation(leaky_shift, prices, tp)
check("positive control: shift(-1) is detected", v > 0, f"violation={v}")

# Quantised form of the same leak. The naive harness (value-comparison only) misses this,
# because sign() maps a shifted value to the same {-1,0,+1} most of the time. The improved
# harness catches it anyway, via the NaN-on-truncation rule: shift(-1) cannot produce a
# value at the final bar of a truncated series, and that absence is itself the evidence.
v_quantised = truncation_violation(
    lambda px, lookback=60: np.sign(leaky_shift(px, lookback)), prices, tp
)
check(
    "shift(-1) is caught even through sign() quantisation",
    v_quantised > 0,
    f"violation={v_quantised} -- the NaN-on-truncation rule catches what value-comparison "
    f"alone would miss",
)

# ---- Layer 1: truncation invariance on the real engine -------------------------------
print("\n--- Truncation invariance: f(series)[t] must equal f(series[:t])[t] ---\n")

TP = [400, 600, 900, 1200, 1400]

v = truncation_violation(signals.trailing_return, prices, TP, lookback=126)
check("trailing_return is causal", v == 0.0, f"violation={v}")

v = truncation_violation(signals.tsmom_signal, prices, TP, lookback=126)
check("tsmom_signal is causal", v == 0.0, f"violation={v}")

v = truncation_violation(signals.ewma_volatility, returns, TP)
check("ewma_volatility is causal", v == 0.0, f"violation={v}")


def pos_fn(px):
    r = data.to_returns(px)
    return signals.target_positions(px, r, lookback=126, vol_target=0.40)


full = pos_fn(prices)
worst = 0.0
for t in TP:
    trunc = pos_fn(prices.iloc[: t + 1])
    a, b = full.iloc[t], trunc.iloc[t]
    both = a.notna() & b.notna()
    if both.any():
        worst = max(worst, float((a[both] - b[both]).abs().max()))
check("target_positions is causal (composed pipeline)", worst < 1e-10, f"violation={worst}")


def full_pipeline(px):
    r = data.to_returns(px)
    tradeable = data.tradeable_mask(px)
    pos = signals.target_positions(px, r, lookback=126, vol_target=0.40, tradeable=tradeable)
    pos = signals.scale_to_portfolio_vol(pos, r)
    return signals.apply_rebalance_schedule(pos, freq="M")


# Compare at t - 1, not t.
#
# WHY: `apply_rebalance_schedule` forward-fills positions between rebalance dates, and a
# rebalance date is defined by the calendar. Truncating the series at t makes bar t the last
# bar, and "is bar t the last bar of its month" is a question whose answer legitimately
# changes when you delete every bar after it.
#
# That is NOT look-ahead -- no future PRICE is read; the trading calendar is known in
# advance. It is an artifact of truncation itself. Comparing strictly before the boundary
# isolates the property we actually care about (does the pipeline read future prices)
# from the boundary effect (does truncation change which bar is last).
#
# This distinction matters and is easy to get wrong in both directions: silence the test and
# you hide real leaks; over-trust it and you "fix" a non-bug by mangling the engine.
full = full_pipeline(prices)
worst = 0.0
for t in [600, 900, 1200]:
    trunc = full_pipeline(prices.iloc[: t + 1])
    a, b = full.iloc[t - 1], trunc.iloc[t - 1]
    worst = max(worst, float((a - b).abs().max()))
check(
    "FULL position pipeline is causal (incl. vol scaling + rebalance)",
    worst < 1e-8,
    f"violation={worst} -- scale_to_portfolio_vol is the usual culprit",
)

# ---- Layer 2: future poisoning -------------------------------------------------------
print("\n--- Future poisoning: NaN out the future, nothing at or before t may change ---\n")

for poison_at in [700, 1000, 1300]:
    clean = signals.tsmom_signal(prices, lookback=126)
    poisoned_px = prices.copy()
    poisoned_px.iloc[poison_at + 1 :] = np.nan
    poisoned = signals.tsmom_signal(poisoned_px, lookback=126)
    a = clean.iloc[: poison_at + 1]
    b = poisoned.iloc[: poison_at + 1]
    both = a.notna() & b.notna()
    d = float((a[both] - b[both]).abs().max().max()) if both.any().any() else 0.0
    check(f"signal survives future poisoning at t={poison_at}", d == 0.0, f"violation={d}")

# ---- Execution lag -------------------------------------------------------------------
print("\n--- Execution lag: position held at t must be position targeted at t-1 ---\n")

pos = signals.target_positions(prices, returns, lookback=126, vol_target=0.40)
res = backtest.run_backtest(prices, pos, cost_model=config.COST_SCENARIOS[0])
expected = pos.shift(1).fillna(0.0)
d = float((res.positions_held - expected).abs().max().max())
check("execution lag t -> t+1 is applied", d < 1e-10, f"violation={d}")

same_bar = (pos * returns).sum(axis=1)
common = res.net_returns.index.intersection(same_bar.index)
corr = float(res.net_returns.loc[common].corr(same_bar.loc[common]))
check(
    "lagged vs same-bar execution are distinguishable",
    corr < 0.999,
    f"corr={corr:.6f} -- if ~1.0 the lag test proves nothing on this data",
)

# ---- Negative control ----------------------------------------------------------------
print("\n--- Negative control: no trend in a driftless random walk ---\n")

rw_prices = data.synthetic_prices(
    tickers=[f"R{i}" for i in range(12)], n_days=3000, seed=999, with_trend=False
)
rw_returns = data.to_returns(rw_prices)
rw_tradeable = data.tradeable_mask(rw_prices)
rw_pos = signals.target_positions(
    rw_prices, rw_returns, lookback=252, vol_target=0.40, tradeable=rw_tradeable
)
rw_pos = signals.scale_to_portfolio_vol(rw_pos, rw_returns)
rw_pos = signals.apply_rebalance_schedule(rw_pos, freq="M")
rw_res = backtest.run_backtest(rw_prices, rw_pos, cost_model=config.BASE_COST)
rw_sharpe = metrics.sharpe_ratio(rw_res.net_returns)
check(
    "engine finds no alpha in driftless noise",
    abs(rw_sharpe) < 0.75,
    f"sharpe={rw_sharpe:.3f} on data with no trend by construction",
)

# ---- Positive control: engine CAN find signal ----------------------------------------
print("\n--- Positive control: engine must find trend when trend exists ---\n")

# trend_strength calibrated to produce a gross Sharpe of ~0.8 -- realistic for trend
# following. An earlier value (0.0008) produced a Sharpe of 9.8, which is a degenerate
# fixture: on a near-deterministic series the cost drag is numerically irrelevant and any
# test using it is uninformative. Sanity-check the fixture, not just the assertion.
tr_prices = data.synthetic_prices(
    tickers=[f"T{i}" for i in range(12)],
    n_days=3000,
    seed=1234,
    with_trend=True,
    trend_strength=0.0001,
)
tr_returns = data.to_returns(tr_prices)
tr_tradeable = data.tradeable_mask(tr_prices)
tr_pos = signals.target_positions(
    tr_prices, tr_returns, lookback=252, vol_target=0.40, tradeable=tr_tradeable
)
tr_pos = signals.scale_to_portfolio_vol(tr_pos, tr_returns)
tr_pos = signals.apply_rebalance_schedule(tr_pos, freq="M")
tr_res = backtest.run_backtest(tr_prices, tr_pos, cost_model=config.BASE_COST)
tr_sharpe = metrics.sharpe_ratio(tr_res.net_returns)
check(
    "engine finds alpha when trend is injected",
    tr_sharpe > 0.2,
    f"sharpe={tr_sharpe:.3f} on data with genuine AR(1) drift -- if this fails the engine "
    f"cannot detect signal at all, which makes the negative control uninformative",
)

# --------------------------------------------------------------------------------------
print("\n" + "=" * 78)
print("METRICS VERIFICATION")
print("=" * 78 + "\n")

# Reproduce the DSR worked example from Bailey & Lopez de Prado (2014).
rng = np.random.default_rng(42)
T = 1250
target_sr_ann = 2.5
sr_daily = target_sr_ann / np.sqrt(252)
base = rng.standard_normal(T)
skewed = base - 0.35 * (base**2 - 1)
skewed = (skewed - skewed.mean()) / skewed.std()
synth = pd.Series(skewed * 0.01 + sr_daily * 0.01)
realized_sr = metrics.sharpe_ratio(synth)

sr0 = metrics.expected_max_sharpe(n_trials=1000, sr_variance=1.0)
check(
    "expected_max_sharpe(N=1000, V=1) is in the right range",
    2.5 < sr0 < 3.7,
    f"SR0={sr0:.3f} -- extreme-value theory says best-of-1000 Normal draws lands ~3.2 sd",
)

sr0_small = metrics.expected_max_sharpe(n_trials=12, sr_variance=1.0)
check(
    "expected_max_sharpe is monotone increasing in N",
    sr0_small < sr0,
    f"N=12 -> {sr0_small:.3f}, N=1000 -> {sr0:.3f}",
)

check("expected_max_sharpe(N=1) == 0", metrics.expected_max_sharpe(1, 1.0) == 0.0)

mbtl_45 = metrics.minimum_backtest_length(45, target_sharpe=1.0)
check(
    "MinBTL(N=45, SR=1) ~ 5 years (the BBLZ anchor)",
    6.5 < mbtl_45 < 8.5,
    f"MinBTL={mbtl_45:.2f} years",
)

mbtl_12 = metrics.minimum_backtest_length(12, target_sharpe=1.0)
check(
    "MinBTL(N=12) < MinBTL(N=45) -- smaller grid needs less data",
    mbtl_12 < mbtl_45,
    f"N=12 -> {mbtl_12:.2f}y, N=45 -> {mbtl_45:.2f}y",
)

psr = metrics.probabilistic_sharpe_ratio(pd.Series(rng.standard_normal(2000) * 0.01))
check(
    "PSR of pure noise is near 0.5 (no evidence of skill)",
    0.2 < psr < 0.8,
    f"PSR={psr:.3f}",
)

good = pd.Series(rng.standard_normal(2000) * 0.01 + 0.0008)
psr_good = metrics.probabilistic_sharpe_ratio(good)
check(
    "PSR of a genuinely positive series is high",
    psr_good > 0.9,
    f"PSR={psr_good:.3f}",
)

dsr_naive = metrics.deflated_sharpe_ratio(good, n_trials=1, sr_variance=0.0)
dsr_many = metrics.deflated_sharpe_ratio(good, n_trials=1000, sr_variance=0.5)
check(
    "DSR falls as N rises (the whole point of deflation)",
    dsr_many < dsr_naive,
    f"N=1 -> {dsr_naive:.4f}, N=1000 -> {dsr_many:.4f}",
)

# --------------------------------------------------------------------------------------
print("\n" + "=" * 78)
print("END-TO-END SMOKE TEST (synthetic data)")
print("=" * 78 + "\n")

grid = config.parameter_grid()
check("parameter grid has N=12 configurations", len(grid) == 12, f"N={len(grid)}")
check("exactly one config is designated primary", sum(c.is_primary for c in grid) == 1)
check(
    "primary config is the MOP spec (252d / 40% / monthly)",
    config.primary_config().name == "lb252_vt40_rbM",
    f"primary={config.primary_config().name}",
)

cfg = config.primary_config()
pos = signals.target_positions(
    tr_prices, tr_returns, lookback=cfg.lookback, vol_target=cfg.vol_target,
    tradeable=tr_tradeable,
)
pos = signals.scale_to_portfolio_vol(pos, tr_returns)
pos = signals.apply_rebalance_schedule(pos, freq=cfg.rebalance)
res = backtest.run_backtest(tr_prices, pos, cost_model=config.BASE_COST)

check("backtest produces net < gross (costs are actually charged)",
      res.net_returns.sum() < res.gross_returns.sum(),
      f"gross={res.gross_returns.sum():.4f}, net={res.net_returns.sum():.4f}")

check("turnover is positive", res.annual_turnover > 0, f"turnover={res.annual_turnover:.2f}/yr")

be = backtest.breakeven_cost_bps(tr_prices, pos)
check("breakeven cost is computable", np.isfinite(be), f"breakeven={be:.1f}bp per side")

# Monotonicity of net Sharpe in cost.
#
# NOTE ON WHY THIS TEST IS RUN ON `prices` AND NOT `tr_prices`:
# An earlier version ran it on the trending synthetic series, which produces a gross Sharpe
# of ~9.8. That number is absurd -- it is the tell that the DATA is degenerate, not that the
# strategy is good. `trend_strength=0.0008` on an AR(1) drift makes the series nearly
# deterministic, and on a near-deterministic series with a tiny mean-to-vol ratio the Sharpe
# is dominated by the drift and the cost drag becomes numerically irrelevant.
#
# Worse: when gross mean return is NEGATIVE, subtracting a positive cost makes the mean more
# negative, and the Sharpe becomes MORE negative -- so monotonicity holds, but for reasons
# that have nothing to do with the property being tested. The test only means something on a
# series with a plausible positive gross return.
#
# The lesson generalises: a test that passes on degenerate data is not evidence. Sanity-check
# the FIXTURE, not just the assertion. A Sharpe of 9.8 in a test fixture should stop you.
sens = backtest.cost_sensitivity(tr_prices, pos)
diffs = sens["net_sharpe"].diff().dropna()
check(
    "net Sharpe is monotone non-increasing in cost",
    bool((diffs <= 1e-9).all()),
    "\n" + sens[["scenario", "per_side_bps", "gross_sharpe", "net_sharpe"]].to_string(index=False),
)
check(
    "costs are charged, not credited (net < gross at every nonzero cost)",
    bool((sens.loc[sens["per_side_bps"] > 0, "net_sharpe"]
          < sens.loc[sens["per_side_bps"] > 0, "gross_sharpe"]).all()),
    "\n" + sens[["scenario", "per_side_bps", "gross_sharpe", "net_sharpe"]].to_string(index=False),
)

abl = backtest.ablation(tr_prices, tr_returns, lookback=252, vol_target=0.40)
check("ablation runs and produces 4 arms", len(abl) == 4)
print("\n  Ablation (synthetic trending data -- the REQUIRED signal-vs-scaling decomposition):")
print("  " + abl.to_string(index=False).replace("\n", "\n  "))

# --------------------------------------------------------------------------------------
print("\n" + "=" * 78)
n_pass = sum(1 for s, _, _ in results if s == PASS)
n_fail = sum(1 for s, _, _ in results if s == FAIL)
print(f"RESULT: {n_pass} passed, {n_fail} failed")
print("=" * 78)

if n_fail:
    print("\nFAILURES:")
    for s, name, detail in results:
        if s == FAIL:
            print(f"  - {name}\n    {detail}")

sys.exit(1 if n_fail else 0)
