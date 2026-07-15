# Pre-Registration

**Status: COMMITTED BEFORE ANY RESULTS WERE OBSERVED.**

This document is written and git-committed before the backtest engine produces a single
performance number. Its purpose is to fix the hypothesis, the parameter grid, and the
evaluation criteria *in advance*, so that the multiple-testing corrections applied later
(Section 5) are honest rather than reconstructed.

If you are reading this repo to evaluate the research: check `git log` for this file's
commit timestamp against the commit timestamps of anything in `results/`. The ordering is
the evidence.

---

## 1. Hypothesis

**H1 (primary).** In a diversified cross-section of liquid ETFs spanning equity indices,
fixed income, commodities and currencies, an instrument's own trailing 12-month excess
return positively predicts the sign of its next-period return. A portfolio that goes long
instruments with positive trailing 12-month returns and short those with negative trailing
12-month returns, with each position scaled inversely to its own recent volatility, earns a
positive risk-adjusted return.

This is a **replication hypothesis**, not a discovery hypothesis. It is the central claim of
Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum," *Journal of Financial Economics*
104(2), 228-250, tested there on 58 liquid futures contracts over 1985-2009.

**H0 (null).** The strategy's out-of-sample Sharpe ratio, net of realistic transaction
costs, is not distinguishable from what would be expected from the best of N skill-less
trials on this sample.

### 1.1 Why a replication and not a novel signal

Stating this plainly because it is a deliberate design choice, not a limitation:

A solo researcher on free data will not discover a novel, uncorrelated, capacity-bearing
alpha. Any signal findable this way is known, decayed, or too small to trade. Claiming
otherwise would itself be a credibility failure. The research contribution of this project
is therefore **not** the signal. It is:

1. A demonstration that the replication is performed without self-deception (Section 3-4).
2. Two open methodological questions that the rigorous replication *surfaces*, which are
   genuinely unresolved in the literature (Section 6).

The value is in (2), and (2) is only credible because of (1).

### 1.2 Expected outcome, stated in advance

I expect the net-of-cost, deflated Sharpe ratio to be **modest and possibly not
significant at the 95% level**. Published in-sample results from the 1985-2009 futures
sample should not be expected to survive:

- a different asset universe (ETFs, not futures),
- a different and largely post-publication sample period,
- realistic transaction costs,
- a multiple-testing correction.

Recording this expectation *now* matters: if the result comes in weak, that is the
pre-registered expectation being met, not a failure to be buried. If it comes in strong,
that is the surprise that requires extra scrutiny, not celebration.

---

## 2. Data

- **Universe:** ~25 liquid ETFs across four asset classes (equity indices, fixed income,
  commodities, currencies). Chosen for liquidity and asset-class diversification, not
  for backtested performance. Full list and selection rationale: `docs/01_DATA.md`.
- **Source:** Yahoo Finance via `yfinance`, split- and dividend-adjusted daily bars.
- **Sample:** from each ETF's inception through the data pull date.
- **Benchmark factors:** Ken French Data Library (Mkt-RF, SMB, HML, RMW, CMA, UMD, RF).

**Known limitations, acknowledged in advance:**

- ETFs are a *proxy* for the futures contracts in the source paper. They carry expense
  ratios and tracking error, and their inception dates truncate the sample severely
  relative to MOP's 1985 start. This is a real deviation from the original study, not a
  detail.
- Yahoo data is not survivorship-bias-free in general. For this universe the exposure is
  limited (a hand-picked set of large surviving ETFs is *itself* a survivorship-selected
  set — see `docs/01_DATA.md` for why this matters less for a time-series strategy than a
  cross-sectional one, and where it still bites).
- No point-in-time fundamentals are used anywhere in this project. The signal is
  price-only. This is a deliberate choice to eliminate an entire class of look-ahead bias
  rather than to manage it.

---

## 3. Signal specification (fixed in advance)

For instrument *i* at time *t*:

1. **Signal:** `sign(r_{i, t-252:t})` — the sign of the trailing 12-month (252 trading day)
   excess return, computed from data available up to and including the close of bar *t*.
2. **Volatility estimate:** EWMA of squared daily returns, computed on data up to and
   including the close of bar *t*.
3. **Position size:** `(target_vol / sigma_{i,t}) * signal_{i,t}`, with per-instrument
   annualized target volatility of 40% (following MOP).
4. **Portfolio construction:** equal-weight across instruments, then scale the whole
   portfolio to a target annualized volatility of 10%, using a trailing estimate of
   portfolio volatility.
5. **Execution:** the position implied by the signal at bar *t* is **entered at bar t+1**.
   No trade is ever executed at a price on the same bar from which its signal was computed.
6. **Rebalance frequency:** monthly (last trading day of month), following MOP.

---

## 4. Parameter grid (FIXED — this is the N that feeds every correction)

The following grid is fixed now and will not be expanded. If it is expanded, this document
will be amended with a visible, timestamped note, and the enlarged N will be used in all
corrections.

