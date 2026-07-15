"""Backtest engine.

THE ONE RULE
------------
The position targeted using information at bar t is HELD from bar t+1. It earns the return
of bar t+1. It is never, under any circumstance, credited with the return of bar t.

This is enforced by a single `.shift(1)` in `run_backtest`, and verified by
tests/test_no_lookahead.py::TestExecutionLag. One line of code; the difference between a
backtest and a fantasy.

Separation of concerns: signals.py produces the position IMPLIED by information at t. This
module turns that into the position HELD at t+1 and the P&L it earns. Those are different
objects and they live in different modules deliberately -- conflating them is precisely how
the same-bar execution error gets made.

See docs/REASONING_LOG.md ENTRY 7 and ENTRY 8.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from .config import CostModel


@dataclass
class BacktestResult:
    """Everything a backtest produces. Gross and net are both retained deliberately.

    Reporting gross-only is one of the errors an interviewer flags immediately, so the
    engine makes it awkward to do by accident: net_returns is what every downstream metric
    consumes, and gross_returns exists so the two can be shown side by side.
    """

    gross_returns: pd.Series
    net_returns: pd.Series
    costs: pd.Series
    turnover: pd.Series
    positions_held: pd.DataFrame
    positions_target: pd.DataFrame
    cost_model: CostModel

    @property
    def equity_gross(self) -> pd.Series:
        return (1.0 + self.gross_returns.fillna(0.0)).cumprod()

    @property
    def equity_net(self) -> pd.Series:
        return (1.0 + self.net_returns.fillna(0.0)).cumprod()

    @property
    def annual_turnover(self) -> float:
        """Round trips per year. Drives the cost drag (ENTRY 8)."""
        n_years = len(self.turnover) / config.TRADING_DAYS_PER_YEAR
        if n_years <= 0:
            return 0.0
        return float(self.turnover.sum() / n_years / 2.0)


def compute_turnover(positions_held: pd.DataFrame) -> pd.Series:
    """Notional traded per bar, as a fraction of portfolio notional.

    Turnover at t is |position_t - position_{t-1}| summed across instruments. This is the
    quantity that costs money, and it is the quantity that makes rebalance frequency a real
    parameter rather than a cosmetic one.
    """
    delta = positions_held.diff()
    # First bar: going from nothing to the initial position is a real trade.
    delta.iloc[0] = positions_held.iloc[0]
    return delta.abs().sum(axis=1)


def run_backtest(
    prices: pd.DataFrame,
    positions_target: pd.DataFrame,
    cost_model: CostModel = config.BASE_COST,
    returns: pd.DataFrame | None = None,
) -> BacktestResult:
    """Run the backtest.

    Args:
        prices: adjusted closes
        positions_target: position implied by information at bar t (from signals.py)
        cost_model: cost assumptions
        returns: optional precomputed returns

    Returns:
        BacktestResult with gross and net series.

    THE LAG. `positions_target` is what you decided at t. `positions_held` is what you own
    at t+1. The single shift below is the whole difference. Everything downstream consumes
    positions_held.
    """
    if returns is None:
        returns = prices.pct_change()

    # ---- THE EXECUTION LAG ----------------------------------------------------------
    # Decided at t, held at t+1, earns the return of t+1.
    positions_held = positions_target.shift(1).fillna(0.0)
    # ---------------------------------------------------------------------------------

    gross_returns = (positions_held * returns).sum(axis=1)

    turnover = compute_turnover(positions_held)
    cost_per_unit_turnover = cost_model.per_side_bps / 10_000.0
    costs = turnover * cost_per_unit_turnover

    net_returns = gross_returns - costs

    return BacktestResult(
        gross_returns=gross_returns,
        net_returns=net_returns,
        costs=costs,
        turnover=turnover,
        positions_held=positions_held,
        positions_target=positions_target,
        cost_model=cost_model,
    )


def breakeven_cost_bps(
    prices: pd.DataFrame,
    positions_target: pd.DataFrame,
    returns: pd.DataFrame | None = None,
    max_bps: float = 500.0,
) -> float:
    """The per-side cost, in bps, at which the strategy's mean net return hits zero.

    This is the honest headline number (ENTRY 8). It lets a reader substitute their own
    cost beliefs instead of taking ours on faith -- "my costs are 4bp, yours breaks even at
    3bp, therefore I don't believe this" is a conversation the reader can have without
    re-running anything.

    Returns 0.0 if the strategy loses money even at zero cost.
    """
    if returns is None:
        returns = prices.pct_change()

    positions_held = positions_target.shift(1).fillna(0.0)
    gross = (positions_held * returns).sum(axis=1)
    turnover = compute_turnover(positions_held)

    mean_gross = float(gross.mean())
    mean_turnover = float(turnover.mean())

    if mean_gross <= 0:
        return 0.0
    if mean_turnover <= 0:
        return float("inf")

    breakeven_fraction = mean_gross / mean_turnover
    return min(breakeven_fraction * 10_000.0, max_bps)


def cost_sensitivity(
    prices: pd.DataFrame,
    positions_target: pd.DataFrame,
    scenarios: list[CostModel] | None = None,
    returns: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Net Sharpe across a range of cost assumptions.

    Reported as a range rather than a point because a single optimistic cost number is one
    of the most common ways a backtest lies.
    """
    from . import metrics

    scenarios = scenarios or config.COST_SCENARIOS
    rows = []
    for cm in scenarios:
        res = run_backtest(prices, positions_target, cost_model=cm, returns=returns)
        rows.append(
            {
                "scenario": cm.label,
                "per_side_bps": cm.per_side_bps,
                "round_trip_bps": cm.round_trip_bps,
                "gross_sharpe": metrics.sharpe_ratio(res.gross_returns),
                "net_sharpe": metrics.sharpe_ratio(res.net_returns),
                "annual_turnover": res.annual_turnover,
                "sharpe_drag": metrics.sharpe_ratio(res.gross_returns)
                - metrics.sharpe_ratio(res.net_returns),
            }
        )
    return pd.DataFrame(rows)


