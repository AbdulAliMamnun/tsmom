"""Data ingestion, with deterministic caching.

Design principle: raw data is fetched ONCE, cached to disk with a manifest recording the
pull date, and never re-fetched. This matters more than it looks.

Yahoo silently revises history. Adjusted closes change when a dividend is restated or a
split is reclassified. If you re-pull on every run, your "reproducible" backtest quietly
produces different numbers month to month, and you will never know which of your results
came from which vintage of the data. Caching the raw pull with a date stamp is what makes
the reproducibility claim in the README true rather than aspirational.

There is also a synthetic-data path (`synthetic_prices`). It exists so the engine and its
unit tests can run in an environment with no network, and -- more usefully -- so that the
leak-detection tests can run against data with KNOWN properties. A random walk has no trend
by construction; if the engine reports a Sharpe on a random walk, something is wrong with
the engine, not with the market.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config


# --------------------------------------------------------------------------------------
# Cache manifest
# --------------------------------------------------------------------------------------


@dataclass
class CacheManifest:
    """Records what was pulled, when, and from where.

    The pull date is not decoration. When someone asks "why don't your numbers match mine",
    the first question is which vintage of Yahoo's history each of you pulled.
    """

    pulled_at_utc: str
    source: str
    tickers: list[str]
    start: str
    end: str
    n_rows: int
    note: str = ""

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "CacheManifest":
        return cls(**json.loads(path.read_text()))


# --------------------------------------------------------------------------------------
# Real data path (yfinance)
# --------------------------------------------------------------------------------------


def fetch_prices(
    tickers: list[str] | None = None,
    start: str = config.DATA_START,
    end: str | None = None,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch adjusted daily closes, caching the raw pull.

    Returns a DataFrame indexed by date, one column per ticker.

    Requires `yfinance`. Run this locally, not in a sandbox -- it needs network.
    """
    tickers = tickers or config.all_tickers()
    cache_dir = cache_dir or config.DATA_RAW
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_path = cache_dir / "prices.parquet"
    manifest_path = cache_dir / "prices_manifest.json"

    if cache_path.exists() and not force_refresh:
        prices = pd.read_parquet(cache_path)
        missing = set(tickers) - set(prices.columns)
        if not missing:
            return prices[tickers]
        # Cache exists but is missing tickers -- fall through and re-pull.

    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "yfinance is required to fetch real data. `pip install yfinance`. "
            "For offline testing use synthetic_prices()."
        ) from exc

    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,      # split- and dividend-adjusted
        progress=False,
        group_by="column",
    )

    prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    prices = prices.reindex(columns=tickers)
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()

    prices.to_parquet(cache_path)
    CacheManifest(
        pulled_at_utc=datetime.now(timezone.utc).isoformat(),
        source="yfinance (auto_adjust=True)",
        tickers=tickers,
        start=start,
        end=end,
        n_rows=len(prices),
        note=(
            "Adjusted closes. Yahoo revises history silently; this cache is the vintage "
            "all results in results/ were computed from. Do not refresh without recording "
            "it in docs/00_PRE_REGISTRATION.md amendment log."
        ),
    ).save(manifest_path)

    return prices


# --------------------------------------------------------------------------------------
# Synthetic data path (offline testing, and known-property control)
# --------------------------------------------------------------------------------------


def synthetic_prices(
    tickers: list[str] | None = None,
    n_days: int = 4000,
    seed: int = config.SEED,
    with_trend: bool = False,
    trend_strength: float = 0.0,
    start: str = "2008-01-02",
) -> pd.DataFrame:
    """Generate synthetic price series with known properties.

    Two uses:

    1. Offline development and unit tests (no network needed).
    2. NEGATIVE CONTROL. With `with_trend=False` these are driftless random walks with
       stochastic volatility. There is no trend to find. If the engine reports a
       meaningfully positive Sharpe on this, the engine is broken -- and that is a test
       worth having, because it catches look-ahead that inspection misses.

    With `with_trend=True` an autocorrelated drift component is injected, so the engine
    SHOULD find signal. That is the positive control: a test suite that only ever runs on
    noise cannot distinguish "correctly finds nothing" from "incapable of finding
    anything".
    """
    tickers = tickers or config.all_tickers()
    rng = np.random.default_rng(seed)

    dates = pd.bdate_range(start=start, periods=n_days)
    out = {}

    for i, ticker in enumerate(tickers):
        t_rng = np.random.default_rng(seed + i)

        # Stochastic vol: AR(1) in log-vol, so vol clusters the way real vol does.
        log_vol = np.zeros(n_days)
        log_vol[0] = np.log(0.01)
        for t in range(1, n_days):
            log_vol[t] = 0.99 * log_vol[t - 1] + 0.01 * np.log(0.01) + 0.05 * t_rng.normal()
        vol = np.exp(log_vol)

        if with_trend:
            # AR(1) drift -- creates genuine, findable time-series momentum.
            drift = np.zeros(n_days)
            for t in range(1, n_days):
                drift[t] = 0.995 * drift[t - 1] + trend_strength * t_rng.normal()
        else:
            drift = np.zeros(n_days)

        returns = drift + vol * t_rng.standard_t(df=5, size=n_days) / np.sqrt(5 / 3)
        out[ticker] = 100.0 * np.exp(np.cumsum(returns))

    prices = pd.DataFrame(out, index=dates)

    # Stagger inception dates, because real ETFs do not all start on the same day and the
    # engine must handle ragged history without silently forward-filling a price that did
    # not exist.
    for i, ticker in enumerate(tickers):
        if i % 4 == 1:
            prices.loc[prices.index[: 250 * (i % 5)], ticker] = np.nan

    return prices


# --------------------------------------------------------------------------------------
# Derived series
# --------------------------------------------------------------------------------------


def to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple daily returns.

    Note: pct_change() on a frame with leading NaNs yields NaN for the first valid
    observation of each column, which is correct -- there is no prior price to difference
    against.
    """
    return prices.pct_change()


def tradeable_mask(prices: pd.DataFrame, min_history: int = config.MIN_HISTORY_DAYS) -> pd.DataFrame:
    """Boolean mask: True where an instrument has enough history to be traded.

    This is a look-ahead control in disguise. Without it, an instrument's first ever bar
    could be assigned a signal computed from... nothing, or worse, from a forward-filled
    value. The mask forces an instrument to earn its way into the portfolio by accumulating
    real history first.
    """
    has_price = prices.notna()
    running_count = has_price.cumsum()
    return has_price & (running_count >= min_history)


def load_ff_factors(cache_dir: Path | None = None) -> pd.DataFrame:
    """Load Ken French daily factors from cache.

    Used for the factor regression: the question "is this alpha or is it repackaged known
    factor exposure" is not optional, and the answer needs a benchmark.

    Download manually from the Ken French Data Library and place the CSV in data/raw/.
    Kept manual deliberately -- the file format changes periodically and a silent parse
    failure is worse than an explicit missing file.
    """
    cache_dir = cache_dir or config.DATA_RAW
    path = cache_dir / "ff_factors_daily.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Ken French factors not found at {path}. Download the daily "
            "Fama/French 5 Factors + Momentum from the Ken French Data Library and save "
            "the CSV there. See docs/01_DATA.md."
        )
    ff = pd.read_csv(path, index_col=0, parse_dates=True)
    return ff / 100.0  # French publishes in percent
