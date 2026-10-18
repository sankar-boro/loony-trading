"""Daily bars for many symbols, for research scripts and scheduled jobs
(pair discovery, regime fitting). Uses the Upstox data engine and its
candle cache; one bad symbol never stops the batch."""
from __future__ import annotations

import pandas as pd

from utils.logger import get_logger

logger = get_logger("history")


def make_data_engine(cfg: dict | None = None):
    """An UpstoxDataEngine with the saved token and a loaded instrument registry."""
    from config.loader import Settings
    from data_engine.upstox import InstrumentRegistry, UpstoxAuth, UpstoxDataEngine

    cfg = cfg or Settings().as_dict()
    up = cfg.get("exchanges", {}).get("upstox", {})
    auth = UpstoxAuth(api_key=up.get("api_key", ""), api_secret=up.get("api_secret", ""),
                      redirect_uri=up.get("redirect_uri", "http://localhost:3561/callback"))
    auth.load_token()
    registry = InstrumentRegistry()
    registry.load()
    return UpstoxDataEngine(auth, registry)


def fetch_daily(symbols: list[str], days: int, engine=None) -> dict[str, pd.DataFrame]:
    """{symbol: daily OHLCV} for the symbols that returned data."""
    engine = engine or make_data_engine()
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = engine.fetch_ohlcv(sym, "1d", lookback_days=days)
        except Exception as exc:
            logger.warning(f"{sym}: daily fetch failed ({exc})")
            continue
        if df is not None and not df.empty:
            out[sym] = df
    return out
