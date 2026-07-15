# STEP 7 SPEC — The UMD investigation

**For Claude Code.** Implement `src/tsmom/umd_investigation.py`, `tests/test_umd_investigation.py`,
and `scripts/run_umd_investigation.py`.

Read `docs/RESULTS_LOG.md` Findings 8, 9, 10 first.

**The question this is built to answer:** why does UMD — a long-short portfolio of US equities
sorted on prior 12-month returns — explain a time-series trend strategy trading currencies at
t = 7.31? The mechanical explanation (equity sleeve dominance) was refuted in Finding 9: UMD
loads on all four sleeves.

**Non-negotiable:** `run_checks.py` 33/33, pytest passing.

**This spec produces machinery and numbers. It does NOT produce a conclusion.** See §11.

---

## 1. FREQUENCY — do this first, it may dissolve the puzzle

**The t = 7.31 result is on ~6,641 DAILY observations. The strategy rebalances MONTHLY on a
12-month signal.**

A daily regression on a monthly-rebalanced strategy has thousands of overlapping, serially
correlated observations. It can produce a large t-statistic for an economically trivial
relationship. **Monthly is the correct primary frequency** — it matches the rebalance and the
signal horizon.

Rerun the full-portfolio and per-sleeve UMD regressions at **monthly frequency**, and for every
regression in this entire spec report **all six**:

| beta | t-stat | p-value | correlation | R² | n_obs |

**R² is the number that matters here, not t.** If UMD explains 1-2% of the currency sleeve's
variance, the relationship is statistically real and economically negligible — and much of
Finding 9's strangeness evaporates. If it explains 15-30%, it does not.

Report daily and monthly side by side. The comparison is itself a finding.

---

## 2. DATA VERIFICATION — the backfill problem

**The currency ETFs do not have 26 years of live history.** From Run 1: FXA/FXB/FXF have 5,043
bars, FXE 5,177, UUP 4,873 — all starting ~2006-2007, not 2000. The sample nominally starts
2000-01-03.

Verify and report:
1. Actual first-valid-observation date per ticker per sleeve.
2. Whether any pre-inception data exists in the series (it should not — `tradeable_mask`
   requires `MIN_HISTORY_DAYS`, but verify rather than assume).
3. Date alignment between sleeve returns and the UMD series (French ends 2026-05-29; prices
   end 2026-07-14).

Then run every subsequent test on **three windows**: full sample; live-ETF period only (from
the date all sleeves have real data, ~2007); and the pre-2007 period.

**If the currency sleeve has no real data before 2007, then any full-sample currency result is
partly about a sleeve that did not exist.** This interacts with Finding 7 (the best era,
2000-2007, is the era Run 1 flagged as not-diversified).

**Also flag: UUP economically overlaps the other currency ETFs.** Long UUP and short FXE/FXY/FXB
are versions of the same dollar trade. The "6 currency instruments" may be closer to 2-3 bets.
Report the within-sleeve correlation matrix for currencies specifically.

---

## 3. Per-sleeve UMD regressions — with R², at monthly frequency

Reproduce Finding 9's table at monthly frequency, with all six statistics. Newey-West lag 3
(monthly ≈ quarterly memory); also report OLS SEs for comparison.

Table: sleeve × (beta, t, p, corr, R², n_obs), daily and monthly.

---

## 4. Sleeve correlation matrix

All six pairs (equity/currency, equity/bond, equity/commodity, currency/bond,
currency/commodity, bond/commodity). Monthly. Report the **magnitude**, not just significance.

Each sleeve is separately vol-targeted to 10%, so these are comparable.

---

## 5. Pairwise sleeve regressions

Each sleeve on each other sleeve. Report all six statistics per pair.

**What to look for:** is co-movement broad or concentrated? If only currency and bonds relate,
that points at rates/dollar rather than a universal momentum factor. If every sleeve relates to
every other, a broad common component is more plausible.

---

## 6. Leave-one-out common trend factor — the key test

**This is the most informative test in the spec.**

For each sleeve, construct `other_three_avg` = the equal-weight average return of the other
three sleeves. Then regress:

```
sleeve_return ~ UMD + other_three_avg
```

Report both coefficients with all six statistics.

