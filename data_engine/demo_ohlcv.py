"""Synthetic OHLCV generator — MarketPulse AI demo mode (spec §41).

The application must run locally without paid API keys. When no Upstox
access token is configured, `UpstoxDataEngine.fetch_ohlcv` falls back to
this module instead of hitting the live historical-candle endpoint, so
the signal engine, backtester, and dashboard all keep working end to end
on clearly-synthetic data.

Deterministic per symbol (seeded from a hash of the symbol string) so
repeated runs produce a stable-looking price history rather than a new
random walk each time — important for a demo someone might screenshot or
walk through twice.
"""
from __future__ import annotations
import zlib
from datetime import timedelta

import numpy as np
import pandas as pd

from config.instruments import STOCK_UNIVERSE
from utils.timeutils import now_utc

# Approximate real-world price anchors for the spec's mandated demo symbols
# (§42) — everything else derives a plausible anchor from its market-cap tier.
_PRICE_ANCHORS: dict[str, float] = {
    "RELIANCE": 2900.0, "HDFCBANK": 1650.0, "ICICIBANK": 1200.0, "INFY": 1800.0,
    "TCS": 4100.0, "SBIN": 800.0, "TATAMOTORS": 950.0, "BHARTIARTL": 1550.0,
    "ITC": 460.0, "LT": 3600.0, "AXISBANK": 1150.0, "KOTAKBANK": 1750.0,
    "MARUTI": 12500.0, "SUNPHARMA": 1750.0, "TATASTEEL": 145.0,
}

_TIER_RANGE = {
    "Large Cap": (400.0, 3500.0),
    "Mid Cap": (250.0, 1800.0),
    "Small Cap": (60.0, 600.0),
}


def _seed_for(symbol: str) -> int:
    return zlib.crc32(symbol.encode("utf-8")) & 0xFFFFFFFF


def _anchor_price(symbol: str) -> float:
    if symbol in _PRICE_ANCHORS:
        return _PRICE_ANCHORS[symbol]
    tier = STOCK_UNIVERSE.get(symbol, {}).get("market_cap", "Mid Cap")
    low, high = _TIER_RANGE.get(tier, _TIER_RANGE["Mid Cap"])
    rng = np.random.RandomState(_seed_for(symbol))
    return float(rng.uniform(low, high))


def generate_demo_ohlcv(symbol: str, days: int = 400) -> pd.DataFrame:
    """Generate `days` of daily synthetic OHLCV bars ending today (UTC),
    business days only, via geometric Brownian motion. Volatility is
    tier-dependent (large caps drift slower than small caps), matching
    the rough shape of real Indian equity price series without claiming
    to be one — every downstream consumer of this data must surface a
    "DEMO DATA" label rather than presenting it as real market history."""
    tier = STOCK_UNIVERSE.get(symbol, {}).get("market_cap", "Mid Cap")
    sigma_daily = {"Large Cap": 0.014, "Mid Cap": 0.020, "Small Cap": 0.028}.get(tier, 0.020)
    mu_daily = 0.0003  # mild upward drift, matches long-run equity index behaviour

    end = pd.Timestamp(now_utc()).normalize()
    dates = pd.bdate_range(end=end, periods=days, tz="UTC")
    n = len(dates)

    rng = np.random.RandomState(_seed_for(symbol))
    log_returns = rng.normal(mu_daily, sigma_daily, size=n)
    anchor = _anchor_price(symbol)
    # Anchor the *last* bar at today's realistic price and walk the GBM
    # path backwards from there, so demo data always looks "current."
    cum_fwd = np.cumsum(log_returns)
    close = anchor * np.exp(cum_fwd - cum_fwd[-1])

    daily_range = np.abs(rng.normal(0, sigma_daily * 0.6, size=n)) * close
    open_ = close * (1 + rng.normal(0, sigma_daily * 0.3, size=n))
    high = np.maximum(open_, close) + daily_range * 0.5
    low = np.minimum(open_, close) - daily_range * 0.5
    low = np.maximum(low, 0.01)

    base_volume = {"Large Cap": 3_000_000, "Mid Cap": 900_000, "Small Cap": 250_000}.get(tier, 900_000)
    volume = np.abs(rng.normal(base_volume, base_volume * 0.35, size=n))
    # Volume spikes on ~4% of days, matching real "unusual volume" events.
    spike_mask = rng.random(n) < 0.04
    volume[spike_mask] *= rng.uniform(2.0, 4.0, size=spike_mask.sum())

    df = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume.round(0),
    }, index=dates)
    df.index.name = "ts"
    return df
