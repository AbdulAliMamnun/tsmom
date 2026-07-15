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

## Run 5 — Full 12-config grid, all disclosed (pre-registration §5.1)

All twelve configurations, net of base costs (5 bp/side), disclosed regardless of outcome.

| config | net Sharpe | ann vol |
|---|---|---|
| lb252_vt20_rbM | 0.706105 | 0.1120 |
| **lb252_vt40_rbM** (primary) | **0.706105** | 0.1120 |
| lb126_vt20_rbM | 0.633875 | 0.1145 |
| lb126_vt40_rbM | 0.633875 | 0.1145 |
| lb252_vt20_rbW | 0.613098 | 0.1115 |
| lb252_vt40_rbW | 0.613098 | 0.1115 |
| lb63_vt20_rbM | 0.609685 | 0.1117 |
| lb63_vt40_rbM | 0.609685 | 0.1117 |
| lb126_vt20_rbW | 0.491461 | 0.1117 |
| lb126_vt40_rbW | 0.491461 | 0.1117 |
| lb63_vt20_rbW | 0.361345 | 0.1105 |
| lb63_vt40_rbW | 0.361345 | 0.1105 |

### Finding 5 — the grid contains six distinct strategies, not twelve

The trial-return correlation matrix (mean off-diagonal **0.709**) shows all six vt20/vt40
pairs at correlation **1.000000**, with net Sharpes **identical to six decimal places** (e.g.
`lb252_vt20_rbM` and `lb252_vt40_rbM` both 0.706105). The per-instrument vol target cancels
exactly under `scale_to_portfolio_vol`: doubling the target doubles every position, doubles
the un-scaled portfolio vol, and halves the scalar that re-targets 10%. So the pre-registered
N=12 grid is **6 distinct strategies**.

**This was found in the correlation matrix, not by reading the code.** Recorded as a design
flaw discovered after results in `docs/00_PRE_REGISTRATION.md` §8.1. N=12 remains the
pre-registered figure for every correction; 6 is reported alongside it.

---

## Run 6 — Walk-forward + CPCV + PBO + embargo (Thread A machinery)

### Walk-forward (expanding window)

| metric | value |
|---|---|
| OOS Sharpe (point) | **0.631** |
| OOS bars | 5915 |
| re-selection steps | 94 |
| selection churn | **6.5%** |
| most-selected config | `lb126_vt20_rbM` (64%), `lb252_vt20_rbM` (34%), `lb252_vt20_rbW` (2%) |

Walk-forward prefers `lb126_vt20_rbM` — **not** the pre-registered primary `lb252_vt40_rbM`.

### CPCV (6 groups, choose 2 → C(6,2)=15 splits → 5 paths)

| metric | value |
|---|---|
| path Sharpe mean | 0.606 |
| path Sharpe std | 0.059 |
| path Sharpe range | **[0.546, 0.706]** |
| per-path | 0.593, 0.593, 0.593, 0.706, 0.546 |
| **PBO** | **0.400** |

Walk-forward point (0.631) falls **inside** the CPCV range, at the 80th percentile.

### Embargo sensitivity (0 / 5 / 21 / 63 days)

Flat: mean path Sharpe 0.606, std 0.059, PBO 0.400 at every embargo. Usable training obs are
identical for embargo ≤ 21 (65,870) and drop only at 63 (65,030) — because the 21-day label
purge already subsumes any embargo ≤ the horizon. Embargo robustness here is therefore narrow
to this fold geometry, not a general claim.

### Finding 6 — selection is stable but not predictive

PBO **0.400** with churn of only **6.5%** is a tension worth stating: the selected config
barely changes step to step (stable), yet in 40% of CPCV splits the in-sample-best config
lands below the out-of-sample median (not predictive). Consistent with Finding 5 — ranking
across near-duplicate configs is close to uninformative.

---

## Run 7 — DSR + effective-N + Harvey-Liu (Thread B machinery)