| Parameter | Values | Count |
|---|---|---|
| Lookback (trading days) | 63, 126, 252 | 3 |
| Per-instrument vol target | 20%, 40% | 2 |
| Rebalance frequency | monthly, weekly | 2 |
| **Total configurations** | | **12** |

**N = 12.**

### 4.1 Justification against Minimum Backtest Length

Bailey, Borwein, Lopez de Prado & Zhu (2014), "Pseudo-Mathematics and Financial
Charlatanism," *Notices of the AMS* 61(5): with only 5 years of data, trying more than
~45 *independent* configurations essentially guarantees an in-sample Sharpe of 1 with an
expected out-of-sample Sharpe of zero. Their MinBTL bound is
`MinBTL (years) < 2*ln(N) / E[max_N]^2`.

With N = 12 and a sample expected to exceed 15 years, this grid is comfortably within the
bound. **The grid was kept small specifically so that the honesty claims in Section 5 are
believable.** A 500-configuration grid would make any subsequent DSR correction close to
meaningless — which is precisely the pathology this project is built to demonstrate
awareness of.

### 4.2 The primary specification

The **12-month lookback / 40% vol target / monthly rebalance** configuration is designated
in advance as the primary specification, because it is the one used in MOP (2012). It is
not chosen because it performed best — at the time of writing, no configuration has been
run.

All other configurations are reported as robustness, and all 12 are disclosed regardless of
outcome.

---

## 5. Evaluation plan (fixed in advance)

### 5.1 What will be reported

- Gross and **net** equity curves, always side by side. Net is the only number claimed.
- Breakeven cost level: the round-trip cost at which the edge disappears.
- Sharpe (annualized, net), max drawdown, Calmar, Sortino, annualized turnover, average
  holding period.
- Probabilistic Sharpe Ratio (PSR) and Minimum Track Record Length.
- **Deflated Sharpe Ratio** using the pre-registered N = 12, and additionally using
  effective-N estimates (see Section 6, Thread B).
- Harvey-Liu haircuts (Bonferroni, Holm, BHY).
- Probability of Backtest Overfitting (PBO) via CSCV.
- Factor regression of net returns on Ken French factors, to establish whether any
  residual alpha exists after known factor exposure.
- Performance by sub-period and by volatility regime. **No single full-sample Sharpe will
  be presented as the headline without its sub-period decomposition.**

### 5.2 Transaction cost model

Costs are modelled following Carver (2015), *Systematic Trading*: cost per round trip is
expressed in **Sharpe-ratio units** (round-trip cost divided by the annualized volatility
of the instrument), then multiplied by annual turnover to give the Sharpe drag. Components:
commission, half bid-ask spread per side, and a slippage allowance.

Cost assumptions are declared in `docs/03_COSTS.md` with sources. Results will be reported
across a *range* of cost assumptions, not a single point estimate, because a single
optimistic cost number is one of the most common ways a backtest lies.

### 5.3 Validation design

Two methods, both applied:

- **Walk-forward:** expanding window, selection on data up to *t* only, evaluation on
  *(t, t+h]*, stepped forward. Produces a single sequential out-of-sample path.
- **Combinatorial Purged Cross-Validation (CPCV)** (Lopez de Prado 2018, AFML Ch. 12),
  with purging and embargoing (AFML Ch. 7). Produces a distribution of out-of-sample paths.

Purge and embargo parameters: label horizon-aware purging; embargo of 21 trading days
(~1 month). Rationale recorded in `docs/04_VALIDATION.md`.

**Standard k-fold CV will not be used**, and the reason is recorded in
`docs/04_VALIDATION.md`: overlapping labels and serial correlation mean a randomly selected
test point is nearly identical to its training neighbours, which leaks the answer into the
training set.

### 5.4 Success criteria — declared in advance

The project is **not** considered to have failed if the strategy shows no significant
net-of-cost alpha. It is considered to have failed if:

- any look-ahead is discovered in the engine after results are published,
- results are reported gross-only, or on a cherry-picked sub-period,
- the parameter grid is expanded after seeing results without disclosure,
- a configuration is promoted to "primary" after the fact.

**The finding is whatever the finding is.** A well-executed null result is the
pre-registered expected outcome (Section 1.2).

---

## 6. The two open questions this project will investigate

These are recorded here to make clear that they were anticipated as *research questions*,
not discovered as excuses after a disappointing result. Machinery for both is built as part
of the core project; the interpretation is deferred until the outputs exist.

### Thread A — When walk-forward and CPCV disagree, which estimate should be believed?

Both methods are defensible; they can disagree; the literature has no settled answer.

- Walk-forward respects the arrow of time and only ever trains on the past, so it is the
  more faithful simulation of live trading. But it yields a single path, so its Sharpe
  estimate is high-variance and poorly suited to inference.
