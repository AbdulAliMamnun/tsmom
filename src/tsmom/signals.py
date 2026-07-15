"""Signal construction.

THE INVARIANT THIS MODULE MAINTAINS
-----------------------------------
Every function here is *causal*: the value it produces at time t is a function of data at
times <= t only. Nothing reaches forward. This is enforced by tests/test_no_lookahead.py,
which checks it by construction (truncation invariance and future-poisoning) rather than by
inspection.

Why the invariant lives here rather than in the backtester: look-ahead is easiest to
introduce during signal construction, where it is also hardest to see. `.rolling(center=True)`,
a full-sample `.mean()` used to normalise, a `.shift(-1)` that looked right at 2am -- all of
these produce code that reads fine and quietly manufactures alpha.

The specific hazards this module is written to avoid:

1. pandas `.rolling()` is backward-looking by default, but `center=True` silently makes it
   two-sided. Never pass it.
2. `.ewm()` is causal by default. Fine.
3. Any full-sample statistic (mean, std, min, max, quantile) used to normalise a series is
   look-ahead, even though it feels innocuous. The z-score of today's value against the
   full-sample mean uses tomorrow's data.
4. `.fillna(method='bfill')` propagates future values backward. Never use it on anything
   the signal touches. (Forward-fill is causal; backward-fill is not.)

See docs/REASONING_LOG.md ENTRY 7.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def ewma_volatility(
    returns: pd.DataFrame,
    halflife: int = config.VOL_HALFLIFE_DAYS,
    annualize: bool = True,
) -> pd.DataFrame:
    """Exponentially-weighted volatility estimate.

    Causal: `.ewm()` looks backward only. The value at t uses returns at times <= t.

    Args:
        returns: daily simple returns
        halflife: EWMA half-life in trading days
        annualize: scale by sqrt(252)

    Why EWMA and not a simple rolling std: volatility clusters, so recent observations are
    more informative about tomorrow's vol than observations from six months ago. A simple
    rolling window weights them equally and then drops them off a cliff at the window edge,
    which produces artificial jumps in position size when a single large old return exits
    the window.
    """
    vol = returns.ewm(halflife=halflife, min_periods=halflife).std()
    if annualize:
        vol = vol * np.sqrt(config.TRADING_DAYS_PER_YEAR)
    return vol


def trailing_return(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Trailing total return over `lookback` trading days.

    Causal: value at t is (P_t / P_{t-lookback}) - 1. Uses only prices at times <= t.

    This is the raw material of the momentum signal. Note it is a *total* return series
    (prices are already dividend-adjusted), not an excess return -- the excess-return
    adjustment happens in `tsmom_signal` where the risk-free rate is subtracted.
    """
    return prices / prices.shift(lookback) - 1.0


def tsmom_signal(
    prices: pd.DataFrame,
    lookback: int,
    risk_free_daily: pd.Series | None = None,
) -> pd.DataFrame:
    """Time-series momentum signal: sign of the trailing excess return.

    Following Moskowitz, Ooi & Pedersen (2012): +1 if the trailing `lookback`-day excess
    return is positive, -1 if negative.

    Causal: uses prices at times <= t only.

    Args:
        prices: adjusted closes
        lookback: trailing window in trading days
        risk_free_daily: daily risk-free rate. If None, the raw (total) return sign is
            used and the signal is a total-return momentum signal rather than an
            excess-return one.

    A note on why the risk-free adjustment is not cosmetic: for a bond ETF in a high-rate
    environment, the total return can be positive while the *excess* return is negative.
    MOP's claim is about excess returns. Dropping the adjustment quietly changes the
    hypothesis being tested -- and would show up as a suspiciously long-biased bond sleeve.
    """
    tr = trailing_return(prices, lookback)

    if risk_free_daily is not None:
        # Compound the daily risk-free rate over the same trailing window, so that we are
        # comparing like with like. Causal: rolling().sum() is backward-looking.
        rf_cum = (
            np.log1p(risk_free_daily)
            .rolling(lookback, min_periods=lookback)
            .sum()
            .pipe(np.expm1)
        )
        rf_aligned = rf_cum.reindex(tr.index).ffill()  # ffill is causal; bfill would not be
        excess = tr.sub(rf_aligned, axis=0)
    else:
        excess = tr

    signal = np.sign(excess)
    signal = signal.where(excess.notna())
    return signal


