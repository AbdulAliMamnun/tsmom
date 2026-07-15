# STEP 5 SPEC — Multiple testing & effective-N (Thread B machinery)

**For Claude Code.** Implement `src/tsmom/multiple_testing.py`, `src/tsmom/factor_model.py`,
and `tests/test_multiple_testing.py`.

Read `docs/REASONING_LOG.md` **ENTRY 14** (DSR machinery) and **ENTRY 16** (Thread B framing)
before writing code. They contain the reasoning; this contains the specification. Where they
conflict, the reasoning log wins and the conflict is a bug in this spec.

**Non-negotiable:** `PYTHONPATH=src python3 run_checks.py` must still report 33/33 when done.

---

## 0. Context

Established results (see `docs/RESULTS_LOG.md`):

- Primary config `lb252_vt40_rbM`: net Sharpe **0.706**, skew **-0.387**, kurtosis **7.796**,
  6671 bars.
- Ablation clean: signal carries performance (random-sign control earns -0.045 net).
- Walk-forward OOS Sharpe **0.631**, selection churn **6.5%**, prefers `lb126_vt20_rbM` (64%).
- CPCV: 15 splits → 5 paths, path Sharpe mean **0.606**, std **0.059**, range [0.546, 0.706].
- **PBO = 0.400.**
- Grid is **fixed at N=12**, pre-registered. Do not add configurations.

**The skew/kurtosis matter.** -0.387 skew and 7.796 kurtosis are exactly what PSR/DSR correct
for. A naive Sharpe t-test would overstate significance here. That is the point of the module.

---

## 1. `trial_returns(prices, returns, configs)` — the input everything needs

Run all 12 configs through the standard pipeline, return a DataFrame: index = date, one
column per config, values = net returns.

```python
def trial_returns(prices, returns, configs) -> pd.DataFrame
```

Pipeline per config (identical to the real strategy — no shortcuts):
```python
pos = signals.target_positions(prices, r, cfg.lookback, cfg.vol_target,
                               tradeable=data.tradeable_mask(prices))
pos = signals.scale_to_portfolio_vol(pos, r)
pos = signals.apply_rebalance_schedule(pos, cfg.rebalance)
res = backtest.run_backtest(prices, pos)
```

**Test:** each column's realised annualised vol within 3× `PORTFOLIO_VOL_TARGET`. Same guard
as `ablation()` — Run 3's blown-up arms printed a plausible-looking table and meant nothing.

---

## 2. Effective-N estimators

**This is the heart of Thread B.** Signature for each: takes the trial-return DataFrame,
returns a float.

```python
def effective_n_naive(trial_rets) -> float          # = number of columns. 12.
def effective_n_rho_bar(trial_rets) -> float        # Bailey & LdP's own remedy
def effective_n_participation(trial_rets) -> float  # (sum λ)² / sum(λ²)
def effective_n_variance_95(trial_rets) -> float    # components explaining 95% of variance
def effective_n_entropy(trial_rets) -> float        # entropy-based effective rank
def effective_n_clustering(trial_rets) -> float     # correlation-clustering count
```

Details:

- **rho_bar:** `N_hat = rho_bar + (1 - rho_bar) * M`, where `rho_bar` = mean off-diagonal
  correlation of trial returns, `M` = 12. Per ENTRY 16 this assumes a single common
  correlation, which is false for a structured matrix. Implement it anyway — it is the
  literature's remedy and the comparison is the point.
- **participation ratio:** eigendecompose the correlation matrix. `(Σλᵢ)² / Σλᵢ²`.
- **variance_95:** count of eigenvalues (sorted desc) whose cumulative share ≥ 0.95.
- **entropy:** `exp(-Σ pᵢ ln pᵢ)` where `pᵢ = λᵢ / Σλ`. Effective rank.
- **clustering:** hierarchical clustering on the correlation distance matrix
  (`d = sqrt(2(1-ρ))`), count clusters at a stated threshold. **The threshold is arbitrary and
  that is itself the finding** — report the cluster count as a function of threshold, not a
  single number. ENTRY 16 flags this: it imports a new arbitrary parameter to solve an
  arbitrary-parameter problem.

Return a tidy DataFrame from `all_effective_n(trial_rets)`: method → estimate.

**Tests:**
- 12 identical columns → every estimator ≈ 1.0 (one bet, repeated).
- 12 independent columns → every estimator ≈ 12.0.
- Estimators are bounded in [1, 12] on real data. If one isn't, it's wrong.

---

## 3. `effective_n_uncertainty(trial_rets, n_boot=1000)`

**ENTRY 16 requires this and it is not optional.**

> "Effective-N estimation on 12 series with limited history is *itself* noisy. The eigenvalue
> spectrum of a 12×12 correlation matrix estimated from a short sample has large sampling
> error. **The uncertainty in N_eff must be reported, not just the point estimate.** Failing
> to do so would repeat, one level up, exactly the error being diagnosed one level down."

