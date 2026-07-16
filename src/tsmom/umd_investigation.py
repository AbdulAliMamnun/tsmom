"""The UMD investigation -- machinery and numbers only.

The full-portfolio regression (Finding 8) shows UMD loading at t = 12.70; the per-sleeve
regression (Finding 9) shows it loading on ALL four sleeves, including currencies (t = 7.31),
which refutes the mechanical "it's just the equity ETFs" explanation. This module builds the
tools to interrogate that result from every angle the existing data allows.

TWO DISCIPLINES, STATED UP FRONT (STEP_7 §11 and §7):

1. This module produces TABLES, not a conclusion. Reporting "UMD became insignificant after
   controls" as a fact is fine; writing "therefore it is a regime effect" is not. No function
   here returns or prints an interpretation. The author forms the position from the numbers.

2. Every regression reports all six of (beta, t-stat, p-value, correlation, R^2, n_obs). A
   t-statistic without its R^2 is exactly what made Finding 9 look strange: t = 7.31 on ~6,641
   overlapping DAILY observations of a MONTHLY-rebalanced strategy can be large while the
   variance explained is tiny. Frequency and R^2 are reported first, deliberately.

None of the controls here can prove causality: an omitted macro variable can always be the
true driver, so the leave-one-out and macro-control tests are informative, not decisive.

All volatility-regime bucketing reuses `multiple_testing.causal_vol_regime_labels` (trailing
+ expanding, no full-sample statistic) -- the full-sample-statistic leak has already recurred
three times in this project and is assumed to be waiting to recur here.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from . import config, data, metrics, validation
from .factor_model import _normalise_factor_columns
from .multiple_testing import causal_vol_regime_labels

TRADING_DAYS = config.TRADING_DAYS_PER_YEAR
SIX_STATS = ["beta", "t_stat", "p_value", "corr", "r_squared", "n_obs"]


# --------------------------------------------------------------------------------------
# Inputs and frequency plumbing
# --------------------------------------------------------------------------------------


@dataclass
class Inputs:
    prices: pd.DataFrame
    returns: pd.DataFrame
    ff: pd.DataFrame                # normalised Ken French factors (UMD present)
    sleeve_daily: pd.DataFrame      # net daily returns per sleeve, each vol-targeted to 10%
    portfolio_daily: pd.Series      # full primary-config net daily returns
    umd_daily: pd.Series
    live_start: pd.Timestamp        # date from which every sleeve is actually trading


def sleeve_returns(
    prices: pd.DataFrame, returns: pd.DataFrame, cfg: config.StrategyConfig
) -> pd.DataFrame:
    """Net daily returns of the primary config run INSIDE each asset-class sleeve.

    Each sleeve goes through the identical pipeline and is separately vol-targeted to the
    portfolio target (`scale_to_portfolio_vol`), so the four series sit at the same risk and
    are directly comparable -- the same construction as `factor_model.sleeve_factor_regressions`.
    """
    out = {}
    for sleeve, tickers in config.UNIVERSE.items():
        cols = [t for t in tickers if t in prices.columns]
        if cols:
            out[sleeve] = validation.strategy_net_returns(prices[cols], returns[cols], cfg)
    return pd.DataFrame(out)


def first_active_date(s: pd.Series):
    """First date a series is actually trading (first non-zero, non-NaN return)."""
    nz = s[(s.notna()) & (s != 0.0)]
    return nz.index[0] if len(nz) else s.index[0]


def load_inputs(
    prices: pd.DataFrame | None = None,
    returns: pd.DataFrame | None = None,
    ff: pd.DataFrame | None = None,
    cfg: config.StrategyConfig | None = None,
) -> Inputs:
    prices = data.fetch_prices() if prices is None else prices
    returns = data.to_returns(prices) if returns is None else returns
    ff = _normalise_factor_columns(data.load_ff_factors()) if ff is None else ff
    cfg = config.primary_config() if cfg is None else cfg

    sleeve_daily = sleeve_returns(prices, returns, cfg)
    portfolio_daily = validation.strategy_net_returns(prices, returns, cfg)
    umd_daily = ff["UMD"]
    live_start = max(first_active_date(sleeve_daily[c]) for c in sleeve_daily.columns)

    return Inputs(prices, returns, ff, sleeve_daily, portfolio_daily, umd_daily, live_start)


def to_monthly(daily: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Compound simple daily returns into calendar-month returns."""
    return (1.0 + daily).resample("ME").prod() - 1.0


