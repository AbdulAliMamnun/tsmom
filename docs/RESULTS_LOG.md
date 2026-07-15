# Results Log

**What this is.** A chronological record of every result produced on real data, and every
bug found while producing it. Append-only: nothing here is edited after the fact, because
the point is the ordering.

**Why it exists separately from the reasoning log.** The reasoning log records *why the
design is what it is*. This records *what happened when it ran*. Keeping them apart means
the reasoning log stays readable as a study guide, while this stays honest as a lab
notebook.

**Rule: results go in here BEFORE they go in the README.** If a number appears in the README
that never appeared here first, the write-up has drifted from the record.

---

## Run 1 — First real-data pull

**Universe:** 25 ETFs (7 equity, 6 fixed income, 6 commodity, 6 currency)
**Sample:** 2000-01-03 → 2026-07-14, 6671 bars (~26.5 years)
**Source:** yfinance, `auto_adjust=True`, cached to `data/raw/prices.parquet`

### Incident: EWJ failed the first pull

```
1 Failed download:
['EWJ']: OperationalError('database is locked')
```

A yfinance cache collision, not a data problem. A clean re-pull (`rm data/raw/prices.parquet`)
returned the full 6671 bars.

**Why this is recorded rather than quietly fixed:** a silently-missing instrument in a
diversified strategy changes the result without announcing itself. The first pull would have
produced a 24-ETF backtest that ran perfectly and reported a number. Nothing would have
failed. The only reason it was caught is that `pull_data.py` prints per-ticker observation
counts — a diagnostic that exists precisely because "it ran without error" is not evidence
that it ran correctly.

### Observation counts (post-fix)

| ticker | obs | | ticker | obs |
|---|---|---|---|---|
| UNG | 4840 | | FXE | 5177 |
| HYG | 4845 | | GLD | 5445 |
| UUP | 4873 | | FXI | 5474 |
| FXY | 4884 | | TIP | 5685 |
| DBA | 4910 | | EEM | 5849 |
| FXA | 5043 | | SHY, IEF, TLT, LQD | 6027 |
| FXB | 5043 | | EFA | 6255 |
| FXF | 5043 | | IWM | 6570 |
| SLV | 5083 | | EWJ, QQQ, SPY | 6671 |
| USO | 5096 | | | |
| DBC | 5140 | | | |

**The staggered inception dates are a real limitation, not a footnote.** The sample nominally
starts 2000-01-03, but only SPY/QQQ/EWJ have full history. UNG (4840 bars) starts ~2007. So
the *effective* sample for a genuinely diversified portfolio starts around 2007, not 2000 —
roughly 19 years, not 26. Any claim about the strategy's behaviour "since 2000" is really a
claim about a portfolio that was mostly equities and Treasuries for its first seven years.

This must appear in the README's limitations section. It is exactly the ETF-sample-truncation
cost that ENTRY 3 flagged in advance.

---

## Run 2 — Primary configuration, real data

**Config:** `lb252_vt40_rbM` (252-day lookback, 40% per-instrument vol target, monthly
rebalance) — the pre-registered primary spec, designated in advance as MOP's (ENTRY 4, §4.2).

### Headline (net of base costs: 5bp/side)

| metric | value |
|---|---|
| n_obs | 6671 |
| years | 26.47 |
| annualised return | 7.55% |
| annualised vol | 11.20% |
| **net Sharpe** | **0.706** |
| Sortino | 0.659 |
| max drawdown | -23.47% |
| Calmar | 0.322 |
| skew | -0.387 |
| kurtosis | 7.796 |
| PSR vs zero | 0.9998 |
| **breakeven cost** | **92.3 bp/side** |
| annual turnover | 4.53 |

### Cost sensitivity

| scenario | per-side bp | gross SR | net SR | Sharpe drag |
|---|---|---|---|---|
| zero (diagnostic only) | 0.0 | 0.746 | 0.746 | 0.000 |
| optimistic | 2.0 | 0.746 | 0.730 | 0.016 |
| base | 5.0 | 0.746 | 0.706 | 0.040 |
| pessimistic | 10.0 | 0.746 | 0.666 | 0.081 |
| stressed | 20.0 | 0.746 | 0.584 | 0.162 |

