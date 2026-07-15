"""Tests for the multiple-testing / effective-N machinery (Thread B).

The load-bearing controls (STEP_5_SPEC section 2):
  - 12 IDENTICAL columns  -> every non-naive estimator collapses to ~1 (one bet, repeated).
  - 12 INDEPENDENT columns -> every estimator ~12 (twelve genuine bets).
  - on real-ish data, every estimator is bounded in [1, 12]. If one isn't, it's wrong.

Plus: the trial-return vol guard (same as ablation -- a blown-up arm prints a plausible
table and means nothing), DSR-curve monotonicity and flip-point interpolation, Harvey-Liu
haircut direction, and factor-regression coefficient recovery.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tsmom import config, data, factor_model, metrics, multiple_testing as mt


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    return data.synthetic_prices(
        tickers=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
        n_days=1600,
        seed=config.SEED,
        with_trend=True,
        trend_strength=0.0004,
    )


@pytest.fixture(scope="module")
def returns(prices: pd.DataFrame) -> pd.DataFrame:
    return data.to_returns(prices)


@pytest.fixture(scope="module")
def trial_rets(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    return mt.trial_returns(prices, returns)


# --------------------------------------------------------------------------------------
# 1. trial_returns
# --------------------------------------------------------------------------------------


def test_trial_returns_shape_and_columns(trial_rets):
    grid = config.parameter_grid()
    assert trial_rets.shape[1] == len(grid) == 12
    assert list(trial_rets.columns) == [c.name for c in grid]


def test_trial_returns_vol_guard(trial_rets):
    """Every config's realised annualised vol within 3x the portfolio target -- the same
    guard as ablation(). A blown-up column would silently poison every downstream number."""
    cap = 3.0 * config.PORTFOLIO_VOL_TARGET
    for c in trial_rets.columns:
        av = metrics.annualized_vol(trial_rets[c])
        assert av <= cap, f"{c} ran at {av:.1%} annualised vol, over 3x the target"


# --------------------------------------------------------------------------------------
# 2. Effective-N estimators -- the controls
# --------------------------------------------------------------------------------------

_NON_NAIVE = ["rho_bar", "participation", "variance_95", "entropy", "clustering"]


def test_identical_columns_collapse_to_one():
    """12 identical columns -> one effective bet. (naive is definitionally the count, so it
    is excluded -- it reports 12 by design.)"""
    rng = np.random.default_rng(config.SEED)
    base = rng.standard_normal(2000)
    tr = pd.DataFrame({f"c{i}": base for i in range(12)})

    table = mt.all_effective_n(tr).set_index("method")["estimate"]
    for m in _NON_NAIVE:
        assert abs(table[m] - 1.0) < 1e-6, f"{m} = {table[m]}, expected ~1"
    assert table["naive"] == 12.0


def test_independent_columns_approach_twelve():
    """12 independent columns -> ~12 effective bets, for every estimator."""
    rng = np.random.default_rng(config.SEED)
    tr = pd.DataFrame(rng.standard_normal((6000, 12)), columns=[f"c{i}" for i in range(12)])

    table = mt.all_effective_n(tr).set_index("method")["estimate"]
    assert table["naive"] == 12.0
    # ~12 within a tolerance. rho_bar can sit a hair ABOVE 12 when the sample mean
    # off-diagonal correlation is slightly negative -- the formula is not bounded by M for
    # negative rho_bar, which is exactly why real (positively-correlated) data stays <= 12.
    for m in ["rho_bar", "participation", "entropy", "clustering"]:
        assert abs(table[m] - 12.0) <= 1.0, f"{m} = {table[m]}, expected ~12"
    assert table["variance_95"] >= 11.0


def test_estimators_bounded_on_real_data(trial_rets):
    """Every estimator lives in [1, 12] on genuinely correlated trial returns."""
    table = mt.all_effective_n(trial_rets).set_index("method")["estimate"]
    for m, v in table.items():
        assert 1.0 - 1e-9 <= v <= 12.0 + 1e-9, f"{m} = {v} out of [1, 12]"
    # The configs are correlated, so the honest effective N is strictly below the naive 12.
    assert table["participation"] < 12.0


def test_clustering_curve_is_monotone_non_increasing(trial_rets):
    """As the distance threshold grows, series merge -> cluster count cannot increase."""
    curve = mt.clustering_curve(trial_rets)
    n = curve["n_clusters"].to_numpy()
    assert np.all(np.diff(n) <= 0)


# --------------------------------------------------------------------------------------
# 3. Effective-N uncertainty
# --------------------------------------------------------------------------------------


def test_effective_n_uncertainty_structure_and_bounds(trial_rets):
    unc = mt.effective_n_uncertainty(trial_rets, n_boot=150, seed=config.SEED)
    assert set(unc["method"]) == set(mt._ESTIMATORS)
    for _, row in unc.iterrows():
        assert row["ci_low"] <= row["ci_high"]
        assert 1.0 - 1e-9 <= row["ci_low"] and row["ci_high"] <= 12.0 + 1e-9
    # naive has no sampling uncertainty; the eigenvalue estimators do.
    naive = unc.set_index("method").loc["naive"]
    assert naive["ci_low"] == naive["ci_high"] == 12.0
    part = unc.set_index("method").loc["participation"]
    assert part["ci_high"] > part["ci_low"]


# --------------------------------------------------------------------------------------
# 4. DSR curve
# --------------------------------------------------------------------------------------


def _series_with_annual_sharpe(sharpe: float, n: int, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    daily = 0.01
    mean = sharpe / np.sqrt(config.TRADING_DAYS_PER_YEAR) * daily
    idx = pd.bdate_range("2005-01-03", periods=n)
    return pd.Series(rng.normal(mean, daily, n), index=idx)


def test_dsr_curve_monotone_non_increasing():
    returns = _series_with_annual_sharpe(1.0, 2000, seed=1)
    rng = np.random.default_rng(2)
    trial = pd.DataFrame(rng.normal(0.0003, 0.01, (2000, 12)))
    curve = mt.dsr_curve(returns, trial)
    dsr = curve.table["dsr"].to_numpy()
    assert np.all(np.diff(dsr) <= 1e-9)


def test_dsr_curve_flip_point_known_crossing():
    """Constructed so DSR passes comfortably at low N and fails by N=12 -> a flip strictly
    inside (1, 12). Strong strategy Sharpe (clears 0.95 at N=1 despite sampling noise) plus
    widely dispersed trial Sharpes (large SR variance -> SR0 climbs fast) guarantee the
    crossing lands in-range rather than at a fragile margin."""
    returns = _series_with_annual_sharpe(1.5, 3000, seed=7)
    # Trial columns with widely dispersed means -> dispersed Sharpes -> large SR variance.
    rng = np.random.default_rng(8)
    means = np.linspace(-0.0015, 0.0015, 12)
    trial = pd.DataFrame(
        {f"c{i}": rng.normal(means[i], 0.01, 3000) for i in range(12)}
    )
    curve = mt.dsr_curve(returns, trial)
    flip = curve.flip_point
    assert np.isfinite(flip) and 1.0 < flip < 12.0
    # Below the flip it passes; above it fails.
    t = curve.table
    assert bool(t.loc[t["assumed_n"] <= np.floor(flip), "passes_95"].iloc[-1])
    assert not bool(t.loc[t["assumed_n"] >= np.ceil(flip), "passes_95"].iloc[0])


def test_dsr_at_n1_equals_psr_vs_zero():
    returns = _series_with_annual_sharpe(1.0, 1500, seed=3)
    rng = np.random.default_rng(4)
    trial = pd.DataFrame(rng.normal(0.0003, 0.01, (1500, 12)))
    curve = mt.dsr_curve(returns, trial, n_range=np.array([1.0]))
    row = curve.table.iloc[0]
    assert row["sr0"] == 0.0
    assert abs(row["dsr"] - metrics.probabilistic_sharpe_ratio(returns, 0.0)) < 1e-9


def test_interpolate_flip_is_exact_on_a_hand_built_table():
    table = pd.DataFrame(
        {"assumed_n": [1.0, 2.0, 3.0, 4.0], "dsr": [0.99, 0.97, 0.93, 0.90]}
    )
    # Crossing 0.95 between N=2 (0.97) and N=3 (0.93): 2 + (0.95-0.97)/(0.93-0.97) = 2.5
    assert abs(mt._interpolate_flip(table) - 2.5) < 1e-9


# --------------------------------------------------------------------------------------
# 5. Harvey-Liu haircuts
# --------------------------------------------------------------------------------------


def test_harvey_liu_haircuts_direction(trial_rets):
    primary = config.primary_config().name
    hl = mt.harvey_liu_haircuts(trial_rets, primary).set_index("method")

    assert set(hl.index) >= {"unadjusted", "bonferroni", "holm", "BHY"}
    p_raw = hl.loc["unadjusted", "adjusted_p"]
    for m in ["bonferroni", "holm", "BHY"]:
        # Adjustment can only inflate a p-value and shrink a Sharpe.
        assert hl.loc[m, "adjusted_p"] >= p_raw - 1e-12
        assert hl.loc[m, "haircut_sharpe"] <= hl.loc["unadjusted", "haircut_sharpe"] + 1e-12
        assert isinstance(bool(hl.loc[m, "passes_5pct"]), bool)


# --------------------------------------------------------------------------------------
# 6. Factor regression
# --------------------------------------------------------------------------------------


def test_factor_regression_recovers_known_betas():
    n = 2500
    idx = pd.bdate_range("2005-01-03", periods=n)
    rng = np.random.default_rng(11)
    ff = pd.DataFrame(
        {
            "Mkt-RF": rng.normal(0.0003, 0.01, n),
            "SMB": rng.normal(0.0, 0.006, n),
            "HML": rng.normal(0.0, 0.006, n),
            "RMW": rng.normal(0.0, 0.005, n),
            "CMA": rng.normal(0.0, 0.005, n),
            "UMD": rng.normal(0.0002, 0.008, n),
            "RF": np.full(n, 0.00002),
        },
        index=idx,
    )
    true_alpha_daily = 0.0001
    net = (
        ff["RF"]
        + true_alpha_daily
        + 0.5 * ff["Mkt-RF"]
        + 0.3 * ff["UMD"]
        + rng.normal(0.0, 0.002, n)
    )
    net = pd.Series(net.to_numpy(), index=idx)

    res = factor_model.factor_regression(net, ff, nw_lags=21)
    assert abs(res.table.loc["Mkt-RF", "coef"] - 0.5) < 0.03
    assert abs(res.table.loc["UMD", "coef"] - 0.3) < 0.03
    assert abs(res.table.loc["SMB", "coef"]) < 0.05
    assert abs(res.alpha_daily - true_alpha_daily) < 0.0001
    assert 0.0 <= res.r_squared <= 1.0
    assert res.n_obs == n


def test_factor_regression_flags_missing_columns():
    idx = pd.bdate_range("2005-01-03", periods=50)
    ff = pd.DataFrame({"Mkt-RF": np.zeros(50)}, index=idx)
    with pytest.raises(ValueError):
        factor_model.factor_regression(pd.Series(np.zeros(50), index=idx), ff)


def _synthetic_ff(idx: pd.DatetimeIndex, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(idx)
    return pd.DataFrame(
        {
            "Mkt-RF": rng.normal(0.0003, 0.01, n),
            "SMB": rng.normal(0.0, 0.006, n),
            "HML": rng.normal(0.0, 0.006, n),
            "RMW": rng.normal(0.0, 0.005, n),
            "CMA": rng.normal(0.0, 0.005, n),
            "UMD": rng.normal(0.0002, 0.008, n),
            "RF": np.full(n, 0.00002),
        },
        index=idx,
    )


def test_sleeve_factor_regressions_covers_all_four_sleeves():
    """Each sleeve is run through the full pipeline and regressed separately.

    Uses the real universe tickers (so config.UNIVERSE sleeves are populated) on synthetic
    prices. The point is structural: one row per asset class, each with its own attribution.
    """
    px = data.synthetic_prices(n_days=1500, seed=config.SEED, with_trend=True, trend_strength=0.0004)
    rets = data.to_returns(px)
    ff = _synthetic_ff(px.index)

    tbl = factor_model.sleeve_factor_regressions(px, rets, config.primary_config(), ff)
    assert set(tbl["sleeve"]) == set(config.UNIVERSE)  # equity, fixed_income, commodity, currency
    assert set(tbl.columns) == {
        "sleeve",
        "alpha_annual",
        "alpha_tstat",
        "umd_coef",
        "umd_tstat",
        "r_squared",
        "n_obs",
    }
    for _, row in tbl.iterrows():
        assert row["n_obs"] > 0
        assert np.isfinite(row["alpha_tstat"]) and np.isfinite(row["umd_tstat"])
        assert 0.0 <= row["r_squared"] <= 1.0


def test_alpha_lag_robustness_reports_all_lags():
    """Alpha point estimate is invariant to the HAC lag; only its t-stat/p-value move."""
    n = 2500
    idx = pd.bdate_range("2005-01-03", periods=n)
    ff = _synthetic_ff(idx, seed=5)
    rng = np.random.default_rng(6)
    net = pd.Series(
        (ff["RF"] + 0.00005 + 0.4 * ff["Mkt-RF"] + rng.normal(0.0, 0.003, n)).to_numpy(),
        index=idx,
    )

    lags = (5, 21, 63, 126)
    tbl = factor_model.alpha_lag_robustness(net, ff, lags=lags)
    assert list(tbl["nw_lag"]) == list(lags)
    assert set(tbl.columns) == {"nw_lag", "alpha_annual", "alpha_tstat", "p_value", "passes_5pct"}
    # The coefficient does not depend on the covariance estimator -- alpha is identical across
    # lags; the standard error (hence t-stat and p-value) is what changes.
    assert tbl["alpha_annual"].nunique() == 1 or tbl["alpha_annual"].std() < 1e-12
    assert tbl["alpha_tstat"].std() > 0
    assert tbl["p_value"].between(0.0, 1.0).all()


# --------------------------------------------------------------------------------------
# 7. Sub-period analysis
# --------------------------------------------------------------------------------------


def test_subperiod_analysis_covers_both_dimensions(trial_rets):
    primary = config.primary_config().name
    tbl = mt.subperiod_analysis(trial_rets[primary])
    assert set(tbl["dimension"]) == {"calendar", "vol_regime"}
    assert set(tbl.loc[tbl["dimension"] == "vol_regime", "bucket"]) <= {
        "low_vol",
        "mid_vol",
        "high_vol",
    }
    # Every bucket reports the four required stats over a non-empty window.
    for _, row in tbl.iterrows():
        assert row["n_obs"] > 0
        assert np.isfinite(row["ann_vol"])