def align(*objs, how: str = "inner") -> pd.DataFrame:
    """Concatenate series/frames on their shared dates and drop rows with any NaN."""
    frames = [o.to_frame() if isinstance(o, pd.Series) else o for o in objs]
    return pd.concat(frames, axis=1, join=how).dropna()


def apply_window(obj, window: str, live_start):
    """Restrict a date-indexed object to one of: full / live (>= live_start) / pre (< live_start)."""
    if window == "full":
        return obj
    if window == "live":
        return obj.loc[obj.index >= live_start]
    if window == "pre":
        return obj.loc[obj.index < live_start]
    raise ValueError(f"unknown window {window!r}")


WINDOWS = ("full", "live", "pre")


# --------------------------------------------------------------------------------------
# The core regression -- all six statistics, always
# --------------------------------------------------------------------------------------


def regress(
    y: pd.Series,
    X: pd.DataFrame,
    nw_lags: int,
    ols_too: bool = False,
) -> pd.DataFrame:
    """OLS with Newey-West (HAC) errors; one row per regressor with the six statistics.

    `corr` is the simple pairwise Pearson correlation of y with that regressor; `r_squared`
    and `n_obs` are model-level (repeated across rows). For a univariate regression R^2
    equals corr^2 -- the invariant the tests check.

    Returns NaN-filled rows if the sample is too small or a series is constant, rather than
    letting statsmodels raise -- an inconclusive cell is reported as inconclusive.
    """
    df = pd.concat([y.rename("_y"), X], axis=1).dropna()
    terms = list(X.columns)
    if len(df) < max(nw_lags + 5, len(terms) + 5) or df["_y"].std() == 0 or any(
        df[t].std() == 0 for t in terms
    ):
        return pd.DataFrame(
            [{"term": t, "beta": np.nan, "t_stat": np.nan, "p_value": np.nan,
              "corr": np.nan, "r_squared": np.nan, "n_obs": int(len(df)),
              **({"ols_t": np.nan, "ols_p": np.nan} if ols_too else {})} for t in terms]
        )

    xx = sm.add_constant(df[terms])
    m = sm.OLS(df["_y"], xx).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lags})
    mo = sm.OLS(df["_y"], xx).fit() if ols_too else None

    rows = []
    for t in terms:
        row = {
            "term": t,
            "beta": float(m.params[t]),
            "t_stat": float(m.tvalues[t]),
            "p_value": float(m.pvalues[t]),
            "corr": float(np.corrcoef(df["_y"], df[t])[0, 1]),
            "r_squared": float(m.rsquared),
            "n_obs": int(m.nobs),
        }
        if ols_too:
            row["ols_t"] = float(mo.tvalues[t])
            row["ols_p"] = float(mo.pvalues[t])
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# §1 + §3  Frequency: per-sleeve UMD regressions, daily vs monthly, with R^2
# --------------------------------------------------------------------------------------


def sleeve_umd_regressions(
    inp: Inputs,
    window: str = "full",
    nw_daily: int = 21,
    nw_monthly: int = 3,
) -> pd.DataFrame:
    """Per-sleeve regression of sleeve return on UMD, at DAILY and MONTHLY frequency.

    Monthly is the correct primary frequency: it matches the monthly rebalance and the
    12-month signal horizon. The daily row exists only for the side-by-side comparison the
    frequency question demands -- a daily regression on a monthly strategy has thousands of
    overlapping, serially correlated observations and can inflate t while R^2 stays tiny.
    """
    rows = []
    daily = align(inp.sleeve_daily, inp.umd_daily.rename("UMD"))
    monthly = to_monthly(daily)
    for freq, frame, nw in (("daily", daily, nw_daily), ("monthly", monthly, nw_monthly)):
        fw = apply_window(frame, window, inp.live_start)
        for sleeve in inp.sleeve_daily.columns:
            r = regress(fw[sleeve], fw[["UMD"]], nw, ols_too=(freq == "monthly")).iloc[0].to_dict()
            r.update({"sleeve": sleeve, "freq": freq, "window": window})
            rows.append(r)
    cols = ["window", "freq", "sleeve", "beta", "t_stat", "p_value", "corr", "r_squared",
            "n_obs", "ols_t", "ols_p"]
    return pd.DataFrame(rows)[cols]