### Reading this honestly

**The Sharpe is the pre-registered expected outcome.** §1.2 of the pre-registration said, in
advance, to expect something "modest and possibly not significant." 0.71 net over 26 years is
modest and plausible — consistent with published TSMOM after costs. It is not a discovery and
should not be written up as one.

**PSR vs zero = 0.9998 is not the number it looks like.** It says: given the sample length,
skew and kurtosis, the probability the true Sharpe exceeds ZERO is 99.98%. Zero is not the
relevant benchmark. The relevant benchmark is the expected maximum Sharpe from N skill-less
trials (ENTRY 14), and the DSR has not been run yet. The kurtosis of 7.8 is the tell that
this correction will bite.

**Costs are not a binding constraint here, and that is worth stating plainly.** Breakeven at
92.3 bp/side against a realistic 2-5 bp for liquid ETFs is a wide margin. Turnover of 4.5
round trips/year is low — that is what makes the drag small (0.04 Sharpe at base). Note this
is a *finding*, not a given: it is a consequence of monthly rebalancing on a slow signal, and
the weekly-rebalance configs in the grid will not look like this.

**Sortino (0.659) < Sharpe (0.706), and skew is negative (-0.387).** Worth flagging because
trend-following is *conventionally* described as positively skewed — many small losses,
occasional large gains. This sample says otherwise for this implementation. That is either a
real property of the ETF universe/period, or an artifact of the vol scaling, and it is not
yet known which.

---

## Run 3 — Ablation (BROKEN — recorded as found)

Raw output:

| arm | gross | net | ann_vol | max_dd | turnover |
|---|---|---|---|---|---|
| vol_scaled_tsmom | 0.686 | 0.533 | **3.596** | **-1.000** | 549.3 |
| unscaled_tsmom | 0.324 | 0.263 | 1.837 | -1.099 | 112.8 |
| vol_scaled_random | -0.046 | **-6.699** | 1.924 | -1.000 | **12,806.8** |
| long_only | 0.460 | 0.460 | 2.152 | -1.002 | 0.47 |

**This table is meaningless and is recorded anyway.** Two bugs, both in `ablation()`, both
mine. Full diagnosis in REASONING_LOG.md ENTRY 18.

**Bug 1:** arms skip `scale_to_portfolio_vol` and `apply_rebalance_schedule`, so they run 25
instruments at 40% vol each, unbounded, rebalanced daily → 360% annualised vol, -100%
drawdown. The equity curve hit zero; every Sharpe in the table describes a bankrupt portfolio.

**Bug 2:** `vol_scaled_random` re-draws signs every bar → 12,807 annual turnover vs the real
arm's 549. It is not a control; it is a different strategy with 23x the trading. Its -6.70
net Sharpe is a cost artifact.

**Status: FIXING.** Both arms must run the identical pipeline as the real strategy, varying
only (a) the signal and (b) per-instrument vol scaling. Random signs resample on rebalance
dates and forward-fill. Plus an assertion that each arm's realised vol is within 3x the
portfolio target, so a blown-up arm fails loudly.

**The uncomfortable part, recorded deliberately:** the headline (Run 2) looks fine, and the
diagnostic that would tell us whether the headline *means* anything is the thing that was
broken. `unscaled_tsmom` at 0.32 vs `vol_scaled_tsmom` at 0.69 hints that vol scaling does
over half the work — which is exactly the ENTRY 6 confound — but the hint is worthless
because both numbers are computed on blown-up portfolios. **The central question of the
project is currently unanswered, and it looked answered.**

---

## Run 4 — Ablation (corrected)

Fix applied per ENTRY 18. All arms now run the identical pipeline as the real strategy
(`target_positions` → `scale_to_portfolio_vol` → `apply_rebalance_schedule`), varying only
(a) the signal and (b) the per-instrument vol toggle. Random signs resample on rebalance
dates and forward-fill. Assertion added: each arm's realised vol must be ≤ 3× the portfolio
target (0.30); verified to fire on a simulated 358%-vol arm.

**A third instance of the ENTRY 17 Finding 1 leak was found during this fix.** The inlined
full-sample `vol.quantile(0.01, axis=0)` floor existed *inside `ablation()`* as well —
separate from the occurrence already fixed in `signals.py`. Same bug, second location, in a
function that had never been leak-tested because the leak tests cover the signal pipeline,
not the analysis helpers. Now routed through `signals.floor_volatility()`.

