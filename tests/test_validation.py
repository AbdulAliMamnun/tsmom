"""Validation-layer tests.

The deliverable of STEP 4 is not the implementation -- it is these tests. They are written
in the same property-based spirit as tests/test_no_lookahead.py: a validation scheme that
itself leaks launders the leak behind a respectable method, so the leak-detection here is by
construction, not by inspection.

The load-bearing tests:
  - purged_indices: interval-based purge (holiday-robust), one-sided embargo, no over-purge.
  - walk_forward:   truncation invariance -- decisions made before t do not move when the
                    future is removed. If they do, selection is leaking.
  - cpcv:           training is disjoint from test AFTER purging, verified by recomputing
                    the interval intersection rather than trusting the purge.
  - PBO:            calibrated on synthetic noise (~0.5) and on a perfect predictor (~0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tsmom import config, data, validation


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    # Trending synthetic data, so different configs genuinely differ (needed for CPCV path
    # non-degeneracy) and the engine has real signal to select on.
    return data.synthetic_prices(
        tickers=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
        n_days=1600,
        seed=config.SEED,
        with_trend=True,
        trend_strength=0.0006,
    )


@pytest.fixture(scope="module")
def returns(prices: pd.DataFrame) -> pd.DataFrame:
    return data.to_returns(prices)


def _daily_index(n: int, start: str = "2010-01-04") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n)


# --------------------------------------------------------------------------------------
# 1. purged_indices -- the core primitive
# --------------------------------------------------------------------------------------


def test_purge_drops_overlapping_by_one_day():
    """A training label window overlapping a test window by even one day is dropped."""
    idx = _daily_index(200)
    horizon = 10
    labels = validation.label_intervals(idx, horizon=horizon)

    test_mask = pd.Series(False, index=idx)
    test_mask.iloc[100:110] = True  # test block

    usable = validation.purged_indices(labels, test_mask, embargo_days=0)

    # An observation at position 92: its label [idx[92], idx[102]] reaches into the test
    # block start (idx[100]) by two days -> must be purged.
    assert not usable.iloc[92]
    # Position 95 overlaps even more -> purged.
    assert not usable.iloc[95]


def test_purge_does_not_over_purge_adjacent():
    """An observation whose label ends exactly one day before the test block starts is KEPT.

    Over-purging is a real cost on a short sample (ENTRY 11); the boundary must be tight.
    """
    idx = _daily_index(200)
    horizon = 10
    labels = validation.label_intervals(idx, horizon=horizon)

    test_mask = pd.Series(False, index=idx)
    test_mask.iloc[100:110] = True

    usable = validation.purged_indices(labels, test_mask, embargo_days=0)

    # Position 89: label [idx[89], idx[99]] ends at idx[99], exactly one bar before the
    # block starts at idx[100]. No shared day -> KEPT.
    assert labels["t_end"].iloc[89] < labels["t_start"].iloc[100]
    assert usable.iloc[89]


def test_purge_alone_drops_all_overlaps_with_zero_embargo():
    """With embargo_days=0, purging alone still removes every overlapping observation."""
    idx = _daily_index(300)
    horizon = 21
    labels = validation.label_intervals(idx, horizon=horizon)

    test_mask = pd.Series(False, index=idx)
    test_mask.iloc[150:170] = True

    usable = validation.purged_indices(labels, test_mask, embargo_days=0)

    test_lo = labels["t_start"].iloc[150]
    test_hi = labels["t_end"].iloc[169]
    # Recompute the intersection independently and confirm nothing usable overlaps.
    overlaps = (labels["t_start"] <= test_hi) & (labels["t_end"] >= test_lo)
    assert not (usable & overlaps).any()


def test_embargo_is_forward_and_sized():
    """embargo_days=21: an obs starting 5 rows after the block is dropped; 30 rows kept.

    Built with horizon=1 so purge covers essentially no forward ground -- this isolates the
    embargo from the purge, otherwise the two effects would be indistinguishable.
    """
    idx = _daily_index(300)
    labels = validation.label_intervals(idx, horizon=1)

    test_mask = pd.Series(False, index=idx)
    test_mask.iloc[150:160] = True  # block ends at position 159

    usable = validation.purged_indices(labels, test_mask, embargo_days=21)

    # Position 164 = 5 rows after the block's last bar (159) -> inside the 21-row embargo.
    assert not usable.iloc[164]
    # Position 189 = 30 rows after -> outside the embargo, and horizon=1 means no purge
    # reaches it -> KEPT.
    assert usable.iloc[189]


def test_embargo_is_one_sided_before_block_is_untouched_by_embargo():
    """The embargo does not reach BEFORE the block; purging alone governs the before-side."""
    idx = _daily_index(300)
    labels = validation.label_intervals(idx, horizon=1)  # negligible purge

    test_mask = pd.Series(False, index=idx)
    test_mask.iloc[150:160] = True

    usable = validation.purged_indices(labels, test_mask, embargo_days=21)

    # Position 145 = 5 rows BEFORE the block. horizon=1 -> label [idx[145], idx[146]] does
    # not reach the block, and the embargo is forward-only -> KEPT.
    assert usable.iloc[145]


def test_purge_is_holiday_robust_by_date_not_row_count():
    """Insert a 4-day calendar gap; purging must still drop by DATE interval, not row count.

    If the implementation used index offsets, the gap would misalign the purge and the
    overlapping observation would survive. Interval-on-dates does not care about the gap.
    """
    base = list(_daily_index(120))
    # Splice a 4-calendar-day hole after position 100 by dropping the next few bdays.
    gapped = pd.DatetimeIndex(base[:101] + base[105:])
    horizon = 10
    labels = validation.label_intervals(gapped, horizon=horizon)

    # Test block right after the gap.
    test_mask = pd.Series(False, index=gapped)
    test_start_pos = 101  # first bar after the gap
    test_mask.iloc[test_start_pos : test_start_pos + 8] = True

    usable = validation.purged_indices(labels, test_mask, embargo_days=0)

    test_lo = labels["t_start"].iloc[test_start_pos]
    test_hi = labels["t_end"].iloc[test_start_pos + 7]
    overlaps = (labels["t_start"] <= test_hi) & (labels["t_end"] >= test_lo)

    # The purge decision matches the independently-recomputed DATE intersection exactly.
    assert (usable == (~overlaps & ~test_mask)).all()
    # And at least one pre-gap observation whose label spans the gap into the block is
    # dropped -- proving the gap did not shield it.
    assert overlaps.iloc[95]
    assert not usable.iloc[95]


def test_purged_training_is_disjoint_from_test():
    """No usable training observation's label may intersect the test union -- ever."""
    idx = _daily_index(400)
    labels = validation.label_intervals(idx, horizon=21)

    test_mask = pd.Series(False, index=idx)
    test_mask.iloc[200:240] = True

    usable = validation.purged_indices(labels, test_mask, embargo_days=21)

    test_lo = labels.loc[test_mask, "t_start"].min()
    test_hi = labels.loc[test_mask, "t_end"].max()
    for i in np.flatnonzero(usable.to_numpy()):
        assert not (
            labels["t_start"].iloc[i] <= test_hi and labels["t_end"].iloc[i] >= test_lo
        )