FF5_UMD = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "UMD"]


def sleeve_ff5_umd_regressions(
    inp: Inputs, window: str = "full", nw_daily: int = 21, nw_monthly: int = 3
) -> pd.DataFrame:
    """Reproduce Finding 9's per-sleeve FF5+UMD regression, daily and monthly.

    This is the MULTIVARIATE model (sleeve ~ Mkt-RF + SMB + HML + RMW + CMA + UMD); the row
    returned is the UMD coefficient's six statistics within it, plus the full-model R^2. The
    daily rows should reproduce Finding 9 (currency UMD t ~ 7.31). `corr` is the simple
    pairwise correlation of the sleeve with UMD; note the univariate UMD R^2 (see
    `sleeve_umd_regressions`) is the cleaner 'variance UMD explains' number.
    """
    daily = align(inp.sleeve_daily, inp.ff[FF5_UMD])
    monthly = to_monthly(daily)
    rows = []
    for freq, frame, nw in (("daily", daily, nw_daily), ("monthly", monthly, nw_monthly)):
        fw = apply_window(frame, window, inp.live_start)
        for sleeve in inp.sleeve_daily.columns:
            r = regress(fw[sleeve], fw[FF5_UMD], nw)
            umd = r[r["term"] == "UMD"].iloc[0].to_dict()
            umd.update({"sleeve": sleeve, "freq": freq, "window": window, "model": "FF5+UMD"})
            rows.append(umd)
    cols = ["window", "model", "freq", "sleeve", "beta", "t_stat", "p_value", "corr",
            "r_squared", "n_obs"]
    return pd.DataFrame(rows)[cols]


def full_portfolio_umd(inp: Inputs, window: str = "full") -> pd.DataFrame:
    """The headline UMD loading (Finding 8) recomputed daily vs monthly, with R^2."""
    rows = []
    daily = align(inp.portfolio_daily.rename("portfolio"), inp.umd_daily.rename("UMD"))
    monthly = to_monthly(daily)
    for freq, frame, nw in (("daily", daily, 21), ("monthly", monthly, 3)):
        fw = apply_window(frame, window, inp.live_start)
        r = regress(fw["portfolio"], fw[["UMD"]], nw, ols_too=(freq == "monthly")).iloc[0].to_dict()
        r.update({"freq": freq, "window": window})
        rows.append(r)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# §2  Data verification -- the backfill problem
# --------------------------------------------------------------------------------------


def ticker_inception(inp: Inputs) -> pd.DataFrame:
    """First valid price date, first tradeable date, and observation count per ticker.

    `first_tradeable` should trail `first_price` by ~MIN_HISTORY_DAYS (tradeable_mask requires
    accumulated history); anything earlier would mean pre-inception data leaked into trading.
    """
    tmask = data.tradeable_mask(inp.prices)
    rows = []
    for sleeve, tickers in config.UNIVERSE.items():
        for t in tickers:
            if t not in inp.prices.columns:
                continue
            col = inp.prices[t]
            fp = col.first_valid_index()
            tr = tmask[t][tmask[t]]
            rows.append({
                "sleeve": sleeve, "ticker": t,
                "first_price": fp,
                "first_tradeable": tr.index.min() if len(tr) else None,
                "n_valid_price": int(col.notna().sum()),
                "any_data_before_first_valid": bool(col.loc[:fp].iloc[:-1].notna().any()),
            })
    return pd.DataFrame(rows)


def date_alignment(inp: Inputs) -> pd.DataFrame:
    return pd.DataFrame([
        {"series": "prices", "start": inp.prices.index.min(), "end": inp.prices.index.max()},
        {"series": "ff_factors", "start": inp.ff.index.min(), "end": inp.ff.index.max()},
        {"series": "usable_overlap", "start": max(inp.prices.index.min(), inp.ff.index.min()),
         "end": min(inp.prices.index.max(), inp.ff.index.max())},
    ])


def currency_within_correlation(inp: Inputs) -> pd.DataFrame:
    """Correlation matrix of the six currency ETFs' raw daily returns.

    UUP (long US dollar) is economically the inverse of FXE/FXY/FXB (long foreign vs dollar),
    so 'six currency instruments' may be closer to 2-3 independent bets. The magnitudes here,
    not a single number, are the point.
    """
    cols = [t for t in config.UNIVERSE["currency"] if t in inp.returns.columns]
    return inp.returns[cols].dropna().corr()


