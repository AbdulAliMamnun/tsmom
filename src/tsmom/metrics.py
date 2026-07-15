"""Performance metrics, including the honesty metrics.

Standard metrics (Sharpe, drawdown, Calmar, Sortino) are here because they are expected.
The metrics that matter for this project are further down:

- Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012)
- Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)
- Minimum Track Record Length
- Minimum Backtest Length (Bailey, Borwein, Lopez de Prado & Zhu 2014)

The DSR is the load-bearing one. It answers: "given that I tried N configurations on a
sample of length T with this much skew and kurtosis, how surprised should I be by the best
Sharpe I found?" Usually the answer is "not very."

See docs/REASONING_LOG.md ENTRY 14.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from . import config

EULER_MASCHERONI = 0.5772156649015329


# --------------------------------------------------------------------------------------
# Standard metrics
# --------------------------------------------------------------------------------------


def sharpe_ratio(
    returns: pd.Series,
    rf: float = 0.0,
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised Sharpe ratio.

    Convention: excess return over `rf` (in per-period units), scaled by sqrt(periods).
    State the convention when reporting -- "Sharpe of 0.6" is not a complete statement
    without it.
    """
    r = returns.dropna()
    if len(r) < 2:
        return float("nan")
    excess = r - rf / periods_per_year
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(excess.mean() / sd * np.sqrt(periods_per_year))


def annualized_return(
    returns: pd.Series, periods_per_year: int = config.TRADING_DAYS_PER_YEAR
) -> float:
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    total = float((1.0 + r).prod())
    years = len(r) / periods_per_year
    if years <= 0 or total <= 0:
        return float("nan")
    return total ** (1.0 / years) - 1.0