### Effective-N estimates (stationary-bootstrap 95% CIs)

| method | point | 95% CI |
|---|---|---|
| naive | 12.00 | [12.00, 12.00] |
| rho_bar | 4.20 | [3.74, 4.70] |
| participation | **1.78** | [1.62, 1.95] |
| variance_95 | 4.00 | [4.00, 4.00] |
| entropy | **2.51** | [2.27, 2.74] |
| clustering | **6.00** | [6.00, 6.00] |

Clustering is reported at distance threshold 0.30 (merge ρ>0.955, near-perfect duplicates),
returning 6 = the distinct-strategy count of Finding 5. The curve is the honest form; the
earlier default of 1.0 sat past total collapse and returned 1 with CI [1,1] — the threshold,
not the data (fixed; see `docs/00_PRE_REGISTRATION.md` §8.1 lineage).

### DSR vs assumed N (var of trial Sharpes = 0.0138)

DSR **passes at 95% at every N in [1, 12]** — no flip point in range. At the naive N=12 the
margin is narrow: **DSR = 0.995 vs the 0.95 threshold** (SR0 = 0.195). At each effective-N
estimate: participation 1.000, entropy 0.999, rho_bar/variance_95/clustering 0.998, naive
0.995. The verdict does not depend on which effective-N one believes — unusually, the sample
resolves it, in the passing direction.

### Harvey-Liu haircuts (independence assumed; active-window Sharpe 0.723)

| method | adjusted p | haircut Sharpe | haircut | passes 5% |
|---|---|---|---|---|
| unadjusted | 0.0003 | 0.723 | — | yes |
| Bonferroni | 0.0034 | 0.583 | −19.3% | yes |
| Holm | 0.0034 | 0.583 | −19.3% | yes |
| BHY | 0.0052 | 0.556 | −23.1% | yes |

All three pass at 5%. (Sharpe here is computed on the post-warm-up active window, 0.723, vs
the full-sample headline 0.706.)

---

## Run 8 — Factor regression + per-sleeve + lag robustness + sub-period

### Full-portfolio factor regression (FF5 + UMD, Newey-West lag 21, N = 6641)

| term | coef | t-stat | p |
|---|---|---|---|
| alpha | 0.0002/day → **3.97%/yr** | **1.97** | **0.0488** |
| Mkt-RF | 0.0518 | 1.82 | 0.0689 |
| SMB | 0.1423 | 6.00 | 0.0000 |
| HML | 0.0181 | 0.66 | 0.5067 |
| RMW | 0.0124 | 0.37 | 0.7083 |
| CMA | 0.1227 | 2.94 | 0.0033 |
| **UMD** | **0.2799** | **12.70** | 0.0000 |

R² = **0.186**. A large UMD beta with modest R² is **strong co-movement, not reducibility** —
this is not "the strategy is just UMD."

### Per-sleeve (each sleeve separately vol-targeted to 10%)

| sleeve | alpha (ann) | alpha t | UMD coef | **UMD t** | R² |
|---|---|---|---|---|---|
| equity | 0.0067 | 0.33 | 0.274 | **10.77** | 0.218 |
| fixed_income | 0.0454 | 2.17 | 0.069 | **5.12** | 0.018 |
| commodity | 0.0226 | 1.02 | 0.134 | **7.77** | 0.032 |
| currency | −0.0099 | −0.45 | 0.099 | **7.31** | 0.021 |

**UMD loads significantly across all four sleeves, currencies included (t=7.31).** The
mechanical story (loading concentrated in the 7 equity ETFs, since UMD is a US equity factor)
is **refuted**: there is no mechanical channel by which a US-equity-momentum factor should
price a trend strategy trading Swiss francs.

### Alpha robustness to Newey-West lag (point estimate lag-invariant at 3.97%/yr)