# --------------------------------------------------------------------------------------
# §4  Sleeve correlation matrix (monthly)
# --------------------------------------------------------------------------------------


def sleeve_correlation_matrix(inp: Inputs, window: str = "full", freq: str = "monthly") -> pd.DataFrame:
    frame = to_monthly(inp.sleeve_daily) if freq == "monthly" else inp.sleeve_daily
    return apply_window(frame, window, inp.live_start).dropna().corr()


# --------------------------------------------------------------------------------------
# §5  Pairwise sleeve regressions (monthly)
# --------------------------------------------------------------------------------------


def pairwise_sleeve_regressions(inp: Inputs, window: str = "full", nw: int = 3) -> pd.DataFrame:
    m = apply_window(to_monthly(inp.sleeve_daily), window, inp.live_start).dropna()
    rows = []
    for a, b in combinations(inp.sleeve_daily.columns, 2):
        r = regress(m[a], m[[b]], nw).iloc[0].to_dict()
        r.update({"y": a, "x": b, "window": window})
        rows.append(r)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# §6  Leave-one-out common trend factor -- the key test
# --------------------------------------------------------------------------------------


def leave_one_out_common_trend(inp: Inputs, window: str = "full", nw: int = 3) -> pd.DataFrame:
    """sleeve ~ UMD + other_three_avg, per sleeve (monthly).

    `other_three_avg` is the equal-weight average return of the OTHER three sleeves. The
    question is whether UMD still loads once the common performance of the rest of the
    strategy is controlled for. Both coefficients are reported with all six statistics; which
    of the four possible patterns obtains is left for the reader to read off the table.
    """
    al = apply_window(
        to_monthly(align(inp.sleeve_daily, inp.umd_daily.rename("UMD"))), window, inp.live_start
    ).dropna()
    sleeves = list(inp.sleeve_daily.columns)
    rows = []
    for s in sleeves:
        others = [x for x in sleeves if x != s]
        X = pd.DataFrame({"UMD": al["UMD"], "other_three_avg": al[others].mean(axis=1)})
        for r in regress(al[s], X, nw).to_dict("records"):
            r.update({"sleeve": s, "window": window})
            rows.append(r)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# §7  Macro controls (monthly, primary frequency)
# --------------------------------------------------------------------------------------


def build_controls_monthly(inp: Inputs) -> pd.DataFrame:
    """Monthly macro controls, all from in-repo data (no external fetch).

    - MktRF          : Ken French market excess return (monthly compounded)
    - UUP            : dollar-index ETF return (monthly)   [endogenous to the currency sleeve]
    - TLT            : long-Treasury ETF return (monthly)  [endogenous to the fixed-income sleeve]
    - mkt_vol_lag    : trailing 21d std of daily Mkt-RF, LAGGED one day (causal), sampled month-end
    - credit_HYG_LQD : high-yield minus investment-grade credit return spread (monthly)
    """
    r, ff = inp.returns, inp.ff
    mkt_d = ff["Mkt-RF"].reindex(r.index)
    mkt_vol_d = mkt_d.rolling(21).std().shift(1)  # causal: uses returns strictly before t
    return pd.DataFrame({
        "MktRF": to_monthly(mkt_d),
        "UUP": to_monthly(r["UUP"]),
        "TLT": to_monthly(r["TLT"]),
        "mkt_vol_lag": mkt_vol_d.resample("ME").last(),
        "credit_HYG_LQD": to_monthly(r["HYG"]) - to_monthly(r["LQD"]),
    })


# UUP is IN the currency sleeve; TLT is IN the fixed-income sleeve. Controlling a sleeve with
# an instrument it contains is contaminated -- reported and flagged, never silently used.
_ENDOGENOUS = {("currency", "UUP"), ("fixed_income", "TLT")}


