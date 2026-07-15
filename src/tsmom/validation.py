"""Validation layer -- the machinery of Thread A.

This module implements the purged/embargoed cross-validation schemes the project is built
to compare. It deliberately contains NO conclusion about which method to believe: that is
Thread A and it belongs to the author (docs/REASONING_LOG.md ENTRY 15). The job here is to
produce the numbers honestly, so the comparison can be made rather than asserted.

The design decisions are argued in docs/REASONING_LOG.md entries 9-13. In one line each:

  ENTRY 9   k-fold is invalid: overlapping labels leak, and confidently so.
  ENTRY 10  purging is defined by the LABEL HORIZON, via interval arithmetic, not index
            offsets -- offsets break on holidays, which are everywhere in this data.
  ENTRY 11  embargo is a one-sided (forward) convention; its length is not derived, so we
            report sensitivity across [0, 5, 21, 63] rather than tuning it.
  ENTRY 12  walk-forward answers the live-trading counterfactual but yields ONE path.
  ENTRY 13  CPCV yields a DISTRIBUTION but trains on the future -- a different estimand.

Everything below rests on `purged_indices` being correct, so it is tested hardest.

The single most important invariant this module preserves: selection at time t uses only
information available at t. It is verified by construction in tests/test_validation.py
(walk-forward truncation invariance and CPCV post-purge disjointness), the same
property-based style as tests/test_no_lookahead.py -- because a validation layer that itself
leaks is worse than none: it launders the leak behind a respectable-looking method.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

import numpy as np
import pandas as pd

from . import backtest, config, data, metrics, signals
from .config import ValidationConfig

# --------------------------------------------------------------------------------------
# The shared strategy pipeline
# --------------------------------------------------------------------------------------
#
# Every validation scheme evaluates configs through the SAME pipeline the real strategy
# uses (STEP_4_SPEC section 0). It is causal end to end -- verified by run_checks.py's
# composed-pipeline truncation test -- which is what lets us precompute each config's
# full-sample net-return path ONCE and then slice it per fold. Slicing a causal series at
# t is identical to having run the pipeline live through t; that identity is the whole
# reason the walk-forward truncation test passes.


def strategy_net_returns(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    cfg: config.StrategyConfig,
    tradeable: pd.DataFrame | None = None,
) -> pd.Series:
    """Net return path for one config, through the standard pipeline."""
    if tradeable is None:
        tradeable = data.tradeable_mask(prices)
    pos = signals.target_positions(
        prices, returns, cfg.lookback, cfg.vol_target, tradeable=tradeable
    )
    pos = signals.scale_to_portfolio_vol(pos, returns)
    pos = signals.apply_rebalance_schedule(pos, cfg.rebalance)
    res = backtest.run_backtest(prices, pos, cost_model=config.BASE_COST, returns=returns)
    return res.net_returns


def _config_return_panel(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    configs: list[config.StrategyConfig],
) -> pd.DataFrame:
    """One column of net returns per config, indexed by the price calendar."""
    tradeable = data.tradeable_mask(prices)
    return pd.DataFrame(
        {cfg.name: strategy_net_returns(prices, returns, cfg, tradeable) for cfg in configs}
    )


def _best_by_sharpe(sharpes: dict[str, float]) -> str:
    """Argmax over a dict of Sharpes, treating NaN as -inf so it never wins."""
    return max(
        sharpes,
        key=lambda name: sharpes[name] if pd.notna(sharpes[name]) else -np.inf,
    )


# --------------------------------------------------------------------------------------
# 1. Purging + embargo -- the core primitive
# --------------------------------------------------------------------------------------


def label_intervals(
    index: pd.DatetimeIndex,
    horizon: int = config.LABEL_HORIZON_DAYS,
) -> pd.DataFrame:
    """Each observation's label window [t_start, t_end], by DATE.

    For bar i the label spans forward `horizon` bars: t_start = index[i], t_end =
    index[min(i + horizon, len - 1)]. The interval is what purging intersects against;
    representing it as dates (not row offsets) is what makes purging robust to holidays and
    missing bars -- the point of ENTRY 10.
    """
    n = len(index)
    end_pos = np.minimum(np.arange(n) + horizon, n - 1)
    return pd.DataFrame(
        {"t_start": index, "t_end": index[end_pos]},
        index=index,
    )


def _contiguous_blocks(positions: np.ndarray) -> list[tuple[int, int]]:
    """Collapse a sorted array of row positions into (first, last) contiguous runs."""
    if len(positions) == 0:
        return []
    blocks = []
    start = prev = positions[0]
    for p in positions[1:]:
        if p == prev + 1:
            prev = p
        else:
            blocks.append((start, prev))
            start = prev = p
    blocks.append((start, prev))
    return blocks


def purged_indices(
    label_intervals: pd.DataFrame,
    test_mask: pd.Series,
    embargo_days: int,
) -> pd.Series:
    """Boolean series: True where an observation is USABLE for TRAINING.

    Semantics (ENTRY 10 and ENTRY 11):

      1. PURGE. Drop any training observation whose label interval [t_start, t_end]
         intersects the union of the test observations' label intervals. Interval
         arithmetic on DATES -- never row offsets, which break on holidays. Two closed
         intervals [a, b] and [c, d] intersect iff a <= d and c <= b; touching at a single
         shared day counts, because a shared day is shared information.
      2. EMBARGO. Additionally drop the `embargo_days` training rows immediately AFTER each
         contiguous test block. One-sided, forward only -- purging already covers the
         before-side through overlap, so the embargo exists solely for the forward serial-
         correlation channel overlap logic misses.
      3. Test observations are never usable for training.
    """
    index = label_intervals.index
    n = len(index)

    test_mask = test_mask.reindex(index).fillna(False).astype(bool)
    test_pos = np.flatnonzero(test_mask.to_numpy())

    usable = ~test_mask.to_numpy().copy()
    if len(test_pos) == 0:
        return pd.Series(usable, index=index)

    t_start = label_intervals["t_start"].to_numpy()
    t_end = label_intervals["t_end"].to_numpy()

    for i0, i1 in _contiguous_blocks(test_pos):
        # Union of the block's label intervals is one interval, since consecutive bars'
        # windows overlap: [t_start[i0], t_end[i1]].
        purge_lo, purge_hi = t_start[i0], t_end[i1]
        overlaps = (t_start <= purge_hi) & (t_end >= purge_lo)
        usable &= ~overlaps

        # Forward embargo: the rows immediately after the block's LAST bar (not after its
        # label end -- the embargo is measured from the test observations themselves).
        if embargo_days > 0:
            hi = min(i1 + embargo_days, n - 1)
            usable[i1 + 1 : hi + 1] = False

    # Belt and braces: test rows are never trainable regardless of the interval algebra.
    usable[test_pos] = False
    return pd.Series(usable, index=index)


# --------------------------------------------------------------------------------------
# 2. Walk-forward -- the live-trading counterfactual (ENTRY 12)
# --------------------------------------------------------------------------------------


@dataclass
class WalkForwardResult:
    oos_returns: pd.Series          # concatenated out-of-sample path
    selections: pd.DataFrame        # columns: date, selected_config, is_sharpe
    n_selections: int
    fold_boundaries: list[tuple]

    @property
    def selection_churn(self) -> float:
        """Fraction of steps at which the selected config changed from the prior step.

        A high churn is itself a finding (STEP_4_SPEC section 2): if the 'best' config
        changes every quarter, 'best' is noise.
        """
        sel = self.selections["selected_config"]
        if len(sel) < 2:
            return 0.0
        return float((sel.values[1:] != sel.values[:-1]).mean())


def walk_forward(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    configs: list[config.StrategyConfig] | None = None,
    validation_config: ValidationConfig = config.DEFAULT_VALIDATION,
) -> WalkForwardResult:
    """Expanding-window walk-forward.

    At each step: fit all configs on [0, t], select the highest IN-SAMPLE Sharpe, evaluate
    THAT config on (t, t + step]. Step forward and repeat; concatenate the OOS segments.

    The selection at step t uses only data through t -- the whole point of the method
    (ENTRY 12). Here it is guaranteed structurally: the per-config return panel is causal,
    so the in-sample slice [0:t] cannot contain information from after t. The truncation
    test in tests/test_validation.py checks this by construction.
    """
    configs = configs or config.parameter_grid()
    panel = _config_return_panel(prices, returns, configs)

    index = prices.index
    n = len(index)
    min_train = validation_config.wf_min_train_days
    step = validation_config.wf_step_days

    oos_segments: list[pd.Series] = []
    selection_rows: list[dict] = []
    fold_boundaries: list[tuple] = []

    t = min_train
    while t < n:
        train = panel.iloc[:t]
        is_sharpes = {name: metrics.sharpe_ratio(train[name]) for name in panel.columns}
        best = _best_by_sharpe(is_sharpes)

        hi = min(t + step, n)
        oos_segments.append(panel[best].iloc[t:hi])
        selection_rows.append(
            {"date": index[t], "selected_config": best, "is_sharpe": is_sharpes[best]}
        )
        fold_boundaries.append((index[t], index[hi - 1]))
        t += step

    oos_returns = (
        pd.concat(oos_segments) if oos_segments else pd.Series(dtype=float)
    )
    return WalkForwardResult(
        oos_returns=oos_returns,
        selections=pd.DataFrame(selection_rows),
        n_selections=len(selection_rows),
        fold_boundaries=fold_boundaries,
    )


# --------------------------------------------------------------------------------------
# 3. CPCV -- the DGP-stability distribution (ENTRY 13)
# --------------------------------------------------------------------------------------


@dataclass
class CPCVResult:
    paths: pd.DataFrame             # one column per assembled path, index = date
    path_sharpes: pd.Series         # Sharpe of each path
    n_paths: int
    n_splits: int


def _contiguous_groups(n: int, n_groups: int) -> list[np.ndarray]:
    """Partition row positions [0, n) into `n_groups` contiguous groups."""
    bounds = np.linspace(0, n, n_groups + 1).astype(int)
    return [np.arange(bounds[g], bounds[g + 1]) for g in range(n_groups)]


def _cpcv_run(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    configs: list[config.StrategyConfig],
    validation_config: ValidationConfig,
) -> dict:
    """Shared CPCV engine. Returns paths plus the per-split IS/OOS Sharpe matrices (the
    matrices feed PBO and embargo sensitivity; the public `cpcv` exposes only the paths)."""
    panel = _config_return_panel(prices, returns, configs)
    names = list(panel.columns)
    index = prices.index
    n = len(index)

    n_groups = validation_config.cpcv_n_groups
    k = validation_config.cpcv_n_test_groups
    groups = _contiguous_groups(n, n_groups)
    labels = label_intervals(index, validation_config.label_horizon_days)

    combos = list(combinations(range(n_groups), k))

    is_rows: list[dict] = []
    oos_rows: list[dict] = []
    train_sizes: list[int] = []
    # per_group_segments[g] accumulates, in split order, the selected config's returns on
    # group g. Each group is a test group in C(n_groups-1, k-1) splits; the p-th of those
    # occurrences becomes path p (the standard AFML Ch. 12 assembly).
    per_group_segments: dict[int, list[pd.Series]] = {g: [] for g in range(n_groups)}

    for combo in combos:
        test_pos = np.concatenate([groups[g] for g in combo])
        test_mask = pd.Series(False, index=index)
        test_mask.iloc[test_pos] = True

        usable = purged_indices(labels, test_mask, validation_config.embargo_days)
        train_rows = usable.to_numpy()
        train_sizes.append(int(train_rows.sum()))

        is_sharpes = {name: metrics.sharpe_ratio(panel[name][train_rows]) for name in names}
        oos_sharpes = {
            name: metrics.sharpe_ratio(panel[name].iloc[test_pos]) for name in names
        }
        is_rows.append(is_sharpes)
        oos_rows.append(oos_sharpes)

        best = _best_by_sharpe(is_sharpes)
        for g in combo:
            per_group_segments[g].append(panel[best].iloc[groups[g]])

    n_paths = len(combos) * k // n_groups
    paths = {}
    for p in range(n_paths):
        pieces = [per_group_segments[g][p] for g in range(n_groups)]
        paths[f"path_{p}"] = pd.concat(pieces).sort_index()
    paths_df = pd.DataFrame(paths)

    path_sharpes = pd.Series(
        {name: metrics.sharpe_ratio(paths_df[name]) for name in paths_df.columns}
    )

    return {
        "paths": paths_df,
        "path_sharpes": path_sharpes,
        "is_sharpes": pd.DataFrame(is_rows),
        "oos_sharpes": pd.DataFrame(oos_rows),
        "train_sizes": train_sizes,
        "n_paths": n_paths,
        "n_splits": len(combos),
    }


def cpcv(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    configs: list[config.StrategyConfig] | None = None,
    validation_config: ValidationConfig = config.DEFAULT_VALIDATION,
) -> CPCVResult:
    """Combinatorial purged cross-validation.

    Partition into `cpcv_n_groups` contiguous groups; for every choice of
    `cpcv_n_test_groups` test groups, purge+embargo the training set, select the best
    config on the purged training data, and evaluate it on the test groups. Assemble the
    test segments into complete backtest paths.

    With 6 groups choosing 2: C(6,2) = 15 splits, and each group is tested in 5 of them,
    yielding 5 complete paths (ENTRY 13).
    """
    configs = configs or config.parameter_grid()
    r = _cpcv_run(prices, returns, configs, validation_config)
    return CPCVResult(
        paths=r["paths"],
        path_sharpes=r["path_sharpes"],
        n_paths=r["n_paths"],
        n_splits=r["n_splits"],
    )


# --------------------------------------------------------------------------------------
# 4. Probability of Backtest Overfitting (CSCV, Bailey et al.)
# --------------------------------------------------------------------------------------


def probability_of_backtest_overfitting(
    is_sharpes: pd.DataFrame,
    oos_sharpes: pd.DataFrame,
) -> dict:
    """PBO via CSCV.

    Per split, take the config with the best IN-SAMPLE Sharpe and ask where its
    OUT-OF-SAMPLE Sharpe falls in the OOS distribution of the config set. PBO is the
    fraction of splits where it lands BELOW the OOS median -- i.e. where in-sample
    selection actively misled.

    Returns the scalar plus the full logit distribution (`logit = ln(w / (1 - w))` for the
    best config's relative OOS rank w). The shape of that distribution is informative and a
    single number hides it, so it is returned too.
    """
    is_sharpes = is_sharpes.reset_index(drop=True)
    oos_sharpes = oos_sharpes.reset_index(drop=True)

    logits: list[float] = []
    below_median: list[bool] = []

    for i in range(len(is_sharpes)):
        is_row = is_sharpes.iloc[i]
        oos_row = oos_sharpes.iloc[i]
        if is_row.isna().all() or oos_row.dropna().empty:
            continue

        best = is_row.idxmax()
        oos_best = oos_row[best]
        if pd.isna(oos_best):
            continue

        below_median.append(bool(oos_best < oos_row.median()))

        valid = oos_row.dropna()
        n = len(valid)
        # Relative rank with mid-rank tie handling, mapped off the {0, 1} boundary.
        rank = float((valid < oos_best).sum() + 0.5 * (valid == oos_best).sum())
        w = min(max(rank / n, 1e-6), 1.0 - 1e-6)
        logits.append(float(np.log(w / (1.0 - w))))

    pbo = float(np.mean(below_median)) if below_median else float("nan")
    return {"pbo": pbo, "logits": np.array(logits)}


# --------------------------------------------------------------------------------------
# 5. Embargo sensitivity (ENTRY 11)
# --------------------------------------------------------------------------------------


def embargo_sensitivity(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    configs: list[config.StrategyConfig] | None = None,
    embargos: list[int] | None = None,
    validation_config: ValidationConfig = config.DEFAULT_VALIDATION,
) -> pd.DataFrame:
    """Re-run CPCV across a range of embargo lengths.

    21 days is a convention, not a derived optimum (ENTRY 11). The honest move is to show
    whether the conclusion moves with the embargo; if it moves a lot, that is a finding to
    report, not a knob to turn until it stops moving.

    Returns one row per embargo length: mean path Sharpe, path Sharpe std, PBO, and the
    mean per-split training-set size (`mean_train_obs`) -- the last so it is visible, and
    assertable, that the embargo parameter is actually reaching `purged_indices`.

    VERIFICATION (do not remove). The natural check "usable training obs strictly decreases
    as embargo grows" is WRONG on correct code: with a `label_horizon_days` forward purge,
    any embargo <= that horizon is fully subsumed by the purge and removes zero additional
    rows. So the counts for embargos 0, 5, 21 are legitimately identical at horizon=21; only
    an embargo EXCEEDING the horizon bites. The correct, still-strict invariant is therefore:

      1. usable training obs is monotone NON-increasing in embargo, and
      2. an embargo strictly greater than the label horizon strictly reduces the training
         set relative to an embargo <= the horizon.

    If (2) fails, embargo_days is not reaching purged_indices -- which is exactly the bug
    identical counts would otherwise hide.
    """
    configs = configs or config.parameter_grid()
    embargos = embargos if embargos is not None else config.EMBARGO_SENSITIVITY
    horizon = validation_config.label_horizon_days

    rows = []
    totals: dict[int, int] = {}
    for e in embargos:
        vc = replace(validation_config, embargo_days=e)
        r = _cpcv_run(prices, returns, configs, vc)
        pbo = probability_of_backtest_overfitting(r["is_sharpes"], r["oos_sharpes"])["pbo"]
        ps = r["path_sharpes"]
        total_train = int(sum(r["train_sizes"]))
        totals[e] = total_train
        rows.append(
            {
                "embargo_days": e,
                "mean_path_sharpe": float(ps.mean()),
                "path_sharpe_std": float(ps.std()),
                "pbo": pbo,
                "mean_train_obs": round(total_train / r["n_splits"]),
            }
        )
    table = pd.DataFrame(rows)

    # ---- verify the embargo actually varies ------------------------------------------
    ordered = sorted(totals.items())  # by embargo ascending
    print(f"\n[embargo check] usable training obs across all splits (label horizon = {horizon}d):")
    for e, t in ordered:
        note = "subsumed by purge" if e <= horizon else "beyond horizon -> bites"
        print(f"    embargo={e:3d}   total_train={t:>7d}   ({note})")

    totals_sorted = [t for _, t in ordered]
    if any(a < b for a, b in zip(totals_sorted, totals_sorted[1:])):
        raise AssertionError(
            f"usable training obs must be non-increasing in embargo; got {ordered}"
        )

    le = [(e, t) for e, t in ordered if e <= horizon]
    gt = [(e, t) for e, t in ordered if e > horizon]
    if le and gt:
        base_e, base_t = max(le)          # largest embargo still <= horizon (most subsumed)
        top_e, top_t = max(gt)            # largest embargo overall (exceeds horizon)
        if not top_t < base_t:
            raise AssertionError(
                f"embargo={top_e} exceeds the label horizon ({horizon}d) but did not reduce "
                f"the training set relative to embargo={base_e} ({top_t} vs {base_t}) -- "
                f"embargo_days is not reaching purged_indices."
            )

    return table
