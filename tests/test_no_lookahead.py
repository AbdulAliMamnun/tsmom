"""Look-ahead detection.

THIS IS THE MOST IMPORTANT FILE IN THE REPOSITORY.

Every backtest author believes their engine has no look-ahead. The belief is worthless as
evidence. What separates a claim from a demonstration is a test that would have caught the
error had it been made.

These tests work by CONSTRUCTION, not by inspection. They do not check for specific known
bugs -- they check a *property* that no look-ahead can satisfy. That means they catch the
whole class, including the errors nobody thought to look for.

THREE LAYERS
------------
1. TRUNCATION INVARIANCE
   Compute f(series)[t]. Then compute f(series[:t])[t]. If they differ, f saw the future.
   This catches off-by-one indexing, centred rolling windows, full-sample normalisation,
   backward-fill -- everything -- with a single property.

2. FUTURE POISONING
   Overwrite everything after t with NaN. Recompute. If any output at or before t changes,
   something downstream reached forward.

3. POSITIVE CONTROL (the one people skip)
   A deliberately leaky function that these tests MUST fail on. Without it, a passing suite
   is uninformative: it might pass because it tests nothing. A test suite that has never
   been shown to fail is not evidence.

Layer 3 is what makes layers 1 and 2 credible. Run it first.

See docs/REASONING_LOG.md ENTRY 7.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tsmom import config, data, signals


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    """Synthetic prices. Deterministic, so a failure is reproducible."""
    return data.synthetic_prices(
        tickers=["AAA", "BBB", "CCC", "DDD"],
        n_days=1500,
        seed=config.SEED,
    )


@pytest.fixture(scope="module")
def returns(prices: pd.DataFrame) -> pd.DataFrame:
    return data.to_returns(prices)


# --------------------------------------------------------------------------------------
# LAYER 3 FIRST: the positive control
# --------------------------------------------------------------------------------------
# If this does not fail, the test methodology is broken and every "pass" below is
# meaningless. Establish that the tests can detect leakage before trusting that they
# detected none.


def _leaky_signal_centered(prices: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """DELIBERATELY BROKEN: centred rolling window sees `lookback/2` bars into the future.

    This is a realistic bug, not a strawman. `center=True` is a single keyword and the code
    reads perfectly naturally.
    """
    ma = prices.rolling(lookback, center=True, min_periods=1).mean()
    return np.sign(prices - ma)


def _leaky_signal_fullsample_zscore(prices: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """DELIBERATELY BROKEN: normalises by full-sample mean and std.

    Also realistic. Feels innocuous -- "I'm just standardising" -- but the full-sample mean
    includes every future observation.
    """
    mom = prices / prices.shift(lookback) - 1.0
    return np.sign((mom - mom.mean()) / mom.std())


def _leaky_signal_shift_negative(prices: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """DELIBERATELY BROKEN: shift(-1) reaches one bar forward.

    The classic 2am bug.

    Returns the CONTINUOUS series, deliberately. If you apply np.sign() first, a naive
    value-comparison harness can pass this control even though it is unambiguously leaky:
    sign() quantises to {-1, 0, +1}, so a one-bar shift usually lands on the same sign and
    the discrepancy vanishes. Test the continuous signal, not its discretised form.
    """
    mom = prices / prices.shift(lookback) - 1.0
    return mom.shift(-1)


def _truncation_invariance_violation(
    fn, prices: pd.DataFrame, test_points: list[int], **kwargs
) -> float:
    """Max absolute discrepancy between full-series and truncated-series evaluation.

    Returns 0.0 for a causal function, > 0 (or inf) for a leaky one.

    A HARNESS BUG WORTH KNOWING ABOUT. The obvious implementation guards with
    `both_valid = a.notna() & b.notna()` and skips points where either is NaN. That guard
    has a legitimate purpose -- warm-up periods produce NaN in BOTH series and comparing
    them is meaningless -- but it silently destroys the test.

    A leaky function evaluated on data truncated at t produces NaN at t *precisely because
    the future it wants to read is not there*. So `b` is NaN exactly at the point that
    proves the leak, `both_valid` is False, the point is skipped, and the harness reports a
    clean 0.0. The naive version reports PASS for `shift(-1)`.

    The distinction:
      - NaN in BOTH -> warm-up. Skip. Evidence of nothing.
      - NaN in TRUNCATED only, where FULL is valid -> the function needed data beyond t to
        produce a value. THAT IS THE LEAK.
    """
    full = fn(prices, **kwargs)
    max_diff = 0.0

    for t in test_points:
        truncated = fn(prices.iloc[: t + 1], **kwargs)
        a = full.iloc[t]
        b = truncated.iloc[t]

        # Truncation-induced NaN: full has a value, truncated does not.
        leaked_to_nan = a.notna() & b.isna()
        if bool(leaked_to_nan.any()):
            return float("inf")

        both_valid = a.notna() & b.notna()
        if both_valid.any():
            diff = (a[both_valid] - b[both_valid]).abs().max()
            max_diff = max(max_diff, float(diff))

    return max_diff


class TestPositiveControl:
    """These MUST fail the invariance check. If they pass, the methodology is broken."""

    def test_centered_rolling_is_detected(self, prices):
        violation = _truncation_invariance_violation(
            _leaky_signal_centered, prices, test_points=[500, 800, 1100]
        )
        assert violation > 0, (
            "POSITIVE CONTROL FAILED. A centred rolling window is unambiguous look-ahead, "
            "and the truncation test did not detect it. The test methodology is broken; "
            "every passing test below is uninformative."
        )

    def test_fullsample_zscore_is_detected(self, prices):
        violation = _truncation_invariance_violation(
            _leaky_signal_fullsample_zscore, prices, test_points=[500, 800, 1100]
        )
        assert violation > 0, (
            "POSITIVE CONTROL FAILED. Full-sample normalisation is look-ahead and was not "
            "detected."
        )

    def test_negative_shift_is_detected(self, prices):
        violation = _truncation_invariance_violation(
            _leaky_signal_shift_negative, prices, test_points=[500, 800, 1100]
        )
        assert violation > 0, (
            "POSITIVE CONTROL FAILED. shift(-1) is look-ahead and was not detected."
        )


# --------------------------------------------------------------------------------------
# LAYER 1: truncation invariance on the real engine
# --------------------------------------------------------------------------------------


class TestTruncationInvariance:
    """f(series)[t] must equal f(series[:t])[t] for every causal f."""

    TEST_POINTS = [400, 600, 900, 1200, 1400]

    def test_trailing_return(self, prices):
        v = _truncation_invariance_violation(
            signals.trailing_return, prices, self.TEST_POINTS, lookback=126
        )
        assert v == 0.0, f"trailing_return sees the future: max discrepancy {v}"

    def test_tsmom_signal(self, prices):
        v = _truncation_invariance_violation(
            signals.tsmom_signal, prices, self.TEST_POINTS, lookback=126
        )
        assert v == 0.0, f"tsmom_signal sees the future: max discrepancy {v}"

    def test_ewma_volatility(self, prices, returns):
        v = _truncation_invariance_violation(
            signals.ewma_volatility, returns, self.TEST_POINTS
        )
        assert v == 0.0, f"ewma_volatility sees the future: max discrepancy {v}"

    def test_target_positions(self, prices, returns):
        """The composed pipeline. Composition can leak even when each part is clean."""

        def fn(p: pd.DataFrame) -> pd.DataFrame:
            r = data.to_returns(p)
            return signals.target_positions(p, r, lookback=126, vol_target=0.40)

        full = fn(prices)
        for t in self.TEST_POINTS:
            truncated = fn(prices.iloc[: t + 1])
            a, b = full.iloc[t], truncated.iloc[t]
            both = a.notna() & b.notna()
            if both.any():
                diff = float((a[both] - b[both]).abs().max())
                assert diff < 1e-10, (
                    f"target_positions sees the future at t={t}: discrepancy {diff}"
                )

    def test_full_position_pipeline(self, prices):
        """Everything, end to end, including portfolio vol scaling and the rebalance
        schedule. This is the composition that actually runs in the backtest."""

        def fn(p: pd.DataFrame) -> pd.DataFrame:
            r = data.to_returns(p)
            tradeable = data.tradeable_mask(p)
            pos = signals.target_positions(
                p, r, lookback=126, vol_target=0.40, tradeable=tradeable
            )
            pos = signals.scale_to_portfolio_vol(pos, r)
            return signals.apply_rebalance_schedule(pos, freq="M")

        # Compare at t-1, not t. `apply_rebalance_schedule` forward-fills between
        # calendar-defined rebalance dates, and truncating at t makes bar t the last bar --
        # "is this the last bar of its month" legitimately changes when you delete every
        # bar after it. That is an artifact of truncation, not look-ahead: no future PRICE
        # is read, and the trading calendar is known in advance. Comparing strictly before
        # the boundary isolates the property under test.
        full = fn(prices)
        for t in [600, 900, 1200]:
            truncated = fn(prices.iloc[: t + 1])
            a, b = full.iloc[t - 1], truncated.iloc[t - 1]
            diff = float((a - b).abs().max())
            assert diff < 1e-8, (
                f"The full position pipeline sees the future at t={t}: discrepancy {diff}. "
                "Each component may be causal while the composition is not -- check "
                "scale_to_portfolio_vol, which is the usual culprit."
            )


# --------------------------------------------------------------------------------------
# LAYER 2: future poisoning
# --------------------------------------------------------------------------------------


class TestFuturePoisoning:
    """Overwrite the future with NaN. Nothing at or before t may change."""

    @pytest.mark.parametrize("poison_at", [700, 1000, 1300])
    def test_signal_unaffected_by_poisoned_future(self, prices, poison_at):
        clean = signals.tsmom_signal(prices, lookback=126)

        poisoned_prices = prices.copy()
        poisoned_prices.iloc[poison_at + 1 :] = np.nan
        poisoned = signals.tsmom_signal(poisoned_prices, lookback=126)

        a = clean.iloc[:poison_at + 1]
        b = poisoned.iloc[:poison_at + 1]

        both = a.notna() & b.notna()
        diff = float((a[both] - b[both]).abs().max()) if both.any().any() else 0.0
        assert diff == 0.0, (
            f"Poisoning the future at t={poison_at} changed the signal at or before t. "
            "Something reaches forward."
        )

    @pytest.mark.parametrize("poison_at", [700, 1000])
    def test_positions_unaffected_by_poisoned_future(self, prices, poison_at):
        def fn(p):
            r = data.to_returns(p)
            return signals.target_positions(p, r, lookback=126, vol_target=0.40)

        clean = fn(prices)
        poisoned_prices = prices.copy()
        poisoned_prices.iloc[poison_at + 1 :] = np.nan
        poisoned = fn(poisoned_prices)

        a = clean.iloc[: poison_at + 1]
        b = poisoned.iloc[: poison_at + 1]
        diff = float((a - b).abs().max().max())
        assert diff < 1e-10, (
            f"Poisoning the future at t={poison_at} changed positions at or before t: "
            f"discrepancy {diff}"
        )


# --------------------------------------------------------------------------------------
# Execution lag
# --------------------------------------------------------------------------------------


class TestExecutionLag:
    """The signal at t must be executed at t+1, never at t.

    This is the single most common look-ahead error in retail backtests, and it is nearly
    invisible on inspection: the array index is right there, off by one.
    """

    def test_backtest_applies_lag(self, prices):
        from tsmom import backtest

        r = data.to_returns(prices)
        pos = signals.target_positions(prices, r, lookback=126, vol_target=0.40)

        result = backtest.run_backtest(prices, pos, cost_model=config.COST_SCENARIOS[0])

        # The held position at t must equal the target position at t-1.
        held = result.positions_held
        expected = pos.shift(1).fillna(0.0)

        aligned_idx = held.index.intersection(expected.index)
        diff = float(
            (held.loc[aligned_idx] - expected.loc[aligned_idx]).abs().max().max()
        )
        assert diff < 1e-10, (
            f"Execution lag is not being applied: discrepancy {diff}. The position held at "
            "t must be the position TARGETED at t-1."
        )

    def test_same_bar_execution_would_be_detected(self, prices):
        """Control: a deliberately un-lagged backtest must differ from the lagged one.

        If these produce identical results, the lag test above proves nothing -- it would
        be passing on a series where the lag happens not to matter.
        """
        from tsmom import backtest

        r = data.to_returns(prices)
        pos = signals.target_positions(prices, r, lookback=126, vol_target=0.40)

        lagged = backtest.run_backtest(
            prices, pos, cost_model=config.COST_SCENARIOS[0]
        ).net_returns

        # Same-bar execution: position at t earns return at t. This is the bug.
        same_bar = (pos * r).sum(axis=1)

        common = lagged.index.intersection(same_bar.index)
        corr = float(lagged.loc[common].corr(same_bar.loc[common]))
        assert corr < 0.999, (
            "Lagged and same-bar execution are indistinguishable on this data, so the "
            "execution-lag test is uninformative. Use data where the lag matters."
        )


# --------------------------------------------------------------------------------------
# Negative control: no signal in noise
# --------------------------------------------------------------------------------------


class TestNegativeControl:
    """On a driftless random walk there is no trend. The engine must not find one."""

    def test_no_alpha_on_random_walk(self):
        from tsmom import backtest, metrics

        prices = data.synthetic_prices(
            tickers=[f"R{i}" for i in range(12)],
            n_days=3000,
            seed=999,
            with_trend=False,
        )
        r = data.to_returns(prices)
        tradeable = data.tradeable_mask(prices)
        pos = signals.target_positions(
            prices, r, lookback=252, vol_target=0.40, tradeable=tradeable
        )
        pos = signals.scale_to_portfolio_vol(pos, r)
        pos = signals.apply_rebalance_schedule(pos, freq="M")

        result = backtest.run_backtest(prices, pos, cost_model=config.BASE_COST)
        sharpe = metrics.sharpe_ratio(result.net_returns)

        # A generous bound. The point is to catch a broken engine reporting 2.0 on noise,
        # not to assert the sample Sharpe is exactly zero -- it won't be, and demanding
        # that would make this test flaky for no benefit.
        assert abs(sharpe) < 0.75, (
            f"Engine reports Sharpe {sharpe:.2f} on driftless random walks. There is no "
            "trend in this data by construction. Something is leaking."
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