def ablation(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    lookback: int,
    vol_target: float,
    rebalance: str = "M",
    seed: int = config.SEED,
) -> pd.DataFrame:
    """Decompose performance into signal vs. volatility scaling.

    THIS IS A REQUIRED OUTPUT, NOT OPTIONAL COLOUR. See docs/REASONING_LOG.md ENTRY 6.

    There is a live argument in the literature that much of TSMOM's reported performance
    comes from the volatility scaling rather than the trend signal. The mechanism: vol
    scaling mechanically cuts exposure going into high-vol periods, and high-vol periods are
    disproportionately when large drawdowns happen. So a vol-scaled *anything* -- including
    a random-sign strategy -- can post a better Sharpe than its unscaled version.

    Four arms:
      1. vol-scaled TSMOM   -- signal + scaling (the strategy)
      2. unscaled TSMOM     -- signal, no scaling
      3. vol-scaled random  -- scaling, no signal
      4. long-only          -- neither

    If (3) is close to (1), the signal is not the source of the performance and the write-up
    must say so. Note this is a causal question in disguise: what is the treatment, and what
    is the correct control?
    """
    from . import metrics, signals

    rng = np.random.default_rng(seed)
    tradeable = prices.notna()

    # Per-instrument vol scaling, computed causally exactly as the real strategy does:
    # floor_volatility uses an EXPANDING quantile, not a full-sample one. The earlier version
    # of this function inlined `vol.quantile(0.01, axis=0)` here -- the very full-sample
    # look-ahead floor_volatility exists to prevent (see signals.py::floor_volatility).
    vol_safe = signals.floor_volatility(signals.ewma_volatility(returns))
    per_instrument_scale = vol_target / vol_safe

    sig = signals.tsmom_signal(prices, lookback)
    ones = pd.DataFrame(1.0, index=sig.index, columns=sig.columns)

    # Random signs for the "no signal" control. BUG (fixed): the previous version drew a fresh
    # sign on EVERY bar, so this arm traded ~20x more than the real signal (12,807 vs 549
    # annual turnover) -- which confounds the Sharpe comparison this ablation exists to make.
    # The docstring is explicit that signs must be resampled at the frequency the real signal
    # changes, so we draw signs and hold them between rebalance dates via the same schedule the
    # strategy rebalances on. Turnover then lands in the same ballpark as the TSMOM arm.
    random_raw = pd.DataFrame(
        rng.choice([-1.0, 1.0], size=sig.shape),
        index=sig.index,
        columns=sig.columns,
    )
    random_sign = signals.apply_rebalance_schedule(random_raw, freq=rebalance)

    # (base signal, apply per-instrument vol scaling?) -- the ONLY two things that vary between
    # arms. Everything else is the shared pipeline below.
    arm_specs = {
        "vol_scaled_tsmom": (sig, True),           # 1. signal + scaling (the strategy)
        "unscaled_tsmom": (sig, False),            # 2. signal, no per-instrument scaling
        "vol_scaled_random": (random_sign, True),  # 3. scaling, no signal
        "long_only": (ones, False),                # 4. neither
    }

    rows = []
    for name, (base, scaled) in arm_specs.items():
        pos = base * per_instrument_scale if scaled else base
        pos = pos.where(tradeable, 0.0).fillna(0.0)

        # BUG (fixed): the previous version fed these raw per-instrument positions straight to
        # run_backtest, skipping portfolio vol scaling and the rebalance schedule. Arms ran at
        # ~360% annualised vol and hit -100% drawdown -- a blown-up table, not a decomposition.
        # Every arm must go through the SAME pipeline the real strategy uses.
        pos = signals.scale_to_portfolio_vol(pos, returns)
        pos = signals.apply_rebalance_schedule(pos, freq=rebalance)

        res = run_backtest(prices, pos, cost_model=config.BASE_COST, returns=returns)

        annual_vol = float(res.net_returns.std() * np.sqrt(config.TRADING_DAYS_PER_YEAR))

        # A correctly-piped arm sits near the portfolio target. If one blows past 3x that, it
        # skipped the pipeline (Bug 1) -- fail loudly rather than print a plausible-looking
        # table built from a 300%-vol arm.
        assert annual_vol <= 3.0 * config.PORTFOLIO_VOL_TARGET, (
            f"ablation arm {name!r} ran at {annual_vol:.1%} annualised vol, over 3x the "
            f"{config.PORTFOLIO_VOL_TARGET:.0%} portfolio target -- it is not going through "
            f"scale_to_portfolio_vol / apply_rebalance_schedule correctly"
        )

        rows.append(
            {
                "arm": name,
                "gross_sharpe": metrics.sharpe_ratio(res.gross_returns),
                "net_sharpe": metrics.sharpe_ratio(res.net_returns),
                "annual_vol": annual_vol,
                "max_drawdown": metrics.max_drawdown(res.net_returns),
                "annual_turnover": res.annual_turnover,
            }
        )
    return pd.DataFrame(rows)
