"""Multiple-testing and effective-N machinery -- Thread B.

The DSR (metrics.py, ENTRY 14) deflates the observed Sharpe against the expected maximum of
N *independent* trials. This module confronts the load-bearing word: N. The grid has 12
configurations, but a 63-day and a 126-day lookback on the same universe are close to the
same strategy -- their return series can be 0.9+ correlated. Twelve configs are not twelve
independent bets, and the honest number of effective trials is somewhere in [1, 12].

ENTRY 16 is explicit that this module produces machinery, NOT a verdict:

  - N is a property of the *search*, not of the data. It is unobservable from outside.
  - The literature's remedy (rho_bar) assumes a single common correlation, which is false
    for a structured, clustered matrix. It is implemented here anyway, because comparing it
    against the eigenvalue methods is the point.
  - Effective-N estimation on 12 short series is ITSELF noisy. The uncertainty in N_eff must
    be reported, not just the point -- failing to do so repeats, one level up, exactly the
    error being diagnosed one level down. Hence `effective_n_uncertainty`.
  - There is no ground truth for N_eff. Nothing here validates against a known answer.

The money output is `dsr_curve`: DSR as a function of assumed N, with the flip point (the N
at which the 95% verdict crosses) interpolated -- NOT rounded, because N_eff is not an
integer and pretending otherwise hides the finding. The result shows the DSR verdict is not
a fact about the strategy but a function of an unobservable, and quantifies how sensitive it
is. Which N to believe is left to the author (ENTRY 16). This module does not decide it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from statsmodels.stats.multitest import multipletests

from . import config, metrics, validation

# --------------------------------------------------------------------------------------
# 1. Trial returns -- the input everything needs
# --------------------------------------------------------------------------------------


def trial_returns(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    configs: list[config.StrategyConfig] | None = None,
) -> pd.DataFrame:
    """Net returns of every grid config, one column per config.

    Each config runs through the identical real-strategy pipeline (no shortcuts): this is
    delegated to `validation.strategy_net_returns` so the two modules cannot drift apart.
    """
    configs = configs or config.parameter_grid()
    from . import data

    tradeable = data.tradeable_mask(prices)
    return pd.DataFrame(
        {
            cfg.name: validation.strategy_net_returns(prices, returns, cfg, tradeable)
            for cfg in configs
        }
    )


# --------------------------------------------------------------------------------------
# Correlation-matrix plumbing shared by the eigenvalue estimators
# --------------------------------------------------------------------------------------


def _active_window(trial_rets: pd.DataFrame) -> pd.DataFrame:
    """Trim the leading warm-up (rows before any config is trading) and drop NaN rows.

    The pipeline emits exact zeros during warm-up (flat, not-yet-trading). Including those
    all-zero rows would pull every pairwise correlation toward 1 and bias effective-N
    downward -- the correlation must be measured over the period the strategies are actually
    live.
    """
    nonzero = (trial_rets != 0).any(axis=1)
    if nonzero.any():
        first = nonzero.idxmax()
        trial_rets = trial_rets.loc[first:]
    return trial_rets.dropna()


def _corr(trial_rets: pd.DataFrame) -> pd.DataFrame:
    return _active_window(trial_rets).corr()


def _eigs(corr: pd.DataFrame) -> np.ndarray:
    """Eigenvalues of a correlation matrix, descending, tiny negatives clipped to 0.

    A sample correlation matrix is PSD, but floating error can produce eigenvalues like
    -1e-16 that would poison a log or a square. Clip them.
    """
    w = np.linalg.eigvalsh(np.asarray(corr, dtype=float))
    w = np.clip(w, 0.0, None)
    return np.sort(w)[::-1]


def _mean_offdiag_corr(corr: pd.DataFrame) -> float:
    c = np.asarray(corr, dtype=float)
    m = c.shape[0]
    if m < 2:
        return 0.0
    off = (c.sum() - np.trace(c)) / (m * (m - 1))
    return float(off)


def _n_clusters(corr: pd.DataFrame, threshold: float, method: str = "average") -> int:
    """Number of clusters of the trial series at a correlation-distance threshold.

    Distance d = sqrt(2(1 - rho)): identical series -> 0, uncorrelated -> sqrt(2) ~ 1.414.
    """
    c = np.asarray(corr, dtype=float)
    if c.shape[0] < 2:
        return int(c.shape[0])
    d = np.sqrt(np.clip(2.0 * (1.0 - c), 0.0, None))
    np.fill_diagonal(d, 0.0)
    condensed = squareform(d, checks=False)
    z = linkage(condensed, method=method)
    labels = fcluster(z, t=threshold, criterion="distance")
    return int(len(np.unique(labels)))


# Default clustering threshold. The threshold is arbitrary and that arbitrariness IS the
# finding (ENTRY 16) -- the honest form of this estimator is `clustering_curve`, not any
# single number. But a single number is needed for the effective-N table, so it must be a
# DEFENSIBLE and STATED one, not an accident.
#
# The earlier default of 1.0 was a bug disguised as a choice: on the real trial matrix (mean
# off-diagonal correlation ~0.71) a threshold of 1.0 sits PAST the point where every series
# collapses into one cluster, so it returned 1 with a bootstrap CI of exactly [1, 1]. That CI
# was reporting the threshold, not the data.
#
# d = sqrt(2(1 - rho)), so a threshold of 0.30 merges only series with rho > 0.955 -- i.e.
# near-perfect DUPLICATES. That is the one non-arbitrary feature of this matrix: the six
# vt20/vt40 pairs are mathematically identical (rho = 1.000, see Finding 5 / the amendment
# log), because per-instrument vol scaling cancels under scale_to_portfolio_vol. At 0.30 the
# estimator therefore returns 6 -- the true count of distinct strategies -- and its bootstrap
# CI is tight because those duplicates merge in every resample (a property of the data, not
# the threshold). Report `clustering_curve` alongside it so the threshold dependence is visible.
CLUSTER_THRESHOLD = 0.30


# --------------------------------------------------------------------------------------
# 2. Effective-N estimators
# --------------------------------------------------------------------------------------


def effective_n_naive(trial_rets: pd.DataFrame) -> float:
    """N = number of configurations. Every trial counts as independent. The upper bound."""
    return float(trial_rets.shape[1])


def effective_n_rho_bar(trial_rets: pd.DataFrame) -> float:
    """Bailey & Lopez de Prado: N_hat = rho_bar + (1 - rho_bar) * M.

    Assumes a single common correlation -- false for a structured matrix (ENTRY 16). Built
    because it is the literature's remedy and the comparison against the eigenvalue methods
    is the entire point.
    """
    corr = _corr(trial_rets)
    m = corr.shape[0]
    rho_bar = _mean_offdiag_corr(corr)
    return float(rho_bar + (1.0 - rho_bar) * m)


def effective_n_participation(trial_rets: pd.DataFrame) -> float:
    """Participation ratio of the eigenvalue spectrum: (sum lambda)^2 / sum(lambda^2)."""
    w = _eigs(_corr(trial_rets))
    denom = float((w**2).sum())
    if denom <= 0:
        return float("nan")
    return float(w.sum() ** 2 / denom)


def effective_n_variance_95(trial_rets: pd.DataFrame) -> float:
    """Number of leading eigenvalues whose cumulative variance share reaches 95%."""
    w = _eigs(_corr(trial_rets))
    total = float(w.sum())
    if total <= 0:
        return float("nan")
    share = np.cumsum(w) / total
    return float(np.searchsorted(share, 0.95) + 1)


def effective_n_entropy(trial_rets: pd.DataFrame) -> float:
    """Entropy-based effective rank: exp(-sum p_i ln p_i), p_i = lambda_i / sum(lambda)."""
    w = _eigs(_corr(trial_rets))
    total = float(w.sum())
    if total <= 0:
        return float("nan")
    p = w / total
    p = p[p > 0]
    entropy = float(-(p * np.log(p)).sum())
    return float(np.exp(entropy))


def effective_n_clustering(
    trial_rets: pd.DataFrame, threshold: float = CLUSTER_THRESHOLD
) -> float:
    """Cluster count at a correlation-distance threshold.

    The threshold is arbitrary and that is itself the finding (ENTRY 16): it imports a new
    free parameter to solve a free-parameter problem, and the count is monotone in it (see
    `clustering_curve`, which is the honest form -- prefer it over this single number).

    The default (`CLUSTER_THRESHOLD` = 0.30, i.e. merge series with rho > 0.955) is chosen to
    isolate near-perfect duplicates rather than to sit past the collapse-to-one point; on the
    real matrix it returns 6, the true count of distinct strategies. Do not read this scalar
    without also reading the curve.
    """
    return float(_n_clusters(_corr(trial_rets), threshold))


def clustering_curve(
    trial_rets: pd.DataFrame,
    thresholds: np.ndarray | None = None,
) -> pd.DataFrame:
    """Cluster count as a function of the distance threshold -- the honest form of the
    clustering estimator (ENTRY 16)."""
    if thresholds is None:
        thresholds = np.round(np.arange(0.2, 1.45, 0.1), 2)
    corr = _corr(trial_rets)
    return pd.DataFrame(
        {
            "threshold": thresholds,
            "n_clusters": [_n_clusters(corr, float(t)) for t in thresholds],
        }
    )


_ESTIMATORS = {
    "naive": effective_n_naive,
    "rho_bar": effective_n_rho_bar,
    "participation": effective_n_participation,
    "variance_95": effective_n_variance_95,
    "entropy": effective_n_entropy,
    "clustering": effective_n_clustering,
}


def _estimators_from_corr(corr: pd.DataFrame, m: int) -> dict[str, float]:
    """All effective-N estimates from a precomputed correlation matrix (used by the
    bootstrap so it computes the correlation once per replicate)."""
    w = _eigs(corr)
    total = float(w.sum())
    share = np.cumsum(w) / total if total > 0 else np.zeros_like(w)
    p = w[w > 0] / total if total > 0 else np.array([1.0])
    rho_bar = _mean_offdiag_corr(corr)
    return {
        "naive": float(m),
        "rho_bar": float(rho_bar + (1.0 - rho_bar) * m),
        "participation": float(w.sum() ** 2 / (w**2).sum()) if (w**2).sum() > 0 else float("nan"),
        "variance_95": float(np.searchsorted(share, 0.95) + 1),
        "entropy": float(np.exp(-(p * np.log(p)).sum())),
        "clustering": float(_n_clusters(corr, CLUSTER_THRESHOLD)),
    }


def all_effective_n(trial_rets: pd.DataFrame) -> pd.DataFrame:
    """Every effective-N estimate as a tidy table: method -> estimate."""
    return pd.DataFrame(
        {"method": list(_ESTIMATORS), "estimate": [f(trial_rets) for f in _ESTIMATORS.values()]}
    )


# --------------------------------------------------------------------------------------
# 3. Effective-N uncertainty -- the recursion ENTRY 16 requires
# --------------------------------------------------------------------------------------


def _stationary_bootstrap_indices(
    n: int, avg_block: float, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices (geometric block lengths, circular).

    Preserves serial correlation -- which is the whole reason an iid bootstrap is wrong
    here (STEP_5_SPEC section 8). Block starts are uniform; each subsequent step either
    continues the current block (prob 1 - 1/avg_block) or jumps to a fresh random start.
    """
    p = 1.0 / avg_block
    idx = np.empty(n, dtype=int)
    idx[0] = rng.integers(n)
    for i in range(1, n):
        if rng.random() < p:
            idx[i] = rng.integers(n)
        else:
            idx[i] = (idx[i - 1] + 1) % n
    return idx


