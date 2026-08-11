"""
Seed a fully offline demo dataset (MarketPulse AI Phase 8 — spec §41/§42).

Runs the full offline bootstrap sequence so the dashboard works end to
end with zero paid API keys:

  1. Stock rows        — from config.instruments.STOCK_UNIVERSE (no network)
  2. Signals            — synthetic OHLCV (data_engine/demo_ohlcv.py, which
                           UpstoxDataEngine.fetch_ohlcv falls back to
                           automatically whenever no Upstox token is
                           configured) scored through the real
                           CompositeSignalEngine — same code path as live data
  3. News                — DemoNewsProvider, via the real ingestion pipeline
                           (data_engine/news/pipeline.py already falls back
                           to it when NEWS_API_KEY isn't configured)
  4. Historical events   — synthetic analogues via the existing --seed-demo
                           path in backfill_historical_events.py

Every synthetic row is traceable rather than presented as real market data
(spec §41): signal generation logs a "DEMO DATA" warning, news content is
literally tagged "[DEMO DATA]", and historical events are tagged "[DEMO]".

Safe to re-run — stock upsert is idempotent; signals/news/historical
events append, matching each underlying script's own behaviour. Intended
for a fresh, empty database: running it against a database that already
has real live signals will mix synthetic scores in for the same symbols.

Usage:
    python3 scripts/seed_demo_data.py [--symbols SYM,SYM,...] [--days N]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from config.instruments import STOCK_UNIVERSE
from config.loader import Settings
from data_engine.demo_ohlcv import generate_demo_ohlcv
from data_engine.news.pipeline import NewsIngestionPipeline
from db.base import session_scope
from db.models import SignalDirection, Stock
from signals import CompositeSignalEngine
from utils.logger import get_logger

logger = get_logger("seed_demo_data")

# spec §42's mandated demo symbols
DEFAULT_SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "TATAMOTORS",
    "BHARTIARTL", "ITC", "LT", "AXISBANK", "KOTAKBANK", "MARUTI", "SUNPHARMA",
    "TATASTEEL",
]

_HISTORICAL_EVENT_TYPES = ["earnings", "guidance", "contract_win"]


def seed_stocks(symbols: list[str]) -> None:
    with session_scope() as db:
        existing = {s.symbol for s in db.query(Stock).filter(Stock.symbol.in_(symbols)).all()}
        inserted = 0
        for symbol in symbols:
            if symbol in existing:
                continue
            info = STOCK_UNIVERSE.get(symbol)
            if not info:
                logger.warning(f"{symbol} not in STOCK_UNIVERSE — skipping")
                continue
            db.add(Stock(
                symbol=symbol, exchange="NSE_EQ", company_name=info["name"],
                isin=info["isin"], sector=info["sector"], industry=info["industry"],
                market_cap=info["market_cap"], is_active=True,
            ))
            inserted += 1
        logger.info(f"Stocks: {inserted} inserted, {len(existing)} already present")


def seed_signals(symbols: list[str], days: int) -> None:
    cfg = Settings().as_dict()
    engine = CompositeSignalEngine(cfg)
    counts = {d: 0 for d in SignalDirection}

    with session_scope() as db:
        for symbol in symbols:
            df = generate_demo_ohlcv(symbol, days=days)
            try:
                scored = engine.score_symbol(db, symbol, df)
                engine.persist(db, scored)
                db.commit()
                counts[scored.direction] += 1
            except Exception as e:
                db.rollback()
                logger.warning(f"{symbol}: demo scoring failed — {e}")

    logger.info(f"Signals: {', '.join(f'{d.value}={n}' for d, n in counts.items())}")


def seed_news() -> None:
    with session_scope() as db:
        result = NewsIngestionPipeline().run_once(db, limit=20)
        db.commit()
    logger.info(f"News: {result}")


def seed_historical_events(symbols: list[str]) -> None:
    from backfill_historical_events import seed_demo_historical_events
    with session_scope() as db:
        for event_type in _HISTORICAL_EVENT_TYPES:
            for symbol in symbols[:5]:  # keep total row volume reasonable
                seed_demo_historical_events(db, event_type, count=15, symbol=symbol)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default=None,
                         help="comma-separated symbols (default: spec §42's 15 mandated symbols)")
    parser.add_argument("--days", type=int, default=400, help="synthetic price history length")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else DEFAULT_SYMBOLS

    logger.warning("Seeding DEMO DATA — synthetic prices, signals, news, and historical events. Not real market data.")
    seed_stocks(symbols)
    seed_signals(symbols, args.days)
    seed_news()
    seed_historical_events(symbols)
    logger.info("Demo seed complete.")


if __name__ == "__main__":
    main()
