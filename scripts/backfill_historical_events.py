"""
Backfill db.models.HistoricalEvent (MarketPulse AI Phase 3).

Two modes:

1. Organic (default) — for StockEvents old enough that forward price data
   actually exists (>= --min-age-days, default 7 calendar days), compute
   REAL realized 1d/5d returns from historical daily bars and persist as
   HistoricalEvent. This is the production path: the analogue dataset
   grows on its own as Phase 1's news pipeline runs over time. 15m/1h
   horizons are left null — this project only has daily bars (see Phase 1
   gap notes on the broken Upstox 15-minute interval), so those horizons
   are honestly unavailable rather than fabricated.

2. Demo seed (--seed-demo TYPE --seed-count N) — generates N synthetic
   HistoricalEvent rows for one event_type with clearly-labeled synthetic
   outcomes, so the analogue engine has enough samples to demo/verify
   against before the organic path has had time to accumulate real data.
   Every row's event_description is prefixed "[DEMO]".

Usage:
    python3 scripts/backfill_historical_events.py
    python3 scripts/backfill_historical_events.py --seed-demo earnings --seed-count 40
"""
from __future__ import annotations
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import Settings
from data_engine.upstox import InstrumentRegistry, UpstoxAuth, UpstoxDataEngine
from db.base import session_scope
from db.models import HistoricalEvent, NewsEvent, Stock, StockEvent
from strategies.regime_detector import RegimeDetector
from utils.logger import get_logger

logger = get_logger("backfill_historical_events")


def _already_backfilled(db, stock_id: int, event_timestamp: datetime) -> bool:
    return (
        db.query(HistoricalEvent)
        .filter(HistoricalEvent.stock_id == stock_id, HistoricalEvent.event_timestamp == event_timestamp)
        .first()
        is not None
    )


def backfill_from_matured_stock_events(db, data_engine, cfg: dict, min_age_days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    candidates = (
        db.query(StockEvent, NewsEvent, Stock)
        .join(NewsEvent, StockEvent.event_id == NewsEvent.id)
        .join(Stock, StockEvent.stock_id == Stock.id)
        .filter(StockEvent.created_at <= cutoff)
        .all()
    )
    if not candidates:
        logger.info(f"No StockEvents older than {min_age_days}d to backfill")
        return 0

    regime_detector = RegimeDetector(cfg)
    created = 0

    for stock_event, news_event, stock in candidates:
        event_ts = stock_event.created_at
        if _already_backfilled(db, stock.id, event_ts):
            continue

        df = data_engine.fetch_ohlcv(stock.symbol, "1d", lookback_days=min_age_days + 30)
        if df.empty:
            continue

        # Last bar at/before the event, using only data available at event time (no look-ahead).
        past = df[df.index <= event_ts]
        if past.empty:
            continue
        event_idx = len(past) - 1
        price_before = float(past["close"].iloc[-1])

        price_after_1d = float(df["close"].iloc[event_idx + 1]) if len(df) > event_idx + 1 else None
        price_after_5d = float(df["close"].iloc[event_idx + 5]) if len(df) > event_idx + 5 else None
        if price_after_1d is None and price_after_5d is None:
            continue  # nothing has matured yet for this one despite the age filter

        try:
            regime = regime_detector.detect(past, symbol=stock.symbol).value
        except Exception:
            regime = None

        db.add(HistoricalEvent(
            stock_id=stock.id,
            event_type=news_event.event_type,
            event_timestamp=event_ts,
            event_description=news_event.summary,
            direction=stock_event.direction,
            regime=regime,
            price_before=price_before,
            price_after_1d=price_after_1d,
            price_after_5d=price_after_5d,
        ))
        created += 1

    db.commit()
    logger.info(f"Organic backfill: {created} HistoricalEvent rows from {len(candidates)} matured StockEvents")
    return created


def seed_demo_historical_events(db, event_type: str, count: int, symbol: str = "RELIANCE") -> int:
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if not stock:
        logger.error(f"Unknown symbol for demo seed: {symbol}")
        return 0

    rng = random.Random(42)  # deterministic — reproducible "known case" for hand-verification
    directions = ["bullish", "bearish", "neutral"]
    created = 0

    for i in range(count):
        direction = directions[i % 3]
        base_drift = {"bullish": 1.2, "bearish": -1.0, "neutral": 0.0}[direction]
        price_before = round(rng.uniform(500, 3000), 2)
        r1d = base_drift + rng.gauss(0, 1.0)
        r5d = base_drift * 2.5 + rng.gauss(0, 2.0)

        db.add(HistoricalEvent(
            stock_id=stock.id,
            event_type=event_type,
            event_timestamp=datetime.now(timezone.utc) - timedelta(days=rng.randint(30, 700)),
            event_description=f"[DEMO] synthetic {event_type} analogue #{i + 1}",
            direction=direction,
            regime=rng.choice(["trending_up", "trending_down", "ranging"]),
            price_before=price_before,
            price_after_1d=round(price_before * (1 + r1d / 100), 2),
            price_after_5d=round(price_before * (1 + r5d / 100), 2),
        ))
        created += 1

    db.commit()
    logger.info(f"Demo seed: {created} synthetic HistoricalEvent rows ({event_type}, {symbol})")
    return created


def run_organic_backfill(min_age_days: int = 7) -> int:
    """Backfill real HistoricalEvent rows from matured StockEvents. Returns
    the number created — the scheduler (Phase 11) and the CLI entry point
    below both call this."""
    cfg = Settings().as_dict()

    with session_scope() as db:
        up_cfg = cfg.get("exchanges", {}).get("upstox", {})
        auth = UpstoxAuth(
            api_key=up_cfg.get("api_key", ""), api_secret=up_cfg.get("api_secret", ""),
            redirect_uri=up_cfg.get("redirect_uri", "http://localhost:8888/callback"),
        )
        auth.load_token()
        registry = InstrumentRegistry()
        registry.load()
        data_engine = UpstoxDataEngine(auth, registry)

        return backfill_from_matured_stock_events(db, data_engine, cfg, min_age_days)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-age-days", type=int, default=7)
    parser.add_argument("--seed-demo", type=str, default=None, help="event_type to seed demo data for")
    parser.add_argument("--seed-count", type=int, default=40)
    parser.add_argument("--seed-symbol", type=str, default="RELIANCE")
    args = parser.parse_args()

    if args.seed_demo:
        cfg = Settings().as_dict()
        with session_scope() as db:
            seed_demo_historical_events(db, args.seed_demo, args.seed_count, args.seed_symbol)
        return

    run_organic_backfill(args.min_age_days)


if __name__ == "__main__":
    main()
