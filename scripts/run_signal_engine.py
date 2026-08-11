"""
Run the composite signal engine across the stock universe and persist
results (MarketPulse AI Phase 2).

For each symbol in config.instruments.STOCK_UNIVERSE: fetch daily OHLCV
(cache-first, live Upstox fallback — same as main.py), score it, persist
the Signal (+ TradeSetup if actionable). Per-symbol failures are logged
and skipped — matches spec §61 partial-availability principle; one bad
symbol must not stop the run.

Usage:
    python3 scripts/run_signal_engine.py [--limit N] [--lookback-days N]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.instruments import STOCK_UNIVERSE
from config.loader import Settings
from data_engine.upstox import InstrumentRegistry, UpstoxAuth, UpstoxDataEngine
from db.base import session_scope
from db.models import SignalDirection
from signals import CompositeSignalEngine
from utils.logger import get_logger

logger = get_logger("run_signal_engine")


def run_signal_engine(limit: int | None = None, lookback_days: int = 200) -> dict:
    """Score the universe and persist Signal rows. Returns a summary dict —
    the scheduler (Phase 11) and the CLI entry point below both call this."""
    cfg = Settings().as_dict()

    up_cfg = cfg.get("exchanges", {}).get("upstox", {})
    auth = UpstoxAuth(
        api_key=up_cfg.get("api_key", ""),
        api_secret=up_cfg.get("api_secret", ""),
        redirect_uri=up_cfg.get("redirect_uri", "http://localhost:8888/callback"),
    )
    auth.load_token()
    registry = InstrumentRegistry()
    registry.load()
    data_engine = UpstoxDataEngine(auth, registry)

    engine = CompositeSignalEngine(cfg)

    symbols = list(STOCK_UNIVERSE.keys())
    if limit:
        symbols = symbols[:limit]

    counts = {d: 0 for d in SignalDirection}
    fetched = failed = 0

    with session_scope() as db:
        for symbol in symbols:
            try:
                df = data_engine.fetch_ohlcv(symbol, "1d", lookback_days=lookback_days)
            except Exception as e:
                logger.warning(f"{symbol}: fetch failed — {e}")
                failed += 1
                continue

            if df.empty or len(df) < 50:
                failed += 1
                continue
            fetched += 1

            try:
                scored = engine.score_symbol(db, symbol, df)
                engine.persist(db, scored)
                db.commit()  # per-symbol commit — one bad symbol must not roll back prior ones
                counts[scored.direction] += 1
                if scored.direction != SignalDirection.NO_SIGNAL:
                    logger.info(
                        f"{symbol}: {scored.direction.value} score={scored.score} "
                        f"confidence={scored.confidence}"
                    )
            except Exception as e:
                db.rollback()
                logger.warning(f"{symbol}: scoring failed — {e}")
                failed += 1

    summary = {
        "universe": len(symbols), "scored": fetched, "skipped": failed,
        "directions": {d.value: n for d, n in counts.items()},
    }
    logger.info(
        f"Universe: {len(symbols)} symbols, {fetched} scored, {failed} skipped (no data/error). "
        f"Directions: {', '.join(f'{d.value}={n}' for d, n in counts.items())}"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="cap symbols scanned")
    parser.add_argument("--lookback-days", type=int, default=200)
    args = parser.parse_args()
    run_signal_engine(limit=args.limit, lookback_days=args.lookback_days)


if __name__ == "__main__":
    main()
