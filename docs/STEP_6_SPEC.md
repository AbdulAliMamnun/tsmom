# STEP 6 SPEC — Figures & README

**For Claude Code.** Produce `scripts/make_figures.py` → `results/figures/*.png`, and `README.md`.

Read `docs/RESULTS_LOG.md` first — every number below must come from it, not from memory. If a
number here disagrees with the results log, the results log wins and the disagreement is a bug
in this spec.

---

## 0. The thing to understand before writing a word

**A quant research README is not a software README.** It opens like a paper abstract:
hypothesis, method, honest result, limitations. Install instructions go near the bottom, if at
all.

The reader is a quant researcher who will spend **four minutes** deciding whether the author
can be trusted with a capital decision. They are not going to run the code. They are going to
read the first screen and skim the figures.

**What earns trust:** a result reported against itself. The headline Sharpe with the factor
regression that undercuts it, in the same section, without being asked.

**What loses trust instantly:** a Sharpe with no cost model; "promising results"; any
adjective where a number belongs; hiding the UMD loading below the fold.

---

## 1. Figures — `scripts/make_figures.py`

Six figures, saved to `results/figures/` at 150 dpi, readable at GitHub's rendered width.
Matplotlib only. No seaborn styling, no dark backgrounds, no chartjunk. Label axes. State units.

1. **`equity_curve.png`** — gross vs net, log scale, primary config. Shade the 2000-2007
   period (the not-yet-diversified era per Run 1) and annotate it as such. Max drawdown marked.

2. **`ablation.png`** — horizontal bars, net Sharpe by arm: `vol_scaled_tsmom` 0.789,
   `unscaled_tsmom` 0.616, `vol_scaled_random` **-0.045**, `long_only` 0.416. The random arm
   at zero is the visual. Annotate: "vol scaling with no signal earns nothing."

3. **`dsr_vs_n.png`** — DSR against assumed N, 1→12. Horizontal line at 0.95. Mark each
   effective-N estimate on the x-axis (participation 1.78, entropy 2.51, rho_bar 4.20,
   clustering 6.00, naive 12). Annotate: **no flip point in range** — and annotate the margin
   at N=12 (0.995 vs 0.95), because the narrowness is the point.

4. **`factor_loadings.png`** — coefficient plot with Newey-West CIs, FF5+UMD. **UMD at t=12.70
   dominates the figure.** Alpha marked separately with its p=0.0488. This figure is the
   project's headline.

5. **`umd_by_sleeve.png`** — UMD t-stat by sleeve: equity 10.77, fixed_income 5.12, commodity
   7.77, currency 7.31. Horizontal line at t=1.96. Annotate the currency bar: "no mechanical
   channel — UMD is a US equity factor."

6. **`alpha_lag_robustness.png`** — alpha t-stat vs Newey-West lag (5, 21, 63, 126), with the
   1.96 line. Show it dipping below at 63. Annotate that the point estimate is lag-invariant
   at 3.97% and only the SE moves.

---

## 2. `README.md`

### Structure — in this order

**Title + one-line abstract.** Not "TSMOM Backtest." Something like: *A pre-registered
time-series momentum replication on 25 liquid ETFs, and what happened when it was tested
honestly.*

**The result, in the first screen.** Before anything else. Roughly:

> Net Sharpe **0.706** (2000-2026, 25 ETFs, net of 5bp/side).
> It passes the Deflated Sharpe Ratio at every effective-N accounting tested.
> **It is also, substantially, cross-sectional momentum beta** — UMD loads at t=12.70,
> leaving 3.97%/yr of alpha whose significance depends on an arbitrary HAC lag choice
> (p=0.0488 at lag 21; p=0.0506 at lag 63).
>
> A strategy can pass every multiple-testing correction and still be repackaged factor
> exposure. Those analyses ask orthogonal questions. That is the finding.

Then `factor_loadings.png`.

**The chain.** The five steps from RESULTS_LOG Open Question 9, as a numbered list. Each step
is a correct application of a standard method; the destination is far from where step 2 alone
would have left you; **step 2 is where most backtests stop.**

**What was pre-registered, and the link.** `docs/00_PRE_REGISTRATION.md`, committed at
`c566120` before any result existed. Say the commit ordering is checkable. Link §8 — the
amendment log — and state plainly that the grid contained six duplicate pairs, discovered from
the correlation matrix after results.

**How it was validated.** Walk-forward 0.631 inside the CPCV range [0.546, 0.706]. PBO 0.400.
Note the churn-6.5%/PBO-0.400 tension: selection is stable but not predictive. Note WF prefers
a config that is not the pre-registered primary.

**Leak detection — with the bug that proves it works.** This section is short and specific.
Truncation invariance, future poisoning, positive controls. Then: *the suite caught a
full-sample quantile in my own vol floor, written as a defensive guard, in a file whose
docstring warns against exactly that. It was not caught by reading the code.* Link ENTRY 17.

**Limitations.** Not a disclaimer paragraph — a real list. ETF proxies not futures; effective
diversified sample starts ~2007 not 2000; hand-picked surviving ETFs are survivorship-selected;
era decline 0.850→0.642→0.638; embargo robustness claim is narrow to this fold geometry.

**Open questions.** Three, stated as questions, not resolved. Chief among them: *why does a
long-short portfolio of US equities sorted on prior returns explain a trend strategy trading
Swiss francs at t=7.31?* Say it is unresolved. **Do not answer it.**

**Repo structure + reproduction.** At the bottom. Brief.

### Rules

- **Every claim links to `docs/RESULTS_LOG.md` or `docs/REASONING_LOG.md`.** The README is a
  summary; the logs are the evidence.
- **No adjectives where numbers belong.** Not "strong Sharpe" — "0.706."
- **Never report a Sharpe without its cost basis.**
- **Do not oversell the UMD finding.** R²=0.186. It is not "the strategy is just UMD." A large
  beta with modest R² means strong co-movement, not reducibility. Say that.
- **Do not undersell it either.** t=12.70 across all four sleeves including currencies is the
  most interesting thing here.
- **Do not write the author's position on the open questions.** State them and stop.
- Keep it under ~400 lines. A quant reader skims.

---

## 3. Definition of done

- [ ] `run_checks.py` 33/33, pytest 50/50
- [ ] `scripts/make_figures.py` produces all six PNGs, reproducibly, from cached data
- [ ] Every figure readable at GitHub width, axes labelled, units stated
- [ ] README opens with the result and the thing that undercuts it, in the first screen
- [ ] Every number traceable to `docs/RESULTS_LOG.md`
- [ ] Limitations are specific, not boilerplate
- [ ] Open questions stated, unanswered