This asks: **does UMD still matter after controlling for the common performance of the rest of
the strategy?** Four possible patterns, all worth reporting explicitly:

- UMD insignificant once `other_three_avg` is included → UMD was detecting a broad common trend
  component.
- UMD survives → UMD carries information beyond the other trend sleeves.
- `other_three_avg` significant, UMD not → UMD is a proxy, not the driver.
- Both significant → the sleeve has both a cross-asset trend exposure and a separate
  relationship with equity momentum.

---

## 7. Macro controls

Regress each sleeve on UMD while controlling for what is obtainable from existing data:

- Mkt-RF (have it — Ken French)
- A dollar proxy: **UUP returns** (in-universe; note the endogeneity — UUP is *in* the currency
  sleeve, so for the currency-sleeve regression this control is contaminated. Report it,
  flag it, do not pretend otherwise.)
- A duration proxy: **TLT returns** (same endogeneity caveat for the fixed-income sleeve)
- Realised market volatility: trailing 21d std of Mkt-RF, **lagged one period** (causal)
- Credit spread proxy: **HYG − LQD** return spread

**Do not fetch external data.** Use what is in the repo. If a control is unobtainable, say so
rather than substituting something that doesn't measure the same thing.

Report: does UMD survive each control, and all controls jointly?

**Note honestly in the docstring:** this cannot prove causality. An omitted macro variable can
always be the true driver. The test is informative, not decisive.

---

## 8. Tail and outlier concentration

- Correlations excluding the largest 5% positive UMD months.
- Correlations excluding the largest 5% negative UMD months.
- Correlations in the worst 10% of *portfolio* months vs. all months.
- Correlations in high-vol vs. low-vol regimes (use the existing causal tertiles from
  `subperiod_analysis` — Run 8 verified they are causal; reuse rather than reimplement).

**The question:** are the sleeves uncorrelated normally but correlated during losses? That is
tail diversification risk, and a full-sample correlation matrix hides it.

---

## 9. Stability over time

- Rolling 3-year and 5-year UMD betas per sleeve. Plot.
- First half vs. second half.
- Pre-2008 / 2008-2015 / 2016-2026.
- Backfilled vs. live-ETF period (§2).

**If the entire result comes from one short period, it cannot be presented as a stable
phenomenon.**

---

## 10. Economic importance

- % of each sleeve's variance explained by UMD (this is just R², but state it as the economic
  question it is).
- Portfolio vol and max drawdown with UMD exposure hedged out (regress portfolio returns on
  UMD, take residuals, compare).
- Do the sleeves lose money at the same time? Report the correlation of sleeve drawdowns.

---

## 11. What NOT to do

- **Do not write a conclusion.** Not in the docstrings, not in the script output, not in a
  summary. Produce the tables. The author forms the position.
- **Do not write an "interpretation" section that lists which outcome obtained.** Reporting
  "UMD became insignificant after controls" as a *fact* is fine. Writing "therefore this is a
  regime effect" is not.
- **Do not tune anything to a result.** If a test is inconclusive, it is inconclusive.
- **Do not use full-sample statistics anywhere** — vol regimes, tertiles, normalisation. This
  leak pattern has now recurred three times in this project (`signals.py`, `ablation()`, and a
  suspected-but-clean case in `subperiod_analysis`). Assume it will recur again here.
- **Do not report a t-statistic without its R².** That failure is what produced Finding 9's
  apparent strangeness in the first place.

---

## 12. Definition of done

- [ ] `run_checks.py` 33/33, pytest passing
- [ ] `scripts/run_umd_investigation.py` prints every table above
- [ ] Every regression reports beta, t, p, corr, R², n_obs
- [ ] Daily vs monthly reported side by side
- [ ] All tests run on full / live-ETF / pre-2007 windows
- [ ] Rolling-beta plot → `results/figures/umd_beta_stability.png`
- [ ] No conclusions anywhere in the output

**The one number to look at first:** the currency sleeve's **monthly R² against UMD**. If it is
1-2%, most of this spec is confirming that the original t = 7.31 was a daily-frequency artifact
and the relationship is economically trivial. If it is 15%+, the puzzle is real and the rest of
the spec matters.