def annualized_vol(
    returns: pd.Series, periods_per_year: int = config.TRADING_DAYS_PER_YEAR
) -> float:
    return float(returns.dropna().std(ddof=1) * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float:
    """Maximum peak-to-trough decline. Returned as a negative number."""
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    equity = (1.0 + r).cumprod()
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def calmar_ratio(
    returns: pd.Series, periods_per_year: int = config.TRADING_DAYS_PER_YEAR
) -> float:
    mdd = max_drawdown(returns)
    if mdd == 0 or np.isnan(mdd):
        return float("nan")
    return annualized_return(returns, periods_per_year) / abs(mdd)


def sortino_ratio(
    returns: pd.Series,
    rf: float = 0.0,
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> float:
    """Sharpe with a downside-deviation denominator.

    Relevant here because trend-following returns are famously positively skewed: many
    small losses, occasional large gains. The Sharpe ratio penalises upside volatility
    identically to downside, which understates a positively-skewed strategy.
    """
    r = returns.dropna()
    if len(r) < 2:
        return float("nan")
    excess = r - rf / periods_per_year
    downside = excess[excess < 0]
    if len(downside) < 2:
        return float("nan")
    dd = float(np.sqrt((downside**2).mean()))
    if dd == 0:
        return float("nan")
    return float(excess.mean() / dd * np.sqrt(periods_per_year))


# --------------------------------------------------------------------------------------
# The honesty metrics
# --------------------------------------------------------------------------------------


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    benchmark_sr: float = 0.0,
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> float:
    """Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012).

    P(true SR > benchmark_sr), correcting for sample length, skewness and kurtosis.

        PSR = Z[ (SR_hat - SR*) * sqrt(T-1) / sqrt(1 - g3*SR_hat + ((g4-1)/4)*SR_hat^2) ]

    Note SR_hat and SR* here are PER-PERIOD, not annualised. Mixing those up is a common
    and silent error -- it produces a plausible-looking number that is wrong by a factor of
    sqrt(252). The function takes annualised inputs and de-annualises internally, so callers
    can pass the number they actually have.

    g4 is NON-EXCESS kurtosis (3.0 for a Normal), not scipy's default excess kurtosis.
    """
    r = returns.dropna()
    T = len(r)
    if T < 3:
        return float("nan")

    sr_ann = sharpe_ratio(r, periods_per_year=periods_per_year)
    if np.isnan(sr_ann):
        return float("nan")

    sr = sr_ann / np.sqrt(periods_per_year)
    sr_star = benchmark_sr / np.sqrt(periods_per_year)

    g3 = float(stats.skew(r, bias=False))
    g4 = float(stats.kurtosis(r, fisher=False, bias=False))  # non-excess

    denom_sq = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr**2
    if denom_sq <= 0:
        return float("nan")

    z = (sr - sr_star) * np.sqrt(T - 1) / np.sqrt(denom_sq)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(
    n_trials: int,
    sr_variance: float,
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> float:
    """Expected maximum Sharpe from `n_trials` skill-less trials.

        SR0 = sqrt(V) * ( (1-gamma)*Z^-1[1 - 1/N] + gamma*Z^-1[1 - 1/(N*e)] )

    This is the benchmark the DSR deflates against. It comes from extreme-value theory: the
    maximum of N draws converges to a Gumbel distribution, and the Euler-Mascheroni constant
    appears in its mean. Know this -- it is a standard interview follow-up.

    Args:
        n_trials: number of INDEPENDENT trials. This is the load-bearing assumption and
            it is exactly what Thread B is about (ENTRY 16). N is not observable.
        sr_variance: variance of the trial Sharpes (annualised units)

    Returns annualised SR0.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1:
        return 0.0
    if sr_variance <= 0:
        return 0.0

    gamma = EULER_MASCHERONI
    e = np.e

    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))

    return float(np.sqrt(sr_variance) * ((1.0 - gamma) * z1 + gamma * z2))


def deflated_sharpe_ratio(
    returns: pd.Series,
    n_trials: int,
    sr_variance: float,
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    The PSR evaluated against the expected maximum Sharpe from N skill-less trials, rather
    than against zero. Corrects for TWO things at once:

      1. Selection bias -- the best of N looks good by construction.
      2. Non-normality -- negative skew and fat tails inflate the Sharpe's apparent
         significance, because the Sharpe's own standard error depends on higher moments.

    Pass at 95% if DSR > 0.95.

    The paper's worked example, worth internalising: N=1000, T=1250, skew=-3, kurtosis=10,
    annualised SR=2.5 gives DSR ~ 0.90. REJECTED at 95% despite a 2.5 Sharpe -- because the
    best of 1000 trials on 5 years of skewed, fat-tailed data is expected to look about that
    good by chance alone.
    """
    sr0_ann = expected_max_sharpe(n_trials, sr_variance, periods_per_year)
    return probabilistic_sharpe_ratio(returns, benchmark_sr=sr0_ann, periods_per_year=periods_per_year)


def minimum_track_record_length(
    returns: pd.Series,
    benchmark_sr: float = 0.0,
    confidence: float = 0.95,
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> float:
    """How many observations are needed for the observed SR to be significant.

    If this exceeds your actual sample length, you do not have enough data to make the
    claim -- regardless of how good the Sharpe looks.
    """
    r = returns.dropna()
    if len(r) < 3:
        return float("nan")

    sr_ann = sharpe_ratio(r, periods_per_year=periods_per_year)
    sr = sr_ann / np.sqrt(periods_per_year)
    sr_star = benchmark_sr / np.sqrt(periods_per_year)

    if sr <= sr_star:
        return float("inf")

    g3 = float(stats.skew(r, bias=False))
    g4 = float(stats.kurtosis(r, fisher=False, bias=False))

    z = stats.norm.ppf(confidence)
    numerator = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr**2
    return float(1.0 + numerator * (z / (sr - sr_star)) ** 2)


def minimum_backtest_length(n_trials: int, target_sharpe: float = 1.0) -> float:
    """Minimum backtest length in years (Bailey, Borwein, Lopez de Prado & Zhu 2014).

        MinBTL < 2*ln(N) / E[max_N]^2

    Their anchor, worth quoting accurately: with only 5 years of data, no more than ~45
    independent configurations should be tried, or you are "almost guaranteed" to produce a
    strategy with an in-sample annualised Sharpe of 1 and an expected out-of-sample Sharpe
    of zero.

    This is the check that justifies keeping the grid small (ENTRY 4).
    """
    if n_trials < 2:
        return 0.0
    return float(2.0 * np.log(n_trials) / target_sharpe**2)


# --------------------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------------------


def summary(
    returns: pd.Series,
    label: str = "",
    periods_per_year: int = config.TRADING_DAYS_PER_YEAR,
) -> dict:
    """Standard summary. Note there is no DSR here -- the DSR needs N and the trial Sharpe
    variance, which are properties of the SEARCH, not of a single return series. That
    separation is deliberate: it is a reminder that significance is not a property of a
    strategy in isolation.
    """
    r = returns.dropna()
    return {
        "label": label,
        "n_obs": len(r),
        "years": len(r) / periods_per_year,
        "ann_return": annualized_return(r, periods_per_year),
        "ann_vol": annualized_vol(r, periods_per_year),
        "sharpe": sharpe_ratio(r, periods_per_year=periods_per_year),
        "sortino": sortino_ratio(r, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(r),
        "calmar": calmar_ratio(r, periods_per_year),
        "skew": float(stats.skew(r, bias=False)) if len(r) > 2 else float("nan"),
        "kurtosis": float(stats.kurtosis(r, fisher=False, bias=False)) if len(r) > 3 else float("nan"),
        "psr_vs_zero": probabilistic_sharpe_ratio(r, 0.0, periods_per_year),
    }