**The lesson, and it is not a comfortable one:** fixing a bug at the site where it was
detected does not fix the *pattern*. The full-sample-statistic-as-safety-guard reflex
produced the same error twice in the same codebase, and the second instance survived because
it sat outside the tested surface. A test suite defines a boundary, and bugs live happily
on the other side of it.

### Results (net of base costs: 5bp/side)

| arm | gross SR | **net SR** | ann_vol | max_dd | turnover |
|---|---|---|---|---|---|
| vol_scaled_tsmom | 0.830 | **0.789** | 0.112 | -0.235 | 4.54 |
| unscaled_tsmom | 0.636 | **0.616** | 0.109 | -0.212 | 2.11 |
| vol_scaled_random | 0.270 | **-0.045** | 0.111 | -0.592 | 34.98 |
| long_only | 0.419 | **0.416** | 0.110 | -0.326 | 0.32 |

All arms land at ~11% annualised vol, matching the portfolio target. Drawdowns are in a
plausible -0.21 to -0.59 range. These are comparable portfolios, so the comparison is
meaningful — which was not true of Run 3.

### The finding: the signal carries the performance

**`vol_scaled_random` earns -0.045 net.** This is the number that matters. It is the ENTRY 6
confound tested directly: volatility scaling applied to *no signal at all*, through the exact
same pipeline. If the "TSMOM is really just vol targeting" story were true of this
implementation, that arm would post a respectable Sharpe on risk management alone.

It earns zero.

Decomposition:
- **Signal + scaling:** 0.789
- **Signal alone (unscaled):** 0.616 → scaling contributes ~0.17
- **Scaling alone (random signs):** -0.045 → scaling contributes ~nothing without a signal
- **Neither (long-only):** 0.416

So vol scaling adds ~0.17 of Sharpe *conditional on having a signal*, and nothing on its own.
The signal is doing the work. This is a clean answer to what is one of the sharpest available
questions about any TSMOM backtest.

### Secondary observations

**The strategy beats long-only (0.789 vs 0.416).** It is not repackaged beta. The factor
regression is what actually establishes this — long-only here is an equal-weight basket
across four asset classes, not a market factor — but the sign is right.

**Random's turnover is 35 vs the real arm's 4.54 — still ~8x, and this is inherent, not a
bug.** Signs now resample monthly for both arms, but a random sign flips at ~50% of
rebalances while a trend signal flips rarely (trends persist; that is the hypothesis). The
control cannot match turnover without ceasing to be random. Note its gross (0.270) vs net
(-0.045): the cost drag is real and is doing legitimate work in that arm.

**Interviewer follow-up this now answers:**
- *"How much of your Sharpe is the vol targeting?"* → "Almost none. Random signs through the
  identical pipeline earn -0.05 net. Scaling adds about 0.17 over the unscaled signal; the
  signal carries the rest."
- *"Your random control trades 8x more than your strategy. Isn't that comparison unfair?"*
  → Worth having a real answer ready. The cost drag on the random arm (0.27 gross → -0.05
  net) is partly a turnover artifact. The gross comparison (0.83 vs 0.27) is the cleaner
  read on signal contribution.

---

## Pending

- [x] Ablation fix + vol assertion (Run 4) — DONE, signal carries the performance
- [ ] Full 12-config grid, all disclosed regardless of outcome
- [ ] Walk-forward (Thread A machinery)
- [ ] CPCV with purging + embargo, PBO (Thread A machinery)
- [ ] Embargo sensitivity: 0 / 5 / 21 / 63 days
- [ ] DSR at pre-registered N=12
- [ ] Effective-N estimators + DSR-vs-N curve + flip point (Thread B machinery)
- [ ] Harvey-Liu haircuts (Bonferroni, Holm, BHY)
- [ ] Factor regression vs Ken French (is this alpha, or repackaged known exposure?)
- [ ] Sub-period and volatility-regime decomposition
- [ ] Figures → `results/figures/`
- [ ] README
- [ ] **Thread A and Thread B positions — deferred to the author, after the outputs exist**