def macro_controls(inp: Inputs, window: str = "full", nw: int = 3) -> pd.DataFrame:
    """For each sleeve: UMD alone, UMD + each control, UMD + all controls (monthly).

    Reports the UMD coefficient's six statistics under each specification, plus an
    `endogenous` flag where the control is an instrument the sleeve contains.
    """
    ctrl = build_controls_monthly(inp)
    al = apply_window(
        to_monthly(align(inp.sleeve_daily, inp.umd_daily.rename("UMD"))).join(ctrl, how="inner"),
        window, inp.live_start,
    ).dropna()
    ctrl_cols = list(ctrl.columns)
    rows = []
    for sleeve in inp.sleeve_daily.columns:
        specs = [("baseline", ["UMD"])]
        specs += [(c, ["UMD", c]) for c in ctrl_cols]
        specs += [("all_joint", ["UMD"] + ctrl_cols)]
        for name, xcols in specs:
            r = regress(al[sleeve], al[xcols], nw)
            umd = r[r["term"] == "UMD"].iloc[0].to_dict()
            rows.append({
                "sleeve": sleeve, "control": name,
                "umd_beta": umd["beta"], "umd_t": umd["t_stat"], "umd_p": umd["p_value"],
                "r_squared": umd["r_squared"], "n_obs": umd["n_obs"],
                "endogenous": (sleeve, name) in _ENDOGENOUS,
                "window": window,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# §8  Tail and outlier concentration
# --------------------------------------------------------------------------------------


def _corr(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < 3 or df.iloc[:, 0].std() == 0 or df.iloc[:, 1].std() == 0:
        return float("nan"), len(df)
    return float(np.corrcoef(df.iloc[:, 0], df.iloc[:, 1])[0, 1]), len(df)


def tail_concentration(inp: Inputs, window: str = "full") -> pd.DataFrame:
    """Sleeve-vs-UMD correlation under tail conditions.

    Conditions: all months; excluding the largest 5% positive and 5% negative UMD months;
    the worst 10% of PORTFOLIO months (all monthly). Plus the high/low volatility regimes,
    computed on DAILY returns via the causal tertile labels (reused, not reimplemented).
    A full-sample correlation hides tail diversification risk -- sleeves that decouple in calm
    and couple in losses -- which is what these slices expose.
    """
    m = apply_window(
        to_monthly(align(inp.sleeve_daily, inp.umd_daily.rename("UMD"),
                         inp.portfolio_daily.rename("portfolio"))),
        window, inp.live_start,
    ).dropna()
    umd = m["UMD"]
    hi = umd <= umd.quantile(0.95)   # keep all but the top 5% positive
    lo = umd >= umd.quantile(0.05)   # keep all but the bottom 5%
    worst = m["portfolio"] <= m["portfolio"].quantile(0.10)

    # Daily vol-regime slices (causal labels on the portfolio).
    dfd = apply_window(align(inp.sleeve_daily, inp.umd_daily.rename("UMD")), window, inp.live_start)
    reg = causal_vol_regime_labels(inp.portfolio_daily).reindex(dfd.index)

    rows = []
    for sleeve in inp.sleeve_daily.columns:
        conds = {
            "all_months": m.index,
            "ex_top5pct_UMD": m.index[hi],
            "ex_bot5pct_UMD": m.index[lo],
            "worst10pct_portfolio": m.index[worst],
        }
        for name, idx in conds.items():
            c, n = _corr(m.loc[idx, sleeve], m.loc[idx, "UMD"])
            rows.append({"sleeve": sleeve, "condition": name, "freq": "monthly",
                         "corr": c, "n_obs": n, "window": window})
        for rname in ("low_vol", "mid_vol", "high_vol"):
            sel = dfd.index[reg == rname]
            c, n = _corr(dfd.loc[sel, sleeve], dfd.loc[sel, "UMD"])
            rows.append({"sleeve": sleeve, "condition": f"{rname}(daily)", "freq": "daily",
                         "corr": c, "n_obs": n, "window": window})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# §9  Stability over time
# --------------------------------------------------------------------------------------


def rolling_umd_betas(inp: Inputs, window_days: int) -> pd.DataFrame:
    """Rolling OLS beta of each sleeve on UMD (daily), window `window_days`."""
    al = align(inp.sleeve_daily, inp.umd_daily.rename("UMD"))
    umd = al["UMD"]
    out = {}
    var = umd.rolling(window_days).var()
    for sleeve in inp.sleeve_daily.columns:
        cov = al[sleeve].rolling(window_days).cov(umd)
        out[sleeve] = cov / var
    return pd.DataFrame(out, index=al.index).dropna(how="all")


def stability_by_period(inp: Inputs, nw: int = 3) -> pd.DataFrame:
    """Per-sleeve monthly UMD regression across period splits.

    Splits: first/second half; calendar eras (pre-2008 / 2008-2015 / 2016-2026); and
    backfilled (< live_start) vs live-ETF (>= live_start).
    """
    m = to_monthly(align(inp.sleeve_daily, inp.umd_daily.rename("UMD")))
    mid = m.index[len(m) // 2]
    ls = inp.live_start

    def era(idx_year_lo, idx_year_hi):
        return (m.index.year >= idx_year_lo) & (m.index.year <= idx_year_hi)

    periods = {
        "first_half": m.index < mid,
        "second_half": m.index >= mid,
        "pre_2008": era(2000, 2007),
        "2008_2015": era(2008, 2015),
        "2016_2026": era(2016, 2026),
        "backfilled(<live)": m.index < ls,
        "live_etf(>=live)": m.index >= ls,
    }
    rows = []
    for pname, mask in periods.items():
        seg = m.loc[mask]
        for sleeve in inp.sleeve_daily.columns:
            r = regress(seg[sleeve], seg[["UMD"]], nw).iloc[0].to_dict()
            r.update({"period": pname, "sleeve": sleeve})
            rows.append(r)
    return pd.DataFrame(rows)


def plot_rolling_betas(inp: Inputs, path=None):
    """Rolling 3y and 5y UMD betas per sleeve -> results/figures/umd_beta_stability.png."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = path or (config.FIGURES / "umd_beta_stability.png")
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    b3 = rolling_umd_betas(inp, 3 * TRADING_DAYS)
    b5 = rolling_umd_betas(inp, 5 * TRADING_DAYS)
    colors = {"equity": "#1f4e79", "fixed_income": "#3b7dbf", "commodity": "#d9a441",
              "currency": "#c0392b"}

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, b, title in ((axes[0], b3, "3-year rolling"), (axes[1], b5, "5-year rolling")):
        for s in inp.sleeve_daily.columns:
            ax.plot(b.index, b[s], lw=1.4, color=colors.get(s, None), label=s.replace("_", " "))
        ax.axhline(0.0, color="black", lw=0.7)
        ax.axvline(inp.live_start, color="#777777", ls=":", lw=1.0)
        ax.set_title(f"UMD beta by sleeve — {title}")
        ax.set_xlabel("year")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("rolling OLS beta on UMD (daily)")
    axes[0].legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# --------------------------------------------------------------------------------------
# §10  Economic importance
# --------------------------------------------------------------------------------------


def variance_explained(inp: Inputs, window: str = "full") -> pd.DataFrame:
    """R^2 of sleeve-on-UMD per sleeve, daily and monthly -- the economic-importance framing
    of the correlation. (This is the % of each sleeve's variance UMD accounts for.)"""
    t = sleeve_umd_regressions(inp, window=window)
    return t[["window", "freq", "sleeve", "r_squared", "corr", "n_obs"]].copy()


def umd_hedged_portfolio(inp: Inputs, window: str = "full") -> pd.DataFrame:
    """Portfolio annualised vol and max drawdown, raw vs UMD-hedged (daily).

    Hedged = residual of regressing portfolio daily returns on UMD (the beta*UMD component
    removed, the intercept and residual kept). Compares the risk that survives after the UMD
    co-movement is stripped out.
    """
    al = apply_window(align(inp.portfolio_daily.rename("p"), inp.umd_daily.rename("UMD")),
                      window, inp.live_start)
    x = sm.add_constant(al[["UMD"]])
    m = sm.OLS(al["p"], x).fit()
    hedged = al["p"] - m.params["UMD"] * al["UMD"]
    return pd.DataFrame([
        {"series": "raw_portfolio", "ann_vol": metrics.annualized_vol(al["p"]),
         "max_drawdown": metrics.max_drawdown(al["p"]), "ann_return": metrics.annualized_return(al["p"])},
        {"series": "umd_hedged", "ann_vol": metrics.annualized_vol(hedged),
         "max_drawdown": metrics.max_drawdown(hedged), "ann_return": metrics.annualized_return(hedged)},
    ])


def sleeve_drawdown_correlation(inp: Inputs, window: str = "full") -> pd.DataFrame:
    """Correlation matrix of the sleeves' drawdown paths -- do they lose money together?"""
    s = apply_window(inp.sleeve_daily, window, inp.live_start).dropna(how="all").fillna(0.0)
    dd = {}
    for c in s.columns:
        eq = (1.0 + s[c]).cumprod()
        dd[c] = eq / eq.cummax() - 1.0
    return pd.DataFrame(dd).corr()
