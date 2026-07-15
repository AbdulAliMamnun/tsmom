# STEP 4 SPEC — Validation layer (Thread A machinery)

**For Claude Code.** Implement `src/tsmom/validation.py` plus `tests/test_validation.py`.

Read `docs/REASONING_LOG.md` entries 9–13 before writing code. They contain the *why* for
every design decision below; this spec contains the *what*. Where they conflict, the
reasoning log wins and the conflict is a bug in this spec.

**Non-negotiable:** `PYTHONPATH=src python3 run_checks.py` must still report 33/33 when you
are done. If a change to shared code breaks a leak test, the change is wrong.

---

## 0. Context you need

The engine is verified and produces real results:

- Primary config `lb252_vt40_rbM`, net Sharpe **0.706**, 6671 bars, 2000-01-03 → 2026-07-14.
- Effective diversified sample starts ~2007 (staggered ETF inception; UNG has 4840 bars).
- Ablation is clean: signal carries performance, vol scaling adds ~0.17.
- Parameter grid is **fixed at N=12** and pre-registered. Do not add configurations.

The pipeline for any config:
```python
pos = signals.target_positions(prices, r, cfg.lookback, cfg.vol_target,
                               tradeable=data.tradeable_mask(prices))
pos = signals.scale_to_portfolio_vol(pos, r)
pos = signals.apply_rebalance_schedule(pos, cfg.rebalance)
res = backtest.run_backtest(prices, pos)
```

---

## 1. `purged_indices(label_intervals, test_mask, embargo_days)` 

**The core primitive. Everything else depends on it being right.**

Signature:
```python
def purged_indices(
    label_intervals: pd.DataFrame,   # columns: t_start, t_end; index = observation index
    test_mask: pd.Series,            # bool, True where observation is in the test fold
    embargo_days: int,
) -> pd.Series:                      # bool, True where observation is USABLE for training
```

Semantics (REASONING_LOG entries 10 and 11):

1. **Purge.** Drop any training observation whose label interval `[t_start, t_end]`
   intersects the *union* of test label intervals. Use interval arithmetic, **not index
   offsets** — index offsets break on holidays and missing bars, which are everywhere in
   this data.
2. **Embargo.** Additionally drop training observations falling in the `embargo_days`
   *immediately after* each contiguous test block. One-sided, forward only. Purging already
   covers the before-side via overlap.
3. Test observations themselves are excluded from training (obviously).

Label horizon comes from `config.LABEL_HORIZON_DAYS` (currently 21). Build
`label_intervals` from the price index: for bar `i`, `t_start = index[i]`,
`t_end = index[min(i + horizon, len-1)]`.

**Must-have tests** (these are the deliverable, not the implementation):
- A training observation whose label window overlaps a test label window by even one day is
  dropped.
- A training observation ending exactly one day before the test block starts is **kept**
  (no over-purging — over-purging on a short sample is a real cost, see ENTRY 11).
- With `embargo_days=0`, purging alone still drops all overlapping observations.
- With `embargo_days=21`, an observation starting 5 days after a test block ends is dropped;
  one starting 30 days after is kept.
- Holiday robustness: insert a 4-day calendar gap into a synthetic index and verify purging
  still drops by *date interval*, not by row count.

---

## 2. `walk_forward(prices, returns, configs, validation_config)`

Expanding window. Per REASONING_LOG ENTRY 12.

```python
@dataclass
class WalkForwardResult:
    oos_returns: pd.Series          # concatenated out-of-sample path
    selections: pd.DataFrame        # columns: date, selected_config, is_sharpe
    n_selections: int
    fold_boundaries: list[tuple]
```

Algorithm:
1. Start at `config.WF_MIN_TRAIN_DAYS` (756).
2. At each step: fit all 12 configs on `[0, t]`, select the highest in-sample Sharpe,
   evaluate that config on `(t, t + WF_STEP_DAYS]` (63).
3. Step forward by `WF_STEP_DAYS`. Repeat.
4. Concatenate the OOS segments into one path.

