"""Factor attribution -- is the alpha real, or repackaged known factor exposure?

The primary config posts a 0.706 net Sharpe. The question that cannot be skipped: is that
alpha, or is it beta to factors anyone can buy? This module regresses the strategy's net
returns on the Fama-French factors plus momentum and reports the intercept -- the part the
factors do not explain.

UMD (momentum) is the one to watch. A time-series momentum strategy loading heavily on
CROSS-sectional momentum would be an interesting and slightly awkward result: it would mean
much of the "trend" edge is the well-known momentum factor wearing a different label.

WHY NEWEY-WEST, NOT OLS STANDARD ERRORS. Strategy returns are autocorrelated (vol clustering,
held positions). OLS standard errors assume iid residuals and therefore understate the true
standard error on autocorrelated data -- they would overstate the t-stat on alpha, which is
exactly the number under scrutiny. HAC (Newey-West) standard errors correct for the serial
correlation. Using OLS SEs here would undercut the entire point of the module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from . import config

# Canonical factor set. The momentum column is named 'UMD' in some French files and 'Mom'
# (or 'MOM') in others; both are accepted.
FACTOR_COLUMNS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "UMD"]
_MOMENTUM_ALIASES = ["UMD", "Mom", "MOM", "WML"]


@dataclass
class FactorRegressionResult:
    table: pd.DataFrame       # term -> coef, tstat, pvalue (Newey-West)
    alpha_annual: float       # annualised intercept
    alpha_tstat: float
    r_squared: float
    n_obs: int
    nw_lags: int

    @property
    def alpha_daily(self) -> float:
        return float(self.table.loc["alpha", "coef"])


def _normalise_factor_columns(ff: pd.DataFrame) -> pd.DataFrame:
    """Standardise the momentum column name to 'UMD' and keep RF if present."""
    ff = ff.copy()
    ff.columns = [str(c).strip() for c in ff.columns]
    for alias in _MOMENTUM_ALIASES:
        if alias in ff.columns and "UMD" not in ff.columns:
            ff = ff.rename(columns={alias: "UMD"})
            break
    return ff


def factor_regression(
    net_returns: pd.Series,
    ff_factors: pd.DataFrame,
    nw_lags: int = 21,
) -> FactorRegressionResult:
    """Regress net returns on the FF5 + momentum factors with Newey-West standard errors.

    The dependent variable is the strategy's EXCESS return (net minus the daily risk-free
    rate, if an 'RF' column is present) so the intercept is a genuine alpha rather than a
    number contaminated by the risk-free drift.

    Args:
        net_returns: daily net returns of the strategy
        ff_factors: Ken French daily factors (already in decimal, per data.load_ff_factors);
            expects Mkt-RF, SMB, HML, RMW, CMA and a momentum column (UMD/Mom), and
            optionally RF.
        nw_lags: Newey-West maximum lag (~21 trading days ~ 1 month).
    """
    ff = _normalise_factor_columns(ff_factors)

    missing = [f for f in FACTOR_COLUMNS if f not in ff.columns]
    if missing:
        raise ValueError(
            f"factor frame is missing columns {missing}; have {list(ff.columns)}. "
            "Need Mkt-RF, SMB, HML, RMW, CMA and a momentum column (UMD/Mom)."
        )

    df = pd.concat([net_returns.rename("strategy"), ff], axis=1, join="inner").dropna(
        subset=["strategy", *FACTOR_COLUMNS]
    )

    y = df["strategy"].astype(float)
    if "RF" in df.columns:
        y = y - df["RF"].astype(float)

    x = df[FACTOR_COLUMNS].astype(float)
    x = sm.add_constant(x)

    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lags})

    terms = ["alpha", *FACTOR_COLUMNS]
    coefs = [model.params["const"], *[model.params[f] for f in FACTOR_COLUMNS]]
    tstats = [model.tvalues["const"], *[model.tvalues[f] for f in FACTOR_COLUMNS]]
    pvals = [model.pvalues["const"], *[model.pvalues[f] for f in FACTOR_COLUMNS]]

    table = pd.DataFrame({"coef": coefs, "tstat": tstats, "pvalue": pvals}, index=terms)

    alpha_daily = float(model.params["const"])
    return FactorRegressionResult(
        table=table,
        alpha_annual=alpha_daily * config.TRADING_DAYS_PER_YEAR,
        alpha_tstat=float(model.tvalues["const"]),
        r_squared=float(model.rsquared),
        n_obs=int(model.nobs),
        nw_lags=nw_lags,
    )


def sleeve_factor_regressions(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    cfg: "config.StrategyConfig",
    ff_factors: pd.DataFrame,
    nw_lags: int = 21,
) -> pd.DataFrame:
    """Run the primary config INSIDE each asset-class sleeve and attribute it separately.

    Why this exists. The full-portfolio regression shows an enormous UMD (momentum) loading
    (t ~ 12.7). There are two very different stories for that number:

      - MECHANICAL: the loading concentrates in the equity sleeve. UMD is an equity factor,
        7 of 25 instruments are equity ETFs, and a time-series trend signal on equities will
        mechanically resemble cross-sectional equity momentum. This would be unremarkable.
      - STRUCTURAL: UMD loads across ALL four sleeves -- bonds, commodities, currencies too.
        That would be genuinely strange (there is no equity-momentum factor in the yen) and
        would suggest the regression is picking up something other than a clean factor.

    Splitting the portfolio by sleeve discriminates between the two. Each sleeve is run
    through the identical pipeline and, crucially, is SEPARATELY vol-targeted to the
    portfolio target (scale_to_portfolio_vol -> config.PORTFOLIO_VOL_TARGET), so the sleeves
    sit at the same risk and their alphas / Sharpes are directly comparable.

    Returns one row per sleeve: alpha (annualised), alpha t-stat, UMD coef, UMD t-stat,
    R^2, n_obs.
    """
    from . import data, validation

    rows = []
    for sleeve, tickers in config.UNIVERSE.items():
        cols = [t for t in tickers if t in prices.columns]
        if not cols:
            continue
        px = prices[cols]
        rets = returns[cols]
        net = validation.strategy_net_returns(px, rets, cfg)
        fr = factor_regression(net, ff_factors, nw_lags=nw_lags)
        rows.append(
            {
                "sleeve": sleeve,
                "alpha_annual": fr.alpha_annual,
                "alpha_tstat": fr.alpha_tstat,
                "umd_coef": float(fr.table.loc["UMD", "coef"]),
                "umd_tstat": float(fr.table.loc["UMD", "tstat"]),
                "r_squared": fr.r_squared,
                "n_obs": fr.n_obs,
            }
        )
    return pd.DataFrame(rows)


def alpha_lag_robustness(
    net_returns: pd.Series,
    ff_factors: pd.DataFrame,
    lags: tuple[int, ...] = (5, 21, 63, 126),
) -> pd.DataFrame:
    """Full-portfolio alpha and its t-stat across a range of Newey-West lags.

    The headline alpha is significant only at the margin (p ~ 0.0488 at lag 21 -- right on
    the 5% line). Whether it survives longer HAC lags is therefore not a detail: a longer lag
    admits more of the return autocovariance into the standard error. For positively
    autocorrelated returns that typically WIDENS the SE and pushes the t-stat down, though it
    is not guaranteed monotonic -- the sign of the added autocovariances decides. The honest
    thing is to report the whole path and let the reader see where, or whether, it crosses.

    This is NOT a search for a lag that passes. Every lag is reported. If the verdict flips
    as the lag grows, the crossing is the finding.

    Returns one row per lag: alpha (annualised, unchanged across lags -- only its SE moves),
    t-stat, p-value, passes_5pct.
    """
    rows = []
    for lag in lags:
        fr = factor_regression(net_returns, ff_factors, nw_lags=lag)
        p = float(fr.table.loc["alpha", "pvalue"])
        rows.append(
            {
                "nw_lag": lag,
                "alpha_annual": fr.alpha_annual,
                "alpha_tstat": fr.alpha_tstat,
                "p_value": p,
                "passes_5pct": bool(p < 0.05),
            }
        )
    return pd.DataFrame(rows)