# --------------------------------------------------------------------------------------
# 2. walk_forward
# --------------------------------------------------------------------------------------


def test_walk_forward_runs_and_records_selections(prices, returns):
    res = validation.walk_forward(prices, returns)
    assert res.n_selections > 0
    assert len(res.oos_returns) > 0
    assert list(res.selections.columns) == ["date", "selected_config", "is_sharpe"]
    # Every selected config is a real grid member.
    grid_names = {c.name for c in config.parameter_grid()}
    assert set(res.selections["selected_config"]) <= grid_names


def test_walk_forward_selection_is_not_leaking(prices, returns):
    """Truncation invariance: decisions made before t are identical when the future is cut.

    This is THE walk-forward test (STEP_4_SPEC section 2). If truncating the price series
    changes an earlier selection, information from after the decision date reached the
    selection.
    """
    full = validation.walk_forward(prices, returns)

    # Truncate at a step boundary well inside the sample.
    cut = config.WF_MIN_TRAIN_DAYS + 5 * config.WF_STEP_DAYS
    trunc = validation.walk_forward(prices.iloc[:cut], returns.iloc[:cut])

    # Compare the selections both runs share, excluding the truncated run's final step
    # (the last bar's rebalance flag legitimately differs at the very edge of the sample).
    m = min(len(trunc.selections), len(full.selections)) - 1
    assert m >= 1
    full_sel = full.selections["selected_config"].iloc[:m].tolist()
    trunc_sel = trunc.selections["selected_config"].iloc[:m].tolist()
    assert full_sel == trunc_sel
    # Decision dates line up too.
    assert (
        full.selections["date"].iloc[:m].tolist()
        == trunc.selections["date"].iloc[:m].tolist()
    )


def test_walk_forward_churn_is_reported(prices, returns):
    res = validation.walk_forward(prices, returns)
    churn = res.selection_churn
    assert 0.0 <= churn <= 1.0


# --------------------------------------------------------------------------------------
# 3. cpcv
# --------------------------------------------------------------------------------------


def test_cpcv_has_15_splits_and_5_paths(prices, returns):
    res = validation.cpcv(prices, returns)
    assert res.n_splits == 15
    assert res.n_paths == 5
    assert res.paths.shape[1] == 5


