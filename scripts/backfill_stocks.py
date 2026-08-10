"""
Backfill db.models.Stock from config.instruments.STOCK_UNIVERSE (MarketPulse
AI Phase 0). Idempotent — upserts on symbol, safe to re-run after
config/instruments.py changes (e.g. after fetch_instruments.sh finds a
stale ISIN).

Usage:
    python3 scripts/backfill_stocks.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.base import session_scope
from db.models import Stock
from config.instruments import STOCK_UNIVERSE


def backfill() -> None:
    with session_scope() as db:
        existing = {s.symbol: s for s in db.query(Stock).all()}
        inserted = updated = 0

        for symbol, info in STOCK_UNIVERSE.items():
            stock = existing.get(symbol)
            if stock is None:
                stock = Stock(symbol=symbol, exchange="NSE_EQ")
                db.add(stock)
                inserted += 1
            else:
                updated += 1

            stock.company_name = info["name"]
            stock.isin = info["isin"]
            stock.sector = info["sector"]
            stock.industry = info["industry"]
            stock.market_cap = info["market_cap"]
            stock.is_active = True

        print(f"Stocks: {inserted} inserted, {updated} updated, {len(STOCK_UNIVERSE)} total in universe")


if __name__ == "__main__":
    backfill()