**Critical:** the selection at step `t` must use only data through `t`. This is the whole
point of the method. Add a test:
- Truncate the price series at some `t`, run walk-forward, and verify the selections made
  before `t` are *identical* to those from the full-series run. If they differ, selection is
  leaking.

Record **which config was selected at each step**, not just the returns. Selection churn is
itself a finding: if the selected config changes every step, the "best" config is noise, and
that is worth reporting.

---

## 3. `cpcv(prices, returns, configs, validation_config)`

Combinatorial purged CV. Per REASONING_LOG ENTRY 13.

```python
@dataclass
class CPCVResult:
    paths: pd.DataFrame             # one column per path, index = date
    path_sharpes: pd.Series         # Sharpe of each path
    n_paths: int
    n_splits: int
```

Algorithm:
1. Partition the sample into `CPCV_N_GROUPS` (6) contiguous groups.
2. For each combination of `CPCV_N_TEST_GROUPS` (2) test groups: C(6,2) = **15 splits**.
3. For each split: purge + embargo the training set (using `purged_indices`), select the
   best config on the purged training data, evaluate on the test groups.
4. Assemble backtest paths from the test segments. With 6 groups choosing 2, each group
   appears in 5 splits → **5 complete paths**.

**Tests:**
- 15 splits, 5 paths. Assert exactly.
- Every training set is disjoint from its test set *after purging*, verified via interval
  intersection — not by assuming the purge worked.
- Path Sharpes have non-degenerate variance (if all 5 paths are identical, the assembly is
  wrong).

---

## 4. `probability_of_backtest_overfitting(configs_is_sharpe, configs_oos_sharpe)`

PBO via CSCV (Bailey et al.). 

The fraction of splits where the config with the best **in-sample** Sharpe lands below the
**median** out-of-sample Sharpe of the config set.

```python
def probability_of_backtest_overfitting(
    is_sharpes: pd.DataFrame,    # rows = splits, cols = configs
    oos_sharpes: pd.DataFrame,   # rows = splits, cols = configs
) -> dict:                       # {'pbo': float, 'logits': np.ndarray}
```

Return the logit distribution too, not just the scalar — the shape is informative and a
single number hides it.

**Tests:**
- Synthetic data where in-sample rank is pure noise w.r.t. out-of-sample → PBO should be ≈0.5.
- Synthetic data where in-sample rank perfectly predicts out-of-sample → PBO ≈ 0.

---

## 5. `embargo_sensitivity(prices, returns, configs)`

Run CPCV across `config.EMBARGO_SENSITIVITY` = [0, 5, 21, 63] days. Return a DataFrame:
embargo length × (mean path Sharpe, path Sharpe std, PBO).

Per REASONING_LOG ENTRY 11: **21 days is a convention, not a derived optimum.** The
defensible move is to show whether the conclusion moves. If it moves a lot, that is a
finding to report, not a parameter to tune until it stops moving.

---

## 6. What NOT to do

- **Do not** add configs to the grid. N=12 is pre-registered and feeds every correction.
- **Do not** write conclusions about which method to believe. That is Thread A and it is
  deferred to the author (see REASONING_LOG ENTRY 15 — it deliberately has no conclusion).
- **Do not** use `sklearn`'s `TimeSeriesSplit` or `KFold`. Neither purges. ENTRY 9 explains
  why they are invalid here.
- **Do not** silence a failing test without diagnosing it. ENTRY 17 Finding 3 is a case where
  a truncation-test failure was a *false positive* and "fixing" it would have mangled a
  correct engine. A failing test is evidence, not proof.

---

## 7. Definition of done

- [ ] `run_checks.py` still 33/33
- [ ] `tests/test_validation.py` passes, including every purging test above
- [ ] `scripts/run_validation.py` produces walk-forward and CPCV results on real data
- [ ] Results printed: WF Sharpe (point), CPCV path Sharpe distribution (mean/std/min/max),
      PBO, embargo sensitivity table
- [ ] Selection churn reported: how often does the selected config change?

Once this runs, paste the output. The interesting question — the one this whole project is
built toward — is whether the walk-forward point estimate falls inside or outside the CPCV
path distribution, and where they diverge.