Stationary bootstrap (Politis-Romano) over the trial-return series, preserving serial
correlation — block bootstrap, not iid resampling. Recompute every estimator per replicate.
Return point estimate + 95% CI per method.

**If the CIs are wide, that is a finding, not a failure.** Report them.

---

## 4. `dsr_curve(returns, trial_rets, n_range)`

**The money output of the entire project.**

```python
def dsr_curve(returns, trial_rets, n_range=np.arange(1, 13, 0.25)) -> pd.DataFrame
```

For each assumed N: compute `expected_max_sharpe(N, var(trial_sharpes))` then the DSR of the
primary config's returns against it. Columns: `assumed_n`, `sr0`, `dsr`, `passes_95`.

Also return **`flip_point`**: the N at which DSR crosses 0.95. Interpolate — do not round to
integers. N_eff is not an integer and pretending otherwise hides the finding.

The shape of the result to aim for (ENTRY 16):

> *"The strategy passes DSR at 95% under an effective-N accounting (N_eff ≈ X) and fails under
> naive accounting (N = 12). The verdict flips at N = Y."*

**This shows the DSR verdict is not a fact about the strategy but a function of an
unobservable — and quantifies exactly how sensitive it is.** That is the result.

**Tests:**
- DSR monotone non-increasing in assumed N.
- `flip_point` correctly identified on synthetic data with a known crossing.
- N=1 → SR0 = 0 → DSR = PSR vs zero.

---

## 5. `harvey_liu_haircuts(trial_rets, primary_config_name)`

Bonferroni, Holm, and BHY haircuts on the primary config's Sharpe.

Return a DataFrame: method → adjusted p-value → haircut Sharpe → passes at 5%.

Note in the docstring: these treat trials as independent, which they are not — same objection
as naive N=12. Report alongside DSR, not instead of it.

---

## 6. `factor_regression(net_returns, ff_factors)`

`src/tsmom/factor_model.py`.

Regress the primary config's net returns on Ken French factors (Mkt-RF, SMB, HML, RMW, CMA,
UMD). Report: alpha (annualised), t-stat, per-factor betas + t-stats, R², N.

**Use Newey-West standard errors** (lag ≈ 21). OLS standard errors on autocorrelated returns
overstate significance, which would undercut the whole point of the module.

Ken French daily factors must be downloaded manually to `data/raw/ff_factors_daily.csv` —
`data.load_ff_factors()` expects this and raises a clear error if absent.

**The question this answers:** is the 0.706 alpha, or is it repackaged known factor exposure?
UMD (momentum) is the one to watch — a time-series momentum strategy loading heavily on
cross-sectional momentum would be an interesting and slightly awkward result.

---

## 7. `subperiod_analysis(net_returns)`

Per pre-registration §5.1: **no full-sample Sharpe is presented as the headline without its
sub-period decomposition.**

- By calendar period: 2000-2007 (pre-diversification — see Run 1, effective sample starts
  ~2007), 2008-2015, 2016-2026.
- By volatility regime: split on trailing realised vol tertiles (causally — trailing, not
  full-sample; this is the same hazard as ENTRY 17 Finding 1).

Report Sharpe, return, vol, max drawdown per bucket.

---

## 8. What NOT to do

- **Do not** add configs. N=12 is pre-registered.
- **Do not** write the Thread B conclusion — which effective-N estimate is correct, or which
  DSR verdict governs. ENTRY 16 deliberately has no conclusion. That is the author's.
- **Do not** report a single effective-N as "the" answer. The output is the *curve* and the
  *flip point*.
- **Do not** use iid bootstrap for the CIs. Serial correlation is the whole reason these
  series aren't independent.

---

## 9. Definition of done

- [ ] `run_checks.py` still 33/33
- [ ] `tests/test_multiple_testing.py` passes, including the identical-columns → N_eff≈1 and
      independent-columns → N_eff≈12 controls
- [ ] `scripts/run_multiple_testing.py` produces on real data:
  - all 12 config Sharpes (disclosed regardless of outcome — pre-registration §5.1)
  - trial-return correlation matrix
  - every effective-N estimate **with bootstrap CIs**
  - DSR at N=12 (naive) and at each N_eff estimate
  - **the DSR-vs-N curve and the flip point**
  - Harvey-Liu haircuts
  - factor regression with Newey-West
  - sub-period and vol-regime tables

Paste the output when it runs.

**The question to have in mind:** where does the flip point fall relative to the plausible
range of N_eff? If it falls *inside* that range, the honest conclusion is that the sample
cannot resolve whether this strategy has an edge — and per ENTRY 16, that is a legitimate and
reportable finding, not a failure.

There is also a live thread from Run 5 worth holding: PBO = 0.40 with selection churn of only
6.5% suggests in-sample ranking across 12 near-duplicate configs may be uninformative. If so,
PBO and effective-N are measuring related things from opposite directions. The correlation
matrix from §1 is the first place to look for evidence.
