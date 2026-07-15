"""Central configuration.

Everything that could be tuned lives here, in one place, so that the parameter grid
is auditable at a glance. See docs/00_PRE_REGISTRATION.md section 4: the grid is
fixed in advance and its size N feeds every multiple-testing correction.

If you add a configuration to the grid, you have changed N, and you must record it in
the amendment log in the pre-registration document. That is not bureaucracy: N is an
input to the Deflated Sharpe Ratio, and an unrecorded change to N silently invalidates
every significance claim downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
RESULTS = REPO_ROOT / "results"
FIGURES = RESULTS / "figures"
TABLES = RESULTS / "tables"

# --------------------------------------------------------------------------------------
# Reproducibility
# --------------------------------------------------------------------------------------

SEED = 20260715

# --------------------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------------------
# Selected for (a) liquidity, (b) asset-class diversification, (c) long available history.
# NOT selected for backtested performance -- see docs/00_PRE_REGISTRATION.md section 2.
#
# Honesty note (docs/REASONING_LOG.md ENTRY 3): this is a hand-picked list of ETFs that
# exist TODAY. That is itself a survivorship-selected set. For a time-series strategy the
# exposure is smaller than for a cross-sectional one (the signal is each instrument's own
# history, not a ranking against peers that have disappeared), but it is not zero. Do not
# claim this universe is survivorship-free.

UNIVERSE: dict[str, list[str]] = {
    "equity": [
        "SPY",   # US large cap
        "IWM",   # US small cap
        "QQQ",   # US tech
        "EFA",   # Developed ex-US
        "EEM",   # Emerging markets
        "EWJ",   # Japan
        "FXI",   # China
    ],
    "fixed_income": [
        "TLT",   # US 20y+ Treasury
        "IEF",   # US 7-10y Treasury
        "SHY",   # US 1-3y Treasury
        "LQD",   # US investment grade credit
        "HYG",   # US high yield credit
        "TIP",   # US TIPS
    ],
    "commodity": [
        "GLD",   # Gold
        "SLV",   # Silver
        "USO",   # Crude oil
        "UNG",   # Natural gas
        "DBA",   # Agriculture
        "DBC",   # Broad commodity
    ],
    "currency": [
        "FXE",   # Euro
        "FXY",   # Japanese yen
        "FXB",   # British pound
        "FXA",   # Australian dollar
        "FXF",   # Swiss franc
        "UUP",   # US dollar index
    ],
}


def all_tickers() -> list[str]:
    """Flat list of every ticker in the universe."""
    return [t for tickers in UNIVERSE.values() for t in tickers]


def asset_class_of(ticker: str) -> str:
    """Which asset-class sleeve a ticker belongs to."""
    for asset_class, tickers in UNIVERSE.items():
        if ticker in tickers:
            return asset_class
    raise KeyError(f"{ticker} not in universe")


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------

DATA_START = "2000-01-01"   # early bound; most ETFs start later, that is expected
BENCHMARK_TICKER = "SPY"
TRADING_DAYS_PER_YEAR = 252

# --------------------------------------------------------------------------------------
# Signal specification
# --------------------------------------------------------------------------------------
# Primary specification follows Moskowitz, Ooi & Pedersen (2012): 12-month lookback,
# 40% per-instrument annualised vol target, monthly rebalance.
#
# It is designated primary because it is THEIRS, not because it performed best. At the time
# this file was written, no configuration had been run.

VOL_HALFLIFE_DAYS = 60          # EWMA half-life for the volatility estimate
PORTFOLIO_VOL_TARGET = 0.10     # annualised, applied at portfolio level
PORTFOLIO_VOL_LOOKBACK = 252    # trailing window for portfolio vol estimate
MIN_HISTORY_DAYS = 300          # an instrument needs this much history before it trades

# Label horizon. This DEFINES the purge width (docs/REASONING_LOG.md ENTRY 10): purging is
# driven by the label's information window, not by calendar adjacency. If you change this,
# the purge changes with it.
LABEL_HORIZON_DAYS = 21

# --------------------------------------------------------------------------------------
# The parameter grid -- THIS IS N
# --------------------------------------------------------------------------------------

LOOKBACKS = [63, 126, 252]              # ~3m, ~6m, ~12m
VOL_TARGETS = [0.20, 0.40]              # per-instrument annualised
REBALANCE_FREQS = ["M", "W"]            # month-end, week-end


@dataclass(frozen=True)
class StrategyConfig:
    """A single point in the parameter grid -- i.e. one trial."""

    lookback: int
    vol_target: float
    rebalance: str

    @property
    def name(self) -> str:
        return f"lb{self.lookback}_vt{int(self.vol_target * 100)}_rb{self.rebalance}"

    @property
    def is_primary(self) -> bool:
        """The MOP (2012) specification. Designated in advance, not after the fact."""
        return (
            self.lookback == 252
            and self.vol_target == 0.40
            and self.rebalance == "M"
        )


def parameter_grid() -> list[StrategyConfig]:
    """Every configuration that will be tried. len() of this is N."""
    return [
        StrategyConfig(lookback=lb, vol_target=vt, rebalance=rb)
        for lb, vt, rb in product(LOOKBACKS, VOL_TARGETS, REBALANCE_FREQS)
    ]


def primary_config() -> StrategyConfig:
    """The pre-registered primary specification."""
    matches = [c for c in parameter_grid() if c.is_primary]
    assert len(matches) == 1, "exactly one config must be designated primary"
    return matches[0]


N_TRIALS = len(parameter_grid())  # 12

# --------------------------------------------------------------------------------------
# Transaction costs
# --------------------------------------------------------------------------------------
# Costs are reported across a RANGE, not a point estimate. A single optimistic cost
# assumption is one of the most common ways a backtest lies, and default backtester cost
# models are typically far too generous (docs/REASONING_LOG.md ENTRY 8).
#
# The headline honesty number is the BREAKEVEN cost -- the round-trip cost at which the
# edge disappears -- because it lets a reader substitute their own cost beliefs instead of
# taking ours on faith.


@dataclass(frozen=True)
class CostModel:
    """Round-trip cost assumptions, in basis points of notional traded.

    half_spread_bps: half the bid-ask spread, charged per side
    commission_bps:  broker commission, per side
    slippage_bps:    execution slippage allowance, per side
    """

    half_spread_bps: float
    commission_bps: float
    slippage_bps: float
    label: str = ""

    @property
    def per_side_bps(self) -> float:
        return self.half_spread_bps + self.commission_bps + self.slippage_bps

    @property
    def round_trip_bps(self) -> float:
        return 2.0 * self.per_side_bps


COST_SCENARIOS: list[CostModel] = [
    CostModel(0.0, 0.0, 0.0, label="zero (diagnostic only -- never the headline)"),
    CostModel(1.0, 0.5, 0.5, label="optimistic"),
    CostModel(2.5, 1.0, 1.5, label="base"),
    CostModel(5.0, 1.0, 4.0, label="pessimistic"),
    CostModel(10.0, 1.0, 9.0, label="stressed"),
]

BASE_COST = COST_SCENARIOS[2]

# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------
# Purge is driven by LABEL_HORIZON_DAYS (ENTRY 10). Embargo is a convention, tested for
# sensitivity rather than claimed as optimal (ENTRY 11).

EMBARGO_DAYS = 21
EMBARGO_SENSITIVITY = [0, 5, 21, 63]

WF_MIN_TRAIN_DAYS = 756      # ~3 years before the first out-of-sample evaluation
WF_STEP_DAYS = 63            # ~quarterly re-selection

CPCV_N_GROUPS = 6
CPCV_N_TEST_GROUPS = 2       # C(6,2) = 15 splits


@dataclass(frozen=True)
class ValidationConfig:
    embargo_days: int = EMBARGO_DAYS
    label_horizon_days: int = LABEL_HORIZON_DAYS
    wf_min_train_days: int = WF_MIN_TRAIN_DAYS
    wf_step_days: int = WF_STEP_DAYS
    cpcv_n_groups: int = CPCV_N_GROUPS
    cpcv_n_test_groups: int = CPCV_N_TEST_GROUPS


DEFAULT_VALIDATION = ValidationConfig()

# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------

DSR_CONFIDENCE = 0.95

# Effective-N estimators to compare (docs/REASONING_LOG.md ENTRY 16 -- Thread B).
# The output that matters is DSR as a FUNCTION of assumed N, with the flip point marked.
EFFECTIVE_N_METHODS = [
    "naive",              # N = 12; every config counts
    "rho_bar",            # Bailey & Lopez de Prado's own remedy
    "participation",      # (sum lambda)^2 / sum(lambda^2)
    "variance_95",        # components explaining 95% of variance
    "entropy",            # entropy-based effective rank
    "clustering",         # correlation-clustering count
]