def effective_n_uncertainty(
    trial_rets: pd.DataFrame,
    n_boot: int = 1000,
    avg_block: float = 20.0,
    seed: int = config.SEED,
) -> pd.DataFrame:
    """Point estimate plus a 95% CI per effective-N method, via stationary bootstrap.

    If the CIs are wide, that is a finding, not a failure (ENTRY 16): it is the direct
    measurement of how little a 12x12 correlation matrix from a short sample actually pins
    down the effective dimension.
    """
    active = _active_window(trial_rets)
    m = active.shape[1]
    n = active.shape[0]
    rng = np.random.default_rng(seed)

    boot = {name: np.empty(n_boot) for name in _ESTIMATORS}
    values = active.to_numpy()
    cols = list(active.columns)
    for b in range(n_boot):
        idx = _stationary_bootstrap_indices(n, avg_block, rng)
        rep = pd.DataFrame(values[idx], columns=cols)
        corr = rep.corr()
        est = _estimators_from_corr(corr, m)
        for name in _ESTIMATORS:
            boot[name][b] = est[name]

    point = {name: f(trial_rets) for name, f in _ESTIMATORS.items()}
    rows = []
    for name in _ESTIMATORS:
        samples = boot[name]
        rows.append(
            {
                "method": name,
                "point": point[name],
                "boot_mean": float(np.nanmean(samples)),
                "ci_low": float(np.nanpercentile(samples, 2.5)),
                "ci_high": float(np.nanpercentile(samples, 97.5)),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 4. DSR curve -- the money output
# --------------------------------------------------------------------------------------


@dataclass
class DSRCurveResult:
    table: pd.DataFrame     # columns: assumed_n, sr0, dsr, passes_95
    flip_point: float       # interpolated N at which DSR crosses 0.95 (see notes below)


def _interpolate_flip(table: pd.DataFrame) -> float:
    """The assumed-N at which DSR crosses 0.95, linearly interpolated.

    DSR is non-increasing in N, so the crossing is pass -> fail as N grows.
      - never passes (fails even at the smallest N): NaN
      - always passes (never crosses within the range): +inf
    """
    n = table["assumed_n"].to_numpy(dtype=float)
    d = table["dsr"].to_numpy(dtype=float)
    if d[0] < 0.95:
        return float("nan")
    for i in range(1, len(d)):
        if d[i] < 0.95 <= d[i - 1]:
            span = d[i] - d[i - 1]
            if span == 0:
                return float(n[i])
            return float(n[i - 1] + (0.95 - d[i - 1]) * (n[i] - n[i - 1]) / span)
    return float("inf")


def dsr_curve(
    returns: pd.Series,
    trial_rets: pd.DataFrame,
    n_range: np.ndarray | None = None,
) -> DSRCurveResult:
    """DSR of the primary config's returns as a function of the assumed number of trials N.

    For each N: SR0 = expected_max_sharpe(N, var(trial Sharpes)); DSR = PSR of `returns`
    against that SR0. The verdict is a function of N, an unobservable -- this curve is how
    that dependence is made explicit and quantified (ENTRY 16).
    """
    if n_range is None:
        n_range = np.arange(1.0, 13.0, 0.25)

    trial_sharpes = np.array(
        [metrics.sharpe_ratio(trial_rets[c]) for c in trial_rets.columns], dtype=float
    )
    sr_var = float(np.var(trial_sharpes, ddof=1))

    rows = []
    for n in n_range:
        n = float(n)
        # Floor SR0 at 0. It is an expected MAXIMUM of N skill-less trials and cannot be
        # negative; the Gumbel approximation in expected_max_sharpe dips slightly negative for
        # fractional N just above 1, which would otherwise make DSR non-monotone at the low
        # end of the curve. Flooring restores the monotonicity the estimand actually has.
        sr0 = max(0.0, metrics.expected_max_sharpe(n, sr_var))
        dsr = metrics.probabilistic_sharpe_ratio(returns, benchmark_sr=sr0)
        rows.append({"assumed_n": n, "sr0": sr0, "dsr": dsr, "passes_95": bool(dsr > 0.95)})

    table = pd.DataFrame(rows)
    return DSRCurveResult(table=table, flip_point=_interpolate_flip(table))


# --------------------------------------------------------------------------------------
# 5. Harvey-Liu haircuts
# --------------------------------------------------------------------------------------


def _sharpe_tstat_pvalue(sr_ann: float, n_obs: int) -> tuple[float, float]:
    """t-stat and two-sided p-value of an annualised Sharpe.

    t = SR_per_period * sqrt(T) = SR_ann * sqrt(T / periods_per_year).
    """
    t = sr_ann * np.sqrt(n_obs / config.TRADING_DAYS_PER_YEAR)
    p = 2.0 * (1.0 - stats.norm.cdf(abs(t)))
    return float(t), float(p)


def harvey_liu_haircuts(
    trial_rets: pd.DataFrame,
    primary_config_name: str,
) -> pd.DataFrame:
    """Bonferroni, Holm and BHY haircuts on the primary config's Sharpe.

    These treat the trials as INDEPENDENT, which they are not -- the same objection as the
    naive N=12 accounting (ENTRY 16). They are reported ALONGSIDE the DSR curve, not instead
    of it: three multiple-testing corrections that share the DSR's load-bearing (and here
    false) independence assumption, shown so the reader can see they agree with the naive end
    of the effective-N range rather than resolve it.

    Returns method -> adjusted p-value -> haircut Sharpe -> passes at 5%.
    """
    names = list(trial_rets.columns)
    active = _active_window(trial_rets)

    sr = {c: metrics.sharpe_ratio(active[c]) for c in names}
    n_obs = {c: int(active[c].notna().sum()) for c in names}
    pvals = np.array([_sharpe_tstat_pvalue(sr[c], n_obs[c])[1] for c in names])

    j = names.index(primary_config_name)
    t_primary, _ = _sharpe_tstat_pvalue(sr[primary_config_name], n_obs[primary_config_name])
    sr_primary = sr[primary_config_name]

    methods = {"bonferroni": "bonferroni", "holm": "holm", "BHY": "fdr_by"}

    rows = [
        {
            "method": "unadjusted",
            "adjusted_p": float(pvals[j]),
            "haircut_sharpe": float(sr_primary),
            "haircut_pct": 0.0,
            "passes_5pct": bool(pvals[j] < 0.05),
        }
    ]
    for label, sm_method in methods.items():
        adj = multipletests(pvals, alpha=0.05, method=sm_method)[1]
        p_adj = float(adj[j])
        # Haircut Sharpe: rescale by the ratio of adjusted to original t-stat (Harvey & Liu
        # 2015). t_adj recovered from the adjusted two-sided p-value. The ratio is capped at
        # 1.0 -- a haircut can only shrink a Sharpe, never inflate it -- which also keeps the
        # result finite when a still-significant p-value underflows to 0 (t_adj -> inf).
        if p_adj >= 1.0 or t_primary == 0:
            haircut_sr = 0.0
        else:
            t_adj = stats.norm.ppf(1.0 - p_adj / 2.0)
            ratio = min(1.0, max(t_adj, 0.0) / abs(t_primary))
            haircut_sr = float(sr_primary * ratio)
        rows.append(
            {
                "method": label,
                "adjusted_p": p_adj,
                "haircut_sharpe": haircut_sr,
                "haircut_pct": float(1.0 - haircut_sr / sr_primary) if sr_primary else float("nan"),
                "passes_5pct": bool(p_adj < 0.05),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 7. Sub-period and volatility-regime decomposition
# --------------------------------------------------------------------------------------
# Pre-registration 5.1: no full-sample Sharpe is the headline without this decomposition.


def _bucket_stats(name: str, dimension: str, r: pd.Series) -> dict:
    r = r.dropna()
    return {
        "dimension": dimension,
        "bucket": name,
        "n_obs": int(len(r)),
        "sharpe": metrics.sharpe_ratio(r) if len(r) > 2 else float("nan"),
        "ann_return": metrics.annualized_return(r) if len(r) else float("nan"),
        "ann_vol": metrics.annualized_vol(r) if len(r) else float("nan"),
        "max_drawdown": metrics.max_drawdown(r) if len(r) else float("nan"),
    }


def subperiod_analysis(net_returns: pd.Series) -> pd.DataFrame:
    """Performance by calendar era and by trailing volatility regime.

    Calendar eras follow Run 1: the effective diversified sample only starts ~2007 (staggered
    ETF inception), so 2000-2007 is pre-diversification and must be shown as such rather than
    blended into a single headline.

    The volatility regime is assigned CAUSALLY: trailing realised vol (known before the bar it
    labels) and EXPANDING tertile thresholds (computed from vol observed up to t only). Using
    full-sample tertiles would be look-ahead -- the same hazard as ENTRY 17 Finding 1, where a
    full-sample statistic used for bucketing quietly leaks.
    """
    r = net_returns.dropna()
    rows = []

    # --- calendar eras ---
    eras = {"2000-2007": ("2000", "2007"), "2008-2015": ("2008", "2015"), "2016-2026": ("2016", "2026")}
    for name, (lo, hi) in eras.items():
        seg = r.loc[(r.index.year >= int(lo)) & (r.index.year <= int(hi))]
        if len(seg):
            rows.append(_bucket_stats(name, "calendar", seg))

    # --- volatility regime (causal) ---
    trailing_vol = r.rolling(63, min_periods=21).std().shift(1)  # known strictly before t
    q_lo = trailing_vol.expanding(min_periods=126).quantile(1.0 / 3.0)
    q_hi = trailing_vol.expanding(min_periods=126).quantile(2.0 / 3.0)
    regime = pd.Series(index=r.index, dtype=object)
    regime[trailing_vol <= q_lo] = "low_vol"
    regime[(trailing_vol > q_lo) & (trailing_vol <= q_hi)] = "mid_vol"
    regime[trailing_vol > q_hi] = "high_vol"
    for name in ("low_vol", "mid_vol", "high_vol"):
        seg = r[regime == name]
        if len(seg):
            rows.append(_bucket_stats(name, "vol_regime", seg))

    return pd.DataFrame(rows)