| lag | alpha t | p | passes 5% |
|---|---|---|---|
| 5 | 2.02 | 0.0438 | yes |
| 21 | 1.97 | **0.0488** | yes |
| 63 | 1.95 | **0.0506** | **no** |
| 126 | 2.03 | 0.0423 | yes |

The alpha coefficient does not change with the HAC lag — only its standard error does. It
**crosses the 5% line at lag 63** (p=0.0506) and recovers at 126. Reported in full; not tuned.

### Finding 7 — sub-period and volatility-regime decomposition (causal)

| dimension | bucket | Sharpe | ann ret | ann vol | max dd |
|---|---|---|---|---|---|
| calendar | 2000–2007 | 0.850 | 0.098 | 0.118 | −0.193 |
| calendar | 2008–2015 | 0.642 | 0.067 | 0.110 | −0.165 |
| calendar | 2016–2026 | 0.638 | 0.066 | 0.109 | −0.235 |
| vol regime | low_vol | 0.561 | 0.044 | 0.083 | −0.145 |
| vol regime | mid_vol | 0.989 | 0.106 | 0.108 | −0.196 |
| vol regime | high_vol | 0.597 | 0.078 | 0.143 | −0.197 |

Performance **declines across eras** (0.850 → 0.642 → 0.638) and is best in the middle vol
tertile. The vol-regime split is assigned **causally** (trailing rolling vol + expanding
tertile thresholds); truncation test = 0 mismatches over 4000 bars, so it is not the ENTRY 17
Finding 1 full-sample-statistic leak recurring in a new place.

---

## Status

- [x] Ablation fix + vol assertion (Run 4)
- [x] Full 12-config grid, all disclosed (Run 5)
- [x] Walk-forward, CPCV + purge/embargo, PBO, embargo sensitivity (Run 6)
- [x] DSR at N=12, effective-N + DSR-vs-N curve + flip point, Harvey-Liu haircuts (Run 7)
- [x] Factor regression vs Ken French, per-sleeve, lag robustness, sub-period/vol-regime (Run 8)
- [x] Figures → `results/figures/` and README (Step 6)
- [ ] **Thread A and Thread B positions — deferred to the author, after the outputs exist**

---

## Open questions (stated, not resolved)

1. **Thread A** — when walk-forward (0.631, one path) and CPCV (a distribution) disagree,
   which estimand governs a capital decision? Deferred (REASONING_LOG ENTRY 15).
2. **Thread B** — what is N, actually? The effective-N range is 1.78–12; there is no ground
   truth. Deferred (ENTRY 16).
3. **Negative skew (−0.387)** — real property of this ETF universe/period, or an artifact of
   the vol scaling? Not yet known (Run 2).
4. Why does walk-forward prefer `lb126_vt20_rbM` over the pre-registered primary (Run 6)?
5. Does the PBO-0.400 / churn-6.5% tension mean in-sample ranking across the six duplicate
   pairs is uninformative (Finding 5 / Finding 6)?
6. Does the alpha survive a longer HAC lag? It crosses at 63 (p=0.0506) and recovers at 126
   (Run 8) — genuinely on the boundary.
7. Is the era decline (0.850 → 0.638) signal decay, a regime effect, or the diversification
   ramp as the sample fills out post-2007 (Run 1 / Finding 7)?
8. Is the UMD relationship co-movement or reducibility? R²=0.186 says co-movement (Run 8).
9. **The chain (the central open question).** *Why does a long-short portfolio of US equities
   sorted on prior returns explain a trend strategy trading Swiss francs at t=7.31?* The five
   steps, each a correct application of a standard method: **(1)** net Sharpe 0.706 →
   **(2)** DSR passes at every effective-N → **(3)** UMD loads at t=12.70 → **(4)** across all
   four sleeves, so the mechanical (equity-only) explanation is refuted → **(5)** the residual
   alpha, 3.97%/yr, is significant or not depending on an arbitrary HAC lag (p=0.0488 at 21,
   0.0506 at 63). **Unresolved. Deliberately not answered here.**
