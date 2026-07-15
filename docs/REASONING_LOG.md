# Reasoning Log

**What this document is.** Every non-obvious methodological choice in this project, recorded
with the reason behind it, as it was made. Not documentation of *what* the code does — the
code says that. This is *why* it does it that way, what the alternatives were, and what
would have to be true for the choice to be wrong.

**How to use it if you are the author.** This is the study guide. For each entry, the test
is not "can I read this and nod." The test is: **close this file and re-derive the reasoning
out loud.** Where you can't, that's the gap. Each entry ends with the follow-up questions an
experienced interviewer would actually ask — those are the real exam, and they are not
answerable by memorising the entry above them.

**How to use it if you are evaluating this repo.** This log is the audit trail. Every claim
in the README should trace back to an entry here.

---

## Table of contents

- [ENTRY 1 — Why pre-registration, and why it is a methodological step rather than paperwork](#entry-1)
- [ENTRY 2 — Why time-series momentum rather than cross-sectional or pairs](#entry-2)
- [ENTRY 3 — Why ETFs, and what that costs us](#entry-3)
- [ENTRY 4 — Why the parameter grid is deliberately small](#entry-4)
- [ENTRY 5 — Why the signal is price-only (killing an entire bias class rather than managing it)](#entry-5)
- [ENTRY 6 — Why volatility scaling, and the confound it introduces](#entry-6)
- [ENTRY 7 — Why the t -> t+1 execution lag, and why it is unit-tested rather than asserted](#entry-7)
- [ENTRY 8 — Why costs are modelled in Sharpe units](#entry-8)
- [ENTRY 9 — Why standard k-fold cross-validation is invalid here](#entry-9)
- [ENTRY 10 — Purging: what it is and why the horizon defines it](#entry-10)
- [ENTRY 11 — Embargoing: why purging alone is insufficient](#entry-11)
- [ENTRY 12 — Walk-forward: what it estimates and what it cannot](#entry-12)
- [ENTRY 13 — CPCV: what it buys and what it costs](#entry-13)
- [ENTRY 14 — The Deflated Sharpe Ratio: the machinery](#entry-14)
- [ENTRY 15 — Thread A framing: the arguments, without the conclusion](#entry-15)
- [ENTRY 16 — Thread B framing: the arguments, without the conclusion](#entry-16)
- [ENTRY 17 — What the leak tests actually caught (write-up material)](#entry-17)

---

<a name="entry-1"></a>
## ENTRY 1 — Why pre-registration, and why it is a methodological step rather than paperwork

**The choice.** `docs/00_PRE_REGISTRATION.md` is written and git-committed before the engine
produces a single performance number. It fixes the hypothesis, the universe, the signal
spec, the parameter grid (N = 12), and the evaluation criteria.

**Why.** Every multiple-testing correction in Section 5 of the pre-registration takes N —
the number of trials — as an input. N is supplied by the researcher. Nothing in the
mathematics can detect a researcher who tried 400 configurations and reports 12. The
correction is therefore only as honest as the accounting behind it, and the accounting is
only verifiable if it was fixed *before* the results were seen.

Git's commit timestamps make the ordering externally checkable. That is the entire point:
the pre-registration converts "trust me, I only tried 12" from an assertion into an artifact
with a verifiable date on it.

**The deeper reason.** The failure mode this guards against is not dishonesty. It is the
ordinary, near-invisible drift where a researcher runs a config, sees a mediocre result,
thinks "the lookback is probably too short," runs another, and never counts either as a
"trial" because each felt like reasoning rather than searching. That drift is how
well-intentioned people produce overfit results. Pre-registration doesn't make you honest;
it makes the drift *visible to yourself*.

**Alternative considered.** Report the grid honestly at the end without pre-registering.
Rejected: it is unverifiable, and — more importantly — it does not protect against the drift
above, because by then the count is reconstructed from memory by the person with the
strongest incentive to under-count.

**What would make this wrong.** Nothing about the practice, but it is worthless if the
amendment log (Section 8) is not maintained honestly. An empty amendment log is itself a
claim.

**Interviewer follow-ups you must be able to answer cold:**
- "You say N = 12. How would I know you didn't try 200?" *(The honest answer names the
  limits of the evidence: the commit history shows the grid was fixed in advance and never
  amended, but nothing proves configurations weren't run outside the harness. Say so.)*
- "Does pre-registration actually help if you're the only reader of your own log?"
- "What's the difference between exploratory analysis and p-hacking, if both involve running
  more configurations?"

---

<a name="entry-2"></a>
## ENTRY 2 — Why time-series momentum rather than cross-sectional or pairs

**The choice.** Time-series (absolute) momentum, per Moskowitz, Ooi & Pedersen (2012).

**Why — the decision criterion is the methodology-to-data-engineering ratio.** The thing
being demonstrated in this project is validation rigour. Every hour spent reconstructing a
survivorship-free universe is an hour not spent on the thing being judged, *and* it is an
hour of work that is easy to get fatally wrong on free data. TSMOM needs only price series
for a set of instruments that all still exist. That is not a shortcut; it is a deliberate
allocation of effort toward the part that carries the signal.

**Why not cross-sectional momentum (Jegadeesh & Titman 1993).** Better-known anomaly, richer
economic story, *the* canonical result. But it requires a point-in-time, survivorship-free
universe with corporate actions handled correctly. On free data that is either impossible or
a months-long data-engineering project with a high chance of a silent, fatal error. It
becomes the right choice the moment WRDS/CRSP access exists, because then the objection
evaporates.

**Why not pairs / cointegration (Gatev, Goetzmann & Rouwenhorst 2006).** Tempting given a
statistics background — cointegration testing, half-life estimation, stationarity are all
genuinely interesting. Rejected because the multiple-testing problem is *acute*: screening
all N(N-1)/2 pairs and keeping the winners is textbook selection bias, and the DSR correction
stops being a supporting analysis and becomes load-bearing. It is a legitimate project, but
it is a *noisier* instrument for demonstrating that you don't fool yourself, because the
central hazard is much larger.

**The property of TSMOM that actually matters here:** low degrees of freedom. Three real
parameters. That is what makes the later honesty claims believable. A strategy with 40
tunable parameters and a beautiful DSR is not evidence of rigour; it is evidence of a
researcher who has not noticed the tension between those two facts.

**What would make this wrong.** If the goal were to demonstrate *signal discovery* rather
than *validation rigour*, this would be the wrong choice — TSMOM is thoroughly known and its
returns are widely reported to have decayed post-publication.

**Interviewer follow-ups:**
- "TSMOM has been public since 2012 and arguably decayed. Why would I care about a
  replication?"
- "You chose the strategy with the fewest parameters. Isn't that just choosing the strategy
  that's hardest to overfit — i.e. dodging the hard problem?"
- "If I gave you CRSP access tomorrow, what would you do differently and why?"

---

<a name="entry-3"></a>
## ENTRY 3 — Why ETFs, and what that costs us

**The choice.** ~25 liquid ETFs across equity indices, fixed income, commodities, and
currencies. Not futures.

**Why.** Futures are what MOP actually traded and are the authentic instrument. But a
futures backtest requires constructing continuous contracts from individual expiries —
choosing a roll rule (calendar, open-interest-based), a roll adjustment method (ratio,
difference, none), and handling the fact that the "price" series you backtest on is a
synthetic object that no one ever traded. Getting the roll wrong is a classic silent killer:
it can manufacture or destroy trend where none existed. It is real work and a real hazard.

ETFs sidestep this entirely: an ETF's adjusted close is a real, tradeable price series.

**What it costs, stated plainly rather than buried.**

1. **Sample truncation.** MOP start in 1985. Most of these ETFs didn't exist before the
   2000s. We lose the 1980s-90s entirely, which removes regimes — and for a trend strategy
   whose performance is famously regime-dependent, that is a material loss, not a footnote.
2. **Instrument mismatch.** An ETF is not its underlying future. It carries an expense ratio
   and tracking error, and commodity ETFs in particular have contango/backwardation drag
   that the futures themselves don't have in the same form. A commodity-ETF trend result is
   not cleanly comparable to MOP's commodity-futures result.
3. **A subtle survivorship issue that does apply.** A hand-picked list of large, liquid,
   currently-existing ETFs is *itself* a survivorship-selected set. ETFs that launched and
   closed are invisible to this universe. For a **time-series** strategy this bites less than
   for a cross-sectional one — the signal is each instrument's own history, not a ranking
   against peers, so there's no "winners rank above losers because losers vanished" effect.
   But it is not zero: the surviving ETFs are disproportionately those that attracted assets,
   which correlates with having had tradeable, trending underlyings. **Do not claim this
   universe is survivorship-free. It isn't. Claim the exposure is limited and explain why.**

**Alternative considered.** Futures via a paid continuous-contract dataset. Rejected on cost
and time, not on merit — this is the upgrade path.

**Interviewer follow-ups:**
- "Your commodity ETFs have contango drag that the futures don't. Doesn't that
  contaminate the commodity sleeve entirely?"
- "You picked 25 ETFs that exist today. Isn't that survivorship bias? Convince me it
  doesn't matter here." *(Note: the honest answer is that it matters less, not that it
  doesn't matter. If you claim it doesn't matter you have failed the question.)*
- "How would your roll rule choice have changed the answer, if you'd used futures?"

---

<a name="entry-4"></a>
## ENTRY 4 — Why the parameter grid is deliberately small

**The choice.** 3 lookbacks x 2 vol targets x 2 rebalance frequencies = **N = 12**. Fixed in
advance, not expanded.

**Why.** Two reasons, and the second is the real one.

1. **MinBTL.** Bailey, Borwein, Lopez de Prado & Zhu (2014) show that with ~5 years of data,
   more than ~45 independent configurations essentially guarantees an in-sample Sharpe of 1
   with an expected out-of-sample Sharpe of *zero*. Their bound: `MinBTL < 2*ln(N)/E[max_N]^2`.
   N = 12 on a 15+ year sample is comfortably inside it.

2. **The grid size determines whether the honesty claims mean anything.** This is the point
   that matters. Any strategy can be made to pass a DSR test by under-reporting N, and any
   strategy will fail one if N is large enough. A researcher who searches 500 configurations
   and then applies a DSR correction has not been rigorous — they have performed rigour
   theatre, because the correction's own assumption (that N is known and honest) has been
   quietly broken by the size of the search. **Keeping the grid small is what makes the
   subsequent correction a real test rather than a ritual.**

**The tension to be honest about.** A small grid means the strategy is less tuned, which
means the raw performance will likely be worse than a searched version. That is the trade
being made deliberately: *believability over performance*. If the write-up shows a mediocre
Sharpe from a 12-config grid, that is a stronger claim than a good Sharpe from a 500-config
grid, and the write-up should say so explicitly rather than apologising for the number.

**Interviewer follow-ups:**
- "Twelve configs is convenient. How do I know you didn't pick the grid *after* poking
  around?" *(See Entry 1. The honest answer acknowledges the limit of the evidence.)*
- "Your 63-day and 126-day lookbacks are ~0.9 correlated. Is that really two trials?"
  *(This is Thread B walking in the door — see Entry 16.)*
- "What's the MinBTL for your actual sample length and grid? Show me the number."

---

<a name="entry-5"></a>
## ENTRY 5 — Why the signal is price-only

**The choice.** No fundamentals anywhere. Signal is a function of past prices only.

**Why.** Free fundamental data is **not point-in-time**. It reports *restated* figures,
stamped at the fiscal period they describe rather than the date they were published. Two
distinct problems follow:

1. **Publication lag.** Q1 earnings are not knowable on 31 March. They appear weeks later.
   A backtest reading them at period-end trades on information that did not exist.
2. **Restatement.** The figure visible today for FY2015 may not be the figure that was
   published in 2016. The data has been silently revised. Even applying a correct
   publication lag does not fix this — you are still using the *corrected* number, which no
   one had at the time.

The second is nastier because it survives the obvious fix, and it is invisible: nothing in
the data announces that it has been revised.

**The design principle.** This is *elimination*, not *mitigation*. Rather than using
fundamentals with an assumed reporting lag and hoping the lag is right, the project removes
the entire bias class from the design. Fewer things to get wrong, and each remaining hazard
gets more attention.

**What it costs.** No fundamental signals, so no valuation, quality, or earnings-based
overlay. Narrower project. Accepted deliberately.

**Interviewer follow-ups:**
- "Suppose I insisted on adding a value overlay. What lag would you use and how would you
  defend it?"
- "Restatement bias survives a reporting lag. How would you actually fix it without a
  point-in-time database?"

---

<a name="entry-6"></a>
## ENTRY 6 — Why volatility scaling, and the confound it introduces

**The choice.** Each position sized `(target_vol / sigma_{i,t}) * sign(...)`, per-instrument
target 40% annualized, sigma from an EWMA of squared daily returns, then the portfolio scaled
to ~10% annualized vol.

**Why.** Three reasons:

1. **Comparability.** Without it, a portfolio across ETFs mixes instruments whose
   volatilities differ by an order of magnitude. Bond ETFs would contribute almost nothing
   and commodity ETFs would dominate. The strategy would be a commodity bet wearing a
   diversified costume.
2. **Fidelity to the source.** MOP scale to 40% per instrument. Deviating would break the
   replication.
3. **It is what practitioners actually do.** Vol targeting is standard in trend following.

**The confound — this is the important part of this entry.** There is a live argument in the
literature that a substantial part of TSMOM's reported performance comes from the
**volatility scaling itself** rather than from the trend signal. The mechanism: vol scaling
mechanically reduces exposure going into high-volatility periods, and high-volatility
periods are disproportionately when large drawdowns happen. So a vol-scaled *anything* —
including a random-sign strategy — can post a better Sharpe than its unscaled version. The
scaling is doing risk management work that gets attributed to the signal.

**The implication for this project.** Reporting a vol-scaled TSMOM Sharpe *without*
disentangling this is a known, citable weakness — and an interviewer who knows the
literature will ask. The honest handling is an ablation:

- vol-scaled TSMOM (the strategy),
- unscaled TSMOM (signal without scaling),
- vol-scaled random sign (scaling without signal),
- long-only (neither).

If (3) is close to (1), the signal is not the source of the performance, and the write-up
must say so. **This ablation is a required output, not optional colour.** Note that it is
also a causal-inference question in disguise: what is the treatment, and what is the correct
control?

**Interviewer follow-ups:**
- "How much of your Sharpe is the signal and how much is the vol targeting? Show me."
- "Your vol estimate uses an EWMA over trailing data. What's the half-life and why? What
  breaks if you halve it?"
- "Vol scaling means you delever into crises. Isn't that just a short-volatility position in
  disguise?"

---

<a name="entry-7"></a>
## ENTRY 7 — Why the t -> t+1 execution lag, and why it is unit-tested rather than asserted

**The choice.** The signal computed from data through the close of bar *t* is executed at
bar *t+1*. Enforced by unit tests that **fail** if any engine function can access a future
bar.

**Why the lag.** The signal at *t* uses the close of *t*. You cannot trade at that close —
by the time you know it, it has happened. Executing at the *t* close is the single most
common look-ahead error in retail backtests, and it is nearly undetectable by inspection
because the code looks fine: the array index is right there, off by one, silently
manufacturing alpha.

**Why unit-tested rather than asserted — this is the part that matters.** Every backtest
author *believes* their engine has no look-ahead. The belief is worthless as evidence. What
distinguishes a claim from a demonstration is a test that would have caught the error had it
been made.

The tests here work by construction rather than by inspection:

1. **Truncation invariance.** Compute the signal at time *t* on the full series. Compute it
   again on the series *truncated at t*. If the values differ, the function saw the future.
   This catches the entire class of errors — off-by-one indexing, `.rolling()` centring,
   full-sample normalisation — with a single property, without needing to anticipate the
   specific bug.
2. **Future-poisoning.** Overwrite all data after *t* with NaN. Recompute. If any output at
   or before *t* changes, something downstream reached forward.
3. **Positive control.** A deliberately leaky function that the test suite must *fail* on.
   Without this, a passing test suite is uninformative — it might pass because it tests
   nothing.

Point 3 is the one people skip and it is the one that makes the other two credible.

**Interviewer follow-ups:**
- "How do you know your engine has no look-ahead?" *(The answer is a test, not a belief.
  If you answer "I was careful," you have failed.)*
- "Your truncation test passes. What class of look-ahead would it still miss?"
- "Why t+1 and not same-close? Convince me you're not just being conservative for show."
- "You rebalance monthly. Is a one-*day* lag realistic for a fund actually executing this
  size?"

---

<a name="entry-8"></a>
## ENTRY 8 — Why costs are modelled in Sharpe units

**The choice.** Following Carver (2015), *Systematic Trading*: cost per round trip expressed
in Sharpe-ratio units — round-trip cost divided by the instrument's annualized volatility —
then multiplied by annual turnover to give the Sharpe drag.

**Why this framing rather than basis points.** It puts cost in the same units as the thing
being claimed. "Costs are 8bp" invites the reply "that's small." But 8bp round-trip on a 15%
vol instrument, traded 12 times a year, is a specific and often decisive amount of Sharpe.
The Sharpe-unit framing makes the comparison immediate and hard to hand-wave: a 0.010-SR
round trip at 10 round trips a year costs 0.10 of Sharpe, so a 0.5-Sharpe pre-cost system
nets 0.4.

It also makes the strategy design tension visible: turnover is not free, and a signal that
needs frequent rebalancing must clear a proportionally higher bar.

**Why a range rather than a point estimate.** A single optimistic cost assumption is one of
the most common ways a backtest lies, and default backtester cost models are typically far
too generous — real costs are commonly understated by 50-100%. So results are reported
across a range, plus a **breakeven cost**: the round-trip cost at which the edge disappears.
The breakeven number is the honest headline, because it lets the reader substitute their own
cost beliefs instead of taking ours.

**Interviewer follow-ups:**
- "What's your breakeven cost, and how does it compare to what you'd actually pay?"
- "Your costs are constant across time. Spreads blew out in March 2020 — what does that do
  to a strategy that delevers into vol?" *(Note the interaction: cost model and vol scaling
  are not independent.)*
- "You're trading ETFs. Why not model market impact? At what AUM does that start to
  matter?"

---

<a name="entry-9"></a>
## ENTRY 9 — Why standard k-fold cross-validation is invalid here

**The choice.** No k-fold. Purged and embargoed schemes only.

**Why.** K-fold assumes observations are IID. Financial observations are not, for two
distinct reasons that are often conflated:

1. **Serial correlation.** Returns and volatilities cluster. Adjacent observations are not
   independent draws.
2. **Overlapping labels — the more damaging one.** If the label at time *t* is a 20-day
   forward return, then the label at *t* and the label at *t+1* share 19 of 20 days of
   information. They are nearly the same observation. Under a random k-fold split, the test
   point at *t* has near-duplicates sitting in the training set. The model doesn't need to
   generalise; it can nearly look the answer up.

The result is a CV score that is optimistic and *confidently* so, which is worse than merely
being wrong — it produces a number that looks like validation and isn't.

**The distinction to be able to draw.** Serial correlation alone would be partially handled
by any time-ordered split. Overlapping labels are what specifically require *purging*,
because the leak is not "the test set is adjacent in time" but "the test label's information
window physically overlaps the training label's information window."

**Interviewer follow-ups:**
- "Why exactly does k-fold fail here? Give me the mechanism, not the slogan." *(If the
  answer is "because time series," that is not an answer.)*
- "Suppose your labels were one-day returns with no overlap. Would k-fold be fine then?"
  *(Think carefully — serial correlation is still present.)*
- "Why not just use a single train/test split and be done?"

---

<a name="entry-10"></a>
## ENTRY 10 — Purging: what it is and why the horizon defines it

**The choice.** Purging per Lopez de Prado (2018), AFML Ch. 7: remove from the *training*
set any observation whose label window overlaps in time with any *test* observation's label
window.

**The mechanism.** If a test label spans [t0, t1], then any training sample whose own label
window intersects [t0, t1] shares information with it. Training on that sample leaks test
information into the model. Purging deletes the overlap.

**The point that is usually missed.** Purging is defined by the **label horizon**, not by
calendar adjacency. A 1-day-horizon label needs almost no purging. A 60-day-horizon label
needs 60 days purged on each side of every test fold. **The horizon determines the purge —
so if you can't state your label horizon precisely, you can't purge correctly.** This is why
the label definition has to be pinned down before the validation design, not after.

**Implementation.** Represent each observation's label as an interval `[t_start, t_end]`.
For each test fold, compute the union of test label intervals and drop every training
observation whose interval intersects that union. Interval arithmetic, not index offsets —
index offsets break the moment the bar spacing isn't uniform (holidays, missing days), which
it never is.

**Interviewer follow-ups:**
- "What's your label horizon and how did you choose it?"
- "You purge based on intervals. What happens across a market holiday?"
- "If I set the horizon to 1 day, does purging still do anything?"

---

<a name="entry-11"></a>
## ENTRY 11 — Embargoing: why purging alone is insufficient

**The choice.** A 21-trading-day (~1 month) embargo after each test fold, per AFML Ch. 7.

**Why purging is not enough.** Purging removes training samples whose label windows
*overlap* test label windows. But serial correlation means a training sample that starts
just *after* the test fold ends — no overlap at all, so purging leaves it — still carries
information about the test period. Volatility clusters; a return the day after the test
window is informative about the test window. The embargo drops a block of training
observations immediately following each test fold to break that residual channel.

**Why *after* and not *before*.** Purging already handles the before-side via overlap. The
asymmetry is the point and it is a common confusion: the embargo exists specifically for
the forward-in-time leak that overlap logic misses.

**Why 21 days.** Honestly: it is a convention (~1 trading month), and AFML suggests ~1% of
sample length as a rule of thumb. **It is not derived from this data.** The defensible move
is not to pretend otherwise but to test sensitivity — report results across embargo lengths
(0, 5, 21, 63) and show whether the conclusion moves. If it moves a lot, that is a finding
worth reporting, not a parameter to tune until it doesn't.

**A choice to flag rather than hide:** an embargo that is too long starves the training set,
especially on a truncated ETF sample. There is a real bias-variance tension here and no
principled optimum. Say so.

**Interviewer follow-ups:**
- "Why 21 days? Why not 5? Why not 60?" *(The honest answer starts with "it's a convention"
  and continues with the sensitivity analysis. An answer that claims 21 is optimal is a
  worse answer.)*
- "Why is the embargo one-sided?"
- "Your sample is short. Doesn't a 21-day embargo cost you meaningful training data?"

---

<a name="entry-12"></a>
## ENTRY 12 — Walk-forward: what it estimates and what it cannot

**The choice.** Expanding-window walk-forward: select on data up to *t*, evaluate on
*(t, t+h]*, step forward. The concatenated out-of-sample path is the primary reported result.

**What it estimates.** The counterfactual "what would have happened had I run this process
live, making each decision with only the information available at that moment." That is the
question a capital allocator actually asks, and walk-forward is the only method here that
answers it directly. This is the strongest argument in its favour and it should not be
undersold.

**What it cannot do.** It produces **one path**. One number. A single realisation of a
high-variance random variable. With a short ETF sample the standard error on that Sharpe is
large — potentially large enough that the point estimate is nearly uninformative. It supports
no meaningful inference: there is no distribution, so there is no confidence interval that
isn't smuggled in from an assumption.

There is also a subtler issue: the walk-forward path is *itself* a single draw from the space
of possible histories. Re-running with a slightly different start date can produce a
materially different number. The single path invites false precision.

**This entry is where Thread A begins.** The tension is now explicit: walk-forward answers
the *right question* with *poor statistical power*. See Entry 15.

**Interviewer follow-ups:**
- "What's the standard error on your walk-forward Sharpe?"
- "You start walk-forward at date X. What if you'd started a month later?"
- "Expanding or rolling window? Defend the choice." *(Expanding uses more data but weights
  the distant past equally; rolling adapts to regime but throws away information. There is
  no free answer.)*

---

<a name="entry-13"></a>
## ENTRY 13 — CPCV: what it buys and what it costs

**The choice.** Combinatorial Purged Cross-Validation per AFML Ch. 12: partition into N
groups, form all train/test combinations of size k, purge and embargo each, generate many
backtest paths.

**What it buys.** A **distribution** of out-of-sample Sharpes instead of a point. That is a
large gain: confidence intervals become meaningful, and the Probability of Backtest
Overfitting (PBO) — the fraction of paths where the in-sample-best configuration
underperforms the out-of-sample median — becomes computable. Recent comparative work finds
CPCV suppresses overfitting better than walk-forward on PBO metrics.

**What it costs — and this is the crux.** Some CPCV folds train on data that comes *after*
the test data. The model is fit on the future to predict the past. Purging and embargoing
prevent *leakage* across the boundary, but they do not make the arrangement *realisable*. No
live trader ever occupied that information position.

So CPCV's paths are not "what would have happened." They are draws from a hypothetical
population of train/test arrangements, most of which could never occur. The question it
answers is closer to: *"is there a stable relationship in this data, robust to which subset
you learn it from?"* That is a real and useful question. **It is not the same question
walk-forward answers.**

**The framing that clarifies it.** The two methods estimate different estimands. Walk-forward
estimates a *live-trading counterfactual*. CPCV estimates a *data-generating-process
stability property*. Asking which is "correct" without specifying which estimand you want is
a category error — and noticing that is the beginning of Thread A rather than the end of it.

**Interviewer follow-ups:**
- "Your CPCV trains on the future. How is that not look-ahead?" *(A precise answer
  distinguishes leakage from realisability. Most candidates cannot.)*
- "What population are your CPCV paths a sample from?"
- "If CPCV and walk-forward disagree, which do you report to a PM?" *(This is Thread A. Do
  not answer it from memory.)*

---

<a name="entry-14"></a>
## ENTRY 14 — The Deflated Sharpe Ratio: the machinery

**The choice.** DSR per Bailey & Lopez de Prado (2014), *JPM* 40(5), 94-107.

**What it does.** The Probabilistic Sharpe Ratio asks: given sample length, skew and
kurtosis, what is the probability the true Sharpe exceeds a benchmark? The DSR sets that
benchmark to the *expected maximum Sharpe from N skill-less trials* — the Sharpe you would
expect to see purely from picking the best of N coin flips.

Benchmark:
```
SR0 = sqrt(V[{SR_n}]) * ( (1 - gamma) * Z^-1[1 - 1/N] + gamma * Z^-1[1 - 1/(N*e)] )
```
where gamma ~ 0.5772 (Euler-Mascheroni), Z^-1 the inverse standard-Normal CDF, e Euler's
number, V[{SR_n}] the variance of trial Sharpes, N the number of independent trials.

Then:
```
DSR = Z[ (SR_hat - SR0) * sqrt(T - 1) / sqrt(1 - g3*SR_hat + ((g4 - 1)/4) * SR_hat^2) ]
```
with g3 skewness, g4 non-excess kurtosis, T observations, SR_hat the observed
per-observation Sharpe. Pass at 95% if DSR > 0.95.

**The worked example that makes it concrete.** From the paper: N = 1000, T = 1250, g3 = -3,
g4 = 10, annualized SR_hat = 2.5 gives DSR ~ 0.90 — **rejected at 95% despite a 2.5 Sharpe.**
Not because 2.5 is a bad number, but because the best of 1000 trials on 5 years of skewed,
fat-tailed data is *expected* to look roughly that good by chance.

**Two things it corrects simultaneously** (worth separating, because they're often merged):
1. **Selection bias** — the best of N looks good by construction.
2. **Non-normality** — negative skew and fat tails inflate the Sharpe's apparent
   significance, because the Sharpe's own standard error depends on the higher moments.

**The load-bearing assumption.** N must be the number of **independent** trials, and it must
be honestly known. Neither holds cleanly in practice. That is not a footnote — it is Thread
B. See Entry 16.

**Interviewer follow-ups:**
- "Walk me through why a 2.5 Sharpe can fail a DSR test."
- "Where does the Euler-Mascheroni constant come from?" *(It's from the expected maximum of
  N draws from a Gumbel-type extreme-value distribution. Know this.)*
- "Your DSR uses V[{SR_n}], the variance of trial Sharpes. What if you'd only run one
  trial?"
- "What's the difference between PSR and DSR in one sentence?"

---

<a name="entry-15"></a>
## ENTRY 15 — Thread A framing: the arguments, without the conclusion

**The question.** Walk-forward and CPCV can disagree about whether the edge is real. Which
estimate should govern a capital allocation decision?

**This entry deliberately does not contain a conclusion.** The machinery is built; the
outputs will exist; the position is the author's to take after seeing them and thinking it
through. A recited conclusion fails on the first follow-up, and the follow-ups on an open
question are unbounded — they cannot be pre-answered. What follows is the map, not the
destination.

### The case for believing walk-forward

- It estimates the live-trading counterfactual. That is literally the decision being made.
- Every fold is realisable. No fold requires information the trader could not have had.
- Its failure mode is *conservative*: it may understate an edge, but is unlikely to
  manufacture one.
- Deployment happens sequentially in time. A method that respects the arrow of time matches
  the structure of the problem.

### The case for believing CPCV

- One path is one draw. Deciding on a single high-variance realisation is not inference.
- CPCV's distribution enables actual statistical statements and PBO.
- Purging and embargoing genuinely prevent leakage; the objection to CPCV is realisability,
  not contamination — and those are different objections.
- A relationship that only holds in one specific temporal arrangement is arguably not a
  relationship at all. Robustness across arrangements is evidence about the DGP.

### The counter-arguments to each

- *Against walk-forward:* the path depends on an arbitrary start date; the standard error may
  be so wide that the point estimate carries little information; "realistic" is not the same
  as "informative."
- *Against CPCV:* it can pass a strategy whose edge is real only in arrangements that could
  never occur. For a *non-stationary* series — which financial data is — training on the
  future may be learning a relationship that did not exist yet. That is arguably a deeper
  problem than leakage, because it survives purging.

### What the outputs need to show to favour one

- **If they agree:** the question is moot for this strategy, and *that* is a finding worth
  reporting cleanly.
- **If CPCV > walk-forward:** suspect that CPCV's non-sequential folds let the model see both
  sides of a regime transition. Check whether the divergence concentrates around regime
  boundaries. If it does, it is evidence that CPCV's advantage is an artifact of
  non-stationarity, not a genuine power gain.
- **If walk-forward > CPCV:** unusual, and worth investigating rather than celebrating.
  Possibly the expanding window benefits from a favourable late-sample regime — which would
  be a walk-forward artifact, not a CPCV failure.
- **If the CPCV distribution is wide and straddles zero:** the honest reading is that the
  sample cannot resolve the question, and the walk-forward point estimate's apparent
  precision was an illusion all along.

### The framing worth thinking hardest about

They estimate different estimands (Entry 13). "Which is correct" may be malformed. The
better question is: *for the decision at hand, which estimand do I want?* For a PM sizing a
live allocation, the live-trading counterfactual seems to be the object of interest — but
then the wide standard error on a single path is a problem for the decision, not just for
the statistics.

A causal-inference lens helps: each method implies a different assignment mechanism for how
observations land in train versus test. Walk-forward's mechanism is the real-world one. CPCV's
is a hypothetical randomisation. Under what conditions does a hypothetical randomisation
identify the real-world estimand? *That* is the question worth working — and it is not
answered by running more code.

**What must be honest in the write-up.** If, after working through it, the position is "I
built both, they disagree, and I don't have a settled view on which governs" — **that is a
publishable position** and a respectable one for an entry-level candidate. It is far stronger
than a confident answer that collapses on the second follow-up.

---

<a name="entry-16"></a>
## ENTRY 16 — Thread B framing: the arguments, without the conclusion

**The question.** The DSR corrects for N independent trials. What is N, actually?

**Again: machinery only, no conclusion.** The map, not the destination.

### The problem

This grid has 12 configurations. They are not 12 independent bets. A 63-day and a 126-day
lookback on the same universe are close to the same strategy; their return series may be 0.9+
correlated. Treating them as 12 independent trials over-deflates the Sharpe and could reject
a real edge. Treating them as 1 under-deflates and could pass a fake one.

**The deeper issue.** N is not a property of the data. It is a property of *the search the
researcher performed*, which is unobservable from outside — and, as Entry 1 notes, is
frequently unobservable to the researcher too, because exploratory runs don't feel like
trials.

### The literature's own remedy, and why it is not a solution

Bailey & Lopez de Prado suggest converting M dependent trials to effective independent
trials:
```
N_hat = rho_bar + (1 - rho_bar) * M
```
with `rho_bar` the average off-diagonal correlation of trial returns. But:

- It assumes a single common correlation. Real trial-correlation matrices are structured
  and clustered, not exchangeable — configs cluster by lookback, by rebalance frequency, by
  vol target.
- Averaging over a structured matrix discards exactly the structure that determines the
  effective dimension.
- It is rarely computed in practice. The overwhelmingly common move is to plug in the raw
  count and move on — which means the correction most people report is systematically
  mis-specified.

### The estimators to build and compare

1. **Naive:** N = 12. Every configuration counts.
2. **rho_bar formula:** the literature's remedy, above.
3. **PCA / eigenvalue-based effective dimension:** eigendecompose the trial-return
   correlation matrix. Candidates: participation ratio `(sum λ_i)^2 / sum(λ_i^2)`; number of
   components explaining 95% of variance; entropy-based effective rank. These respect
   structure that `rho_bar` averages away.
4. **Correlation clustering:** cluster trial return series; count clusters as effective
   trials. Intuitive, but the count depends on the linkage and threshold — which imports a
   new arbitrary parameter, and that tension is itself worth reporting rather than hiding.
5. **Lower bound:** N = 1. One strategy, one bet.

### The output that matters

**DSR as a function of assumed N**, with the estimators marked on it, and the **flip point**
— the N at which the verdict crosses 0.95 — identified explicitly.

The result being driven toward is of the shape: *"The strategy passes DSR at 95% under an
effective-N accounting (N_eff ~ X) and fails under naive accounting (N = 12). The verdict
flips at N = Y. Here is which I believe and why."*

This is honest whichever way it lands, and it is a real result: it shows the DSR verdict is
not a fact about the strategy but a *function of an unobservable*, and it quantifies exactly
how sensitive that verdict is.

### Why this is genuinely in an actuarial/causal wheelhouse

This is the effective-sample-size problem. Correlated hypothesis tests, effective degrees of
freedom under dependence, participation ratios — this is standard equipment in statistics
that the quant-finance literature has, in this specific application, handled with a
first-order approximation. That gap is the opportunity. Connections worth pulling on:
effective sample size under clustering; Meff in multiple-testing genomics (the eigenvalue
methods there — Cheverud, Li & Ji — are attacking the identical problem); the design-effect
concept in survey sampling.

### What must be honest

- Effective-N estimation on 12 series with limited history is *itself* noisy. The eigenvalue
  spectrum of a 12x12 correlation matrix estimated from a short sample has large sampling
  error. **The uncertainty in N_eff must be reported, not just the point estimate.** Failing
  to do so would repeat, one level up, exactly the error being diagnosed one level down —
  and an interviewer who spots that will enjoy pointing it out.
- There is no ground truth for N_eff. Nothing here can be validated against a known answer.
- If the flip point falls inside the plausible range of N_eff, the honest conclusion is that
  **the sample cannot resolve whether the strategy has an edge.** That is a legitimate and
  reportable finding.

**Interviewer follow-ups:**
- "What's your N and why?"
- "Your configs are correlated. Doesn't that mean the DSR is over-deflating?"
- "How confident are you in your N_eff estimate? What's the standard error?" *(The recursion
  is the point. Sit with it.)*
- "If the answer depends this much on an unobservable, is the DSR useful at all?" *(A real
  question. Do not dismiss it.)*

---

<a name="entry-17"></a>
## ENTRY 17 — What the leak tests actually caught (write-up material)

**This entry is a record of the tests working.** It is not a confession to be buried; it is
the strongest available evidence that the methodology in Entry 7 is real rather than
decorative. A test suite that has never caught anything is a test suite that has never been
shown to work.

Four findings from the first full run of `run_checks.py`. Two were real bugs in the engine,
one was a real bug in the *test harness*, and one was a false positive that had to be
diagnosed rather than silenced.

### Finding 1 — A genuine look-ahead bug, in code written by someone who knew better

`target_positions` contained:

```python
vol_floor = vol.quantile(0.01, axis=0)   # full-sample quantile
vol_safe = vol.clip(lower=vol_floor, axis=1)
```

A **full-sample** quantile. The volatility floor applied in 2010 was computed from
volatilities observed through 2025. Unambiguous look-ahead. Truncation-invariance violation:
**~0.10 in position units.**

**Why this one matters more than the others.** It was not written carelessly. It was written
as a *defensive* guard — dividing by a near-zero vol estimate produces absurd position sizes,
so a floor is genuinely needed. The bug entered disguised as safety code, in a file whose
own module docstring warns against exactly this class of error (hazard #3: "any full-sample
statistic used to normalise a series is look-ahead, even though it feels innocuous").

**It was not caught by reading the code. It was caught by a property test.** That is the
entire argument for property-based leak detection over inspection, and it is worth making
this concrete in the README rather than claiming abstract rigour. Fixed via
`floor_volatility()`, which uses an expanding (causal) quantile with a running-min fallback.

### Finding 2 — A bug in the test harness that made a leaky control pass

The truncation harness guarded with `both_valid = a.notna() & b.notna()`, skipping points
where either series was NaN. That guard has a legitimate purpose: warm-up periods produce
NaN in both series, and comparing them is meaningless.

But it silently destroyed the test. **A leaky function evaluated on data truncated at t
produces NaN at t precisely because the future it wants to read is not there.** So the
truncated value was NaN exactly at the point that proves the leak, `both_valid` was False,
the point was skipped, and the harness reported a clean `0.0`.

The naive harness reported **PASS for `shift(-1)`** — the most blatant look-ahead there is.

The distinction that fixes it:
- NaN in **both** → warm-up. Skip. Evidence of nothing.
- NaN in **truncated only**, where full is valid → the function needed data beyond *t*.
  **That absence is itself the evidence.**

**The lesson is uncomfortable and worth keeping:** the positive controls existed *because*
a test suite that has never failed is untrustworthy — and the positive control still
initially passed, for a reason nobody anticipated. Guarding against known failure modes is
not the same as having a working test. This is why Entry 7's Layer 3 is not optional.

### Finding 3 — A false positive that must be diagnosed, not silenced

The full-pipeline truncation test failed with a violation of **0.81**, apparently
implicating `scale_to_portfolio_vol`.

It was not. Isolating the pipeline stage by stage showed `scale_to_portfolio_vol` agreeing
to 16 significant figures. The culprit was `rebalance_mask`, which contained
`is_last.iloc[-1] = True` — forcing a rebalance on the final bar.

On a series truncated at *t*, bar *t* **is** the last bar, so it rebalanced. On the full
series the same bar was a mid-month Wednesday, so it did not. The test flagged a discrepancy,
but **no future price was ever read**. Truncation merely changed which bar was last.

Two things follow, and they pull in opposite directions:

1. **A truncation-test failure is *evidence* of look-ahead, not *proof*.** The discipline is
   to find the mechanism before fixing. Reflexively "fixing" a false positive means mangling
   a correct engine to silence a test.
2. **The line was wrong anyway, for a better reason.** It rebalanced on whatever day the data
   happened to end — which is not a trading rule. A real strategy rebalances on month-ends,
   not on "the day my CSV stops." Removing it fixed the invariance failure and a modelling
   error simultaneously.

Note also the subtlety in the fix: `rebalance_mask` uses `.shift(-1)` on the **calendar**.
That is *not* look-ahead. You know on 31 January that it is the last business day of the
month, because you own a calendar. You do not need tomorrow's price to know tomorrow's date.
Being able to state precisely why one `.shift(-1)` is fine and another is fatal is the
difference between following a rule and understanding it.

### Finding 4 — A test that passed on degenerate data

The cost-monotonicity check ran against a synthetic fixture with `trend_strength=0.0008`,
which produced a **gross Sharpe of 9.8**.

That number is the tell. Not "the strategy is good" — *the fixture is broken*. At that trend
strength the series is nearly deterministic, the cost drag becomes numerically irrelevant,
and the test passes without exercising the property it claims to test. Recalibrated to
`trend_strength=0.0001` (gross Sharpe ≈ 0.8, realistic for trend following), where the cost
drag is actually visible.

**The generalisation:** a test that passes on degenerate data is not evidence. Sanity-check
the *fixture*, not just the assertion. A Sharpe of 9.8 anywhere in a test suite should stop
you cold — and the fact that it did not, on the first pass, is itself instructive about how
easily a good-looking number escapes scrutiny.

### Why all four belong in the write-up

The claim this project makes is not "my engine is clean." It is **"here is the machinery
that would tell me if it weren't, and here is it working."** These four findings are that
machinery working: catching a real leak, catching its own blind spot, correctly distinguishing
a false positive from a real failure, and catching a fixture that made a test vacuous.

An interviewer asking *"how do you know your engine has no look-ahead?"* (Entry 7, the
single highest-value question in this document) can be answered with Finding 1 specifically:
*"Because a test caught one that I had already written a docstring warning myself against."*
That answer is worth more than any amount of asserted care.

---

## Study protocol

Do this before any interview, and before the resume line is defended anywhere:

1. **Read one entry. Close the file. Re-derive it out loud.** Not "recall the words" —
   reconstruct the argument. If the reconstruction stalls, that entry is not yet yours.
2. **Answer the follow-ups cold, in writing.** They are the actual exam. The entries are
   preparation for them, not substitutes.
3. **For Entries 15 and 16 (the threads): do not look for the answer in this document. It
   isn't there, deliberately.** Run the code, look at the outputs, form a view, write it
   down, then attack your own view. Whatever survives is yours and is defensible. Anything
   recited will not survive contact.
4. **The honest fallback is available and is strong:** "I built the machinery, here are the
   outputs, I haven't settled on an interpretation" beats a confident answer that collapses
   under one follow-up. Use it if the view hasn't formed yet.

**The single highest-value question in this document** — worth more than the rest combined —
is: *"how do you know your engine has no look-ahead?"* The answer is a test (Entry 7), not a
belief. Everything else in this project rests on that answer being real.