def test_cpcv_training_disjoint_from_test_after_purge(prices, returns):
    """Every training set is disjoint from its test set AFTER purging -- verified by
    recomputing the interval intersection, not by assuming the purge worked."""
    from itertools import combinations

    idx = prices.index
    n = len(idx)
    vc = config.DEFAULT_VALIDATION
    groups = validation._contiguous_groups(n, vc.cpcv_n_groups)
    labels = validation.label_intervals(idx, vc.label_horizon_days)

    for combo in combinations(range(vc.cpcv_n_groups), vc.cpcv_n_test_groups):
        test_pos = np.concatenate([groups[g] for g in combo])
        test_mask = pd.Series(False, index=idx)
        test_mask.iloc[test_pos] = True

        usable = validation.purged_indices(labels, test_mask, vc.embargo_days)

        # Disjoint by position.
        assert not usable.to_numpy()[test_pos].any()

        # Disjoint by label interval, checked PER contiguous test block. (A min/max envelope
        # over two non-adjacent groups would wrongly cover the gap between them, where
        # training observations are legitimately usable -- the purge is per-block, so the
        # verification must be too.)
        overlaps = pd.Series(False, index=idx)
        for i0, i1 in validation._contiguous_blocks(test_pos):
            lo = labels["t_start"].iloc[i0]
            hi = labels["t_end"].iloc[i1]
            overlaps |= (labels["t_start"] <= hi) & (labels["t_end"] >= lo)
        assert not (usable & overlaps).any()


def test_cpcv_paths_have_non_degenerate_variance():
    """If all 5 paths were identical, the assembly (or selection) would be wrong.

    Uses DRIFTLESS data deliberately. On the strongly-trending fixture one config dominates
    every split, so all five paths collapse to that config -- a legitimate (if boring)
    outcome, not an assembly bug. On noise the in-sample-best config varies split to split,
    which is exactly what must produce distinct paths if the assembly is correct.
    """
    noisy = data.synthetic_prices(
        tickers=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
        n_days=1600,
        seed=config.SEED,
        with_trend=False,
    )
    res = validation.cpcv(noisy, data.to_returns(noisy))
    assert res.path_sharpes.std() > 0
    # Stronger: the paths are not literally the same series.
    assert res.paths.T.drop_duplicates().shape[0] > 1


# --------------------------------------------------------------------------------------
# 4. probability_of_backtest_overfitting
# --------------------------------------------------------------------------------------


def test_pbo_is_half_when_is_rank_is_noise():
    """In-sample rank independent of out-of-sample -> PBO ~ 0.5."""
    rng = np.random.default_rng(config.SEED)
    n_splits, n_configs = 400, 12
    is_sharpes = pd.DataFrame(rng.normal(size=(n_splits, n_configs)))
    oos_sharpes = pd.DataFrame(rng.normal(size=(n_splits, n_configs)))

    out = validation.probability_of_backtest_overfitting(is_sharpes, oos_sharpes)
    assert 0.4 <= out["pbo"] <= 0.6
    assert len(out["logits"]) == n_splits


def test_pbo_is_zero_when_is_perfectly_predicts_oos():
    """In-sample rank perfectly predicts out-of-sample -> PBO ~ 0."""
    rng = np.random.default_rng(config.SEED)
    n_splits, n_configs = 200, 12
    is_sharpes = pd.DataFrame(rng.normal(size=(n_splits, n_configs)))
    oos_sharpes = is_sharpes.copy()  # identical ranking

    out = validation.probability_of_backtest_overfitting(is_sharpes, oos_sharpes)
    assert out["pbo"] < 0.05
    # Logits should sit firmly positive (best IS config is best OOS -> top of the rank).
    assert np.median(out["logits"]) > 0


# --------------------------------------------------------------------------------------
# 5. embargo_sensitivity
# --------------------------------------------------------------------------------------


def test_embargo_sensitivity_table_shape(prices, returns):
    table = validation.embargo_sensitivity(prices, returns, embargos=[0, 21])
    assert list(table["embargo_days"]) == [0, 21]
    assert set(table.columns) == {
        "embargo_days",
        "mean_path_sharpe",
        "path_sharpe_std",
        "pbo",
        "mean_train_obs",
    }
    assert table["pbo"].between(0.0, 1.0).all()


def test_embargo_actually_reaches_purged_indices(prices, returns):
    """The embargo must genuinely vary the training set.

    Two properties, both from the purge/embargo interaction (not a heuristic):
      - embargos <= the label horizon (21) are SUBSUMED by the forward purge -> identical
        training-set sizes. Identical counts there are correct, not a bug.
      - an embargo EXCEEDING the horizon strictly shrinks the training set -> proof that
        embargo_days reaches purged_indices. If this failed, the parameter would be dead.
    """
    table = validation.embargo_sensitivity(prices, returns, embargos=[0, 5, 21, 63])
    sizes = dict(zip(table["embargo_days"], table["mean_train_obs"]))

    # Subsumption: everything at or below the horizon is identical.
    assert sizes[0] == sizes[5] == sizes[21]
    # Threading: crossing the horizon strictly reduces the training set.
    assert sizes[63] < sizes[21]
    # Monotone non-increasing overall.
    ordered = [sizes[e] for e in [0, 5, 21, 63]]
    assert all(a >= b for a, b in zip(ordered, ordered[1:]))