def floor_volatility(vol: pd.DataFrame, quantile: float = 0.01) -> pd.DataFrame:
    """Floor the volatility estimate, causally.

    WHY THIS FUNCTION EXISTS -- read this before changing it.

    Dividing by a near-zero volatility estimate produces an absurd position size. A floor is
    genuinely needed. The obvious implementation is:

        vol_floor = vol.quantile(0.01, axis=0)   # <-- LOOK-AHEAD
        vol_safe = vol.clip(lower=vol_floor, axis=1)

    That is a FULL-SAMPLE quantile. The floor applied in 2010 is computed from volatilities
    observed through 2025. It is look-ahead, and it arrived here disguised as defensive
    coding -- which is exactly why it is dangerous: the intent is safety, so it does not
    read like a bug.

    This was written that way in the first draft of this repo and caught by
    tests/test_no_lookahead.py::TestTruncationInvariance::test_target_positions, which
    reported a violation of ~0.10 in position units. It was not caught by reading the code.
    That is the entire argument for property-based leak tests over inspection, and it is
    worth stating plainly in the write-up rather than quietly fixing.

    The causal version uses an EXPANDING quantile: the floor at time t is computed from
    volatilities observed up to t only. It is more conservative early in the sample (fewer
    observations to estimate from), which is correct -- early in the sample you genuinely
    know less.
    """
    expanding_floor = vol.expanding(min_periods=60).quantile(quantile)
    # Before min_periods is met there is no floor estimate; use the running min as a
    # fallback, which is also causal.
    fallback = vol.expanding(min_periods=1).min()
    floor = expanding_floor.fillna(fallback)
    return vol.clip(lower=floor)


def target_positions(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    lookback: int,
    vol_target: float,
    tradeable: pd.DataFrame | None = None,
    risk_free_daily: pd.Series | None = None,
) -> pd.DataFrame:
    """Volatility-scaled target positions, in units of portfolio notional.

    Position for instrument i at time t:

        pos_{i,t} = sign(trailing excess return) * (vol_target / sigma_{i,t})

    Causal: signal and sigma both use data <= t. The t -> t+1 execution lag is applied in
    the backtester (backtest.py), NOT here -- this function returns the position implied by
    information available at t, which is a different object from the position actually held
    at t. Keeping those two ideas in separate modules is deliberate: conflating them is
    exactly how the same-bar execution error gets made.

    See docs/REASONING_LOG.md ENTRY 6 for the volatility-scaling confound: a meaningful
    part of TSMOM's reported performance may come from the scaling rather than the signal,
    and the ablation in analysis/ exists to measure that.
    """
    signal = tsmom_signal(prices, lookback, risk_free_daily=risk_free_daily)
    vol = ewma_volatility(returns)
    vol_safe = floor_volatility(vol)

    positions = signal * (vol_target / vol_safe)

    if tradeable is not None:
        positions = positions.where(tradeable, 0.0)

    return positions.fillna(0.0)


