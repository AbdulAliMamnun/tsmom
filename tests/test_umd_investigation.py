"""Tests for the UMD investigation machinery.

These check the mechanics that make the numbers trustworthy -- correct frequency conversion,
the six-statistic regression (including R^2 = corr^2 for a univariate fit), causal controls,
window partitioning, and endogeneity flagging. Two integration tests on the cached real data
confirm the daily FF5+UMD result reproduces Finding 9 and that the live-ETF window starts
after currency inception.

There is nothing here that asserts an interpretation -- the module produces tables; the tests
verify the tables are computed correctly, not what they say.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tsmom import config, data, umd_investigation as ui


# --------------------------------------------------------------------------------------
# Unit tests -- deterministic, synthetic
# --------------------------------------------------------------------------------------


def test_to_monthly_compounds_correctly():
    idx = pd.bdate_range("2020-01-01", periods=42)  # ~2 months
    daily = pd.Series(0.01, index=idx)  # constant 1%/day
    m = ui.to_monthly(daily)
    # A month of k days of 1% compounds to 1.01^k - 1.
    jan = daily.loc["2020-01"]
    expected_jan = 1.01 ** len(jan) - 1.0
    assert abs(m.loc[m.index[0]] - expected_jan) < 1e-9


def test_regress_univariate_r2_equals_corr_squared():
    rng = np.random.default_rng(0)
    n = 500
    idx = pd.bdate_range("2010-01-01", periods=n)
    x = pd.Series(rng.normal(size=n), index=idx)
    y = 0.7 * x + pd.Series(rng.normal(scale=0.5, size=n), index=idx)
    r = ui.regress(y, x.to_frame("x"), nw_lags=3)
    row = r.iloc[0]
    assert set(["beta", "t_stat", "p_value", "corr", "r_squared", "n_obs"]).issubset(r.columns)
    assert abs(row["r_squared"] - row["corr"] ** 2) < 1e-9
    assert abs(row["beta"] - 0.7) < 0.1
    assert row["n_obs"] == n


def test_regress_guards_degenerate_input():
    idx = pd.bdate_range("2010-01-01", periods=50)
    y = pd.Series(np.arange(50.0), index=idx)
    const = pd.Series(1.0, index=idx)  # zero variance
    r = ui.regress(y, const.to_frame("c"), nw_lags=3)
    assert np.isnan(r.iloc[0]["beta"])  # returns NaN rather than raising


def test_apply_window_partitions_the_sample():
    idx = pd.bdate_range("2000-01-01", periods=100)
    s = pd.Series(1.0, index=idx)
    live = idx[60]
    full = ui.apply_window(s, "full", live)
    pre = ui.apply_window(s, "pre", live)
    liv = ui.apply_window(s, "live", live)
    assert len(full) == 100
    assert len(pre) + len(liv) == 100
    assert pre.index.max() < live <= liv.index.min()


def test_first_active_date_skips_leading_zeros():
    idx = pd.bdate_range("2005-01-01", periods=10)
    s = pd.Series([0.0, 0.0, 0.0, 0.01, -0.02, 0.0, 0.01, 0.0, 0.0, 0.03], index=idx)
    assert ui.first_active_date(s) == idx[3]


# --------------------------------------------------------------------------------------
# Integration tests -- cached real data
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def inp():
    return ui.load_inputs()


def test_sleeve_returns_four_sleeves_vol_targeted(inp):
    sr = inp.sleeve_daily
    assert list(sr.columns) == list(config.UNIVERSE.keys())
    from tsmom import metrics
    cap = 3.0 * config.PORTFOLIO_VOL_TARGET
    for c in sr.columns:
        assert metrics.annualized_vol(sr[c]) <= cap


def test_live_start_after_currency_inception(inp):
    # The currency ETFs start ~2006-2007; the live window must begin no earlier.
    assert inp.live_start.year >= 2006
    first_ccy = min(
        inp.prices[t].first_valid_index()
        for t in config.UNIVERSE["currency"] if t in inp.prices.columns
    )
    assert inp.live_start >= first_ccy


def test_daily_ff5_umd_reproduces_finding_9(inp):
    """Finding 9: per-sleeve FF5+UMD daily, currency UMD t ~ 7.31, equity ~ 10.77."""
    t = ui.sleeve_ff5_umd_regressions(inp, "full")
    daily = t[t["freq"] == "daily"].set_index("sleeve")
    assert abs(daily.loc["currency", "t_stat"] - 7.31) < 0.2
    assert abs(daily.loc["equity", "t_stat"] - 10.77) < 0.3
    # Every regression carries all six statistics.
    for col in ["beta", "t_stat", "p_value", "corr", "r_squared", "n_obs"]:
        assert col in t.columns


def test_frequency_shrinks_n_and_reports_r2(inp):
    t = ui.sleeve_umd_regressions(inp, "full")
    daily = t[t["freq"] == "daily"]
    monthly = t[t["freq"] == "monthly"]
    # Monthly has vastly fewer observations than daily (the overlap problem).
    assert monthly["n_obs"].iloc[0] < daily["n_obs"].iloc[0] / 10
    # R^2 is reported and bounded.
    assert t["r_squared"].between(0.0, 1.0).all()


def test_leave_one_out_returns_two_coefficients_per_sleeve(inp):
    lo = ui.leave_one_out_common_trend(inp, "full")
    assert set(lo["term"]) == {"UMD", "other_three_avg"}
    for s in config.UNIVERSE:
        assert len(lo[lo["sleeve"] == s]) == 2


def test_macro_controls_flag_endogenous_instruments(inp):
    mc = ui.macro_controls(inp, "full")
    ccy_uup = mc[(mc["sleeve"] == "currency") & (mc["control"] == "UUP")].iloc[0]
    fi_tlt = mc[(mc["sleeve"] == "fixed_income") & (mc["control"] == "TLT")].iloc[0]
    assert bool(ccy_uup["endogenous"]) is True
    assert bool(fi_tlt["endogenous"]) is True
    # A control that is NOT inside the sleeve is not flagged.
    eq_uup = mc[(mc["sleeve"] == "equity") & (mc["control"] == "UUP")].iloc[0]
    assert bool(eq_uup["endogenous"]) is False


def test_tail_concentration_has_regime_and_tail_conditions(inp):
    tc = ui.tail_concentration(inp, "full")
    conds = set(tc["condition"])
    assert {"all_months", "ex_top5pct_UMD", "ex_bot5pct_UMD", "worst10pct_portfolio"} <= conds
    assert any("high_vol" in c for c in conds)  # causal daily regime slice present
    assert tc["corr"].dropna().between(-1.0, 1.0).all()