- CPCV yields a sampling distribution and far greater statistical power, but achieves this
  partly by training on folds that could never have been available live (training on future
  data to predict the past), so its realism is contested.

**What will be measured:** the walk-forward point estimate versus the full CPCV path
distribution; where in the sample they diverge; whether divergence concentrates in specific
volatility or trend regimes; PBO.

**What is deferred:** the position on which estimate should govern a capital allocation
decision. That requires reasoning about what counterfactual each method actually estimates,
and is not settled by running the code.

### Thread B — What is N, actually?

The Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) corrects for the number of
*independent* trials. In practice that number is not observable. This grid's 12
configurations are highly correlated — a 63-day and a 126-day lookback on the same universe
are close to the same bet — so a naive N = 12 over-deflates. The literature's own remedy,
`N_hat = rho_bar + (1 - rho_bar) * M` where `rho_bar` is the average off-diagonal
correlation of trial returns, is itself an approximation that is rarely computed in
practice.

**What will be measured:** the trial-return correlation matrix; effective-N under (i) the
`rho_bar` formula, (ii) a PCA / eigenvalue-based effective-dimension estimate, (iii) a
correlation-clustering count; and the DSR verdict as a function of assumed N, including the
value of N at which the verdict flips.

**What is deferred:** which effective-N estimate is correct, and therefore which DSR verdict
governs.

---

## 7. Reproducibility commitments

- Pinned environment (`requirements.txt` with exact versions).
- All randomness seeded; seeds recorded in config.
- Raw data cached to `data/raw/` on first pull and never re-fetched, so results are
  reproducible even as Yahoo silently revises history.
- Data pull date recorded in the cache manifest.
- One-command reproduction from raw data to every figure and table in `results/`.

---

## 8. Amendment log

Any change to the hypothesis, universe, signal specification, parameter grid, or evaluation
plan after this document's initial commit must be recorded here with a date and a reason.
An empty log is a claim that nothing was changed after results were seen.

| Date | Change | Reason |
|---|---|---|
| — | *(none)* | Initial commit, before any results. |
| 2026-07-15 | **Disclosure (not a change): the pre-registered N=12 grid contains only 6 distinct strategies.** No parameter was added, removed, or re-tuned; N=12 stands as the pre-registered figure for every correction. What changed is our knowledge: the vt20/vt40 axis was found — *after* results — to be degenerate. See §8.1. | A design flaw in the grid, discovered post-hoc from the trial-return correlation matrix (Finding 5). Recorded here so that the empty log does not falsely claim nothing was learned about the grid after results were seen. |

### 8.1 The vt20/vt40 axis is degenerate under portfolio vol targeting

**What was pre-registered.** §4 fixes the grid at **N = 12** = 3 lookbacks × 2 per-instrument
vol targets (20%, 40%) × 2 rebalance frequencies. That N feeds every multiple-testing
correction (DSR, Harvey-Liu).

**The flaw.** The per-instrument vol target is exactly cancelled by the portfolio-level vol
scaling. Doubling the target from 20% to 40% doubles every per-instrument position (positions
scale as `vol_target / sigma`), which doubles the un-scaled portfolio's realised volatility,
which halves the scalar that `scale_to_portfolio_vol` applies to hit the fixed 10% portfolio
target. The two factors cancel **identically**, not approximately. The vt20 and vt40 members
of each (lookback, rebalance) pair are therefore the *same strategy*, and the grid contains
**6 distinct strategies, not 12**.

**The evidence, and where it came from.** This was **not** found by reading the code — it was
found in the **trial-return correlation matrix** (Run 5 / Finding 5). All six vt20/vt40 pairs
sit at correlation **1.000000**, with net Sharpes identical to six decimal places (e.g.
`lb252_vt20_rbM` and `lb252_vt40_rbM` both 0.706105). The eigenvalue effective-N estimators
corroborate it: participation ratio ≈ 1.8, and the clustering count is exactly **6** at any
distance threshold that merges near-perfect duplicates. The correlation matrix surfaced a
structural fact that code review had missed — which is the same lesson as ENTRY 17: a property
measured from the data catches what inspection does not.

**Why this is a disclosure, not a grid change.**
- **N = 12 is unchanged and still reported as the headline**, per §4: it is the number of
  configurations actually run and the honest upper bound on the search. Every DSR/Harvey-Liu
  correction continues to use N = 12. Nothing was added post-hoc, so no multiple-testing
  penalty is being quietly relaxed.
- **We now also report the true count of distinct strategies, 6**, alongside it. Reporting
  both is the honest position: 12 overstates the number of independent bets (it double-counts
  a redundant axis), and this is precisely the effective-N question Thread B exists to
  quantify (ENTRY 16) — here answered exactly, for once, rather than estimated.
- This is a flaw in grid *design*, discovered after results. It is logged as such rather than
  silently corrected, because silently collapsing the grid to N = 6 after seeing the results
  would itself be a post-hoc change to a pre-registered quantity — the thing this log exists
  to prevent.