def scale_to_portfolio_vol(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    target_vol: float = config.PORTFOLIO_VOL_TARGET,
    lookback: int = config.PORTFOLIO_VOL_LOOKBACK,
) -> pd.DataFrame:
    """Scale the whole portfolio to a target annualised volatility.

    Causal, and this one takes care to *stay* causal in a place where it is easy not to be.

    The naive implementation computes the portfolio return series from the positions, takes
    its rolling std, and divides. But the portfolio return at time t depends on the position
    at t, which is what we are trying to size -- and the rolling std at t would then include
    the return at t. That is circular, and the circularity leaks.

    The fix: compute the *ex-ante* portfolio volatility from positions known at t-1 and the
    return covariance estimated from data up to t-1, then apply the scalar to the position
    entered at t. Here we use the realised volatility of the unscaled strategy's returns,
    lagged, which is the simple version of the same idea.
    """
    # Unscaled portfolio returns: position at t-1 earns return at t.
    unscaled_returns = (positions.shift(1) * returns).sum(axis=1)

    realized_vol = (
        unscaled_returns.rolling(lookback, min_periods=lookback // 2).std()
        * np.sqrt(config.TRADING_DAYS_PER_YEAR)
    )

    # Lag the scalar: the vol estimate at t uses returns through t, so it cannot inform the
    # position held *at* t. Shift it forward one bar.
    scalar = (target_vol / realized_vol).shift(1)

    # Cap leverage. Without this, an unusually quiet trailing year produces an enormous
    # scalar and the backtest levers into the next crisis. This is a real failure mode of
    # naive vol targeting, not a hypothetical.
    scalar = scalar.clip(upper=3.0).fillna(0.0)

    return positions.mul(scalar, axis=0)


def rebalance_mask(index: pd.DatetimeIndex, freq: str) -> pd.Series:
    """Boolean series: True on rebalance dates.

    Args:
        index: the trading calendar
        freq: 'M' for month-end, 'W' for week-end, 'D' for daily

    Positions are only updated on rebalance dates and held constant in between. This is
    what makes turnover -- and therefore cost -- a function of rebalance frequency, which
    is why rebalance frequency is in the parameter grid.
    """
    if freq == "D":
        return pd.Series(True, index=index)

    period = index.to_period("M" if freq == "M" else "W")
    period_series = pd.Series(period, index=index)

    # A bar is a rebalance date if the NEXT bar belongs to a different period.
    #
    # Two subtleties, both learned from a failing test:
    #
    # 1. This uses `.shift(-1)` on the CALENDAR, not on any price or return. That is not
    #    look-ahead: the trading calendar is known in advance. You know on 31 January that
    #    it is the last business day of the month, because you own a calendar. You do not
    #    need tomorrow's price to know tomorrow's date.
    #
    # 2. The final bar is deliberately NOT forced to True. An earlier version did
    #    (`is_last.iloc[-1] = True`, on the reasoning that the last bar "closes" its
    #    period) and it broke truncation invariance -- on a series truncated at t, bar t is
    #    the last bar and rebalances; on the full series the same bar is a mid-month
    #    Wednesday and does not.
    #
    #    That failure was a FALSE POSITIVE for look-ahead: no future data was read,
    #    truncation merely changed which bar was last. But the line was wrong anyway, for a
    #    better reason: it rebalances on whatever day the data happens to end, which is not
    #    a trading rule. A real strategy rebalances on month-ends, not on "the day my CSV
    #    stops". Removing it fixes the invariance failure and the modelling error at once.
    #
    # Worth keeping straight: a truncation-test failure is EVIDENCE of look-ahead, not
    # proof. Diagnose before fixing. The discipline is to find the mechanism, not to
    # silence the test.
    is_last = period_series != period_series.shift(-1)
    return is_last.astype(bool)


def apply_rebalance_schedule(
    positions: pd.DataFrame,
    freq: str,
) -> pd.DataFrame:
    """Hold positions constant between rebalance dates.

    Causal: forward-fill only propagates past values forward, which is what actually
    happens when you hold a position. (A backward-fill here would be look-ahead, and would
    look almost identical in a diff.)
    """
    mask = rebalance_mask(positions.index, freq)
    # Broadcast the (T,) mask across columns explicitly. pandas 3.0 does not broadcast a
    # (T, 1) ndarray against a (T, K) frame in .where(), so build the full-shape condition.
    cond = pd.DataFrame(
        np.repeat(mask.to_numpy()[:, None], positions.shape[1], axis=1),
        index=positions.index,
        columns=positions.columns,
    )
    held = positions.where(cond)
    return held.ffill().fillna(0.0)
