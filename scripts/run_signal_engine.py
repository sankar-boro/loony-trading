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


def run_signal_engine(limit: int | None = None, lookback_days: int = 200,
                       timeframe: str = "1d", symbols: list[str] | None = None) -> dict:
    """Score the universe (or an explicit `symbols` list) and persist
    Signal rows. Returns a summary dict — the scheduler (Phase 11), the
    dashboard's intraday-scan endpoint, and the CLI entry point below all
    call this.

    `timeframe` lets this run against intraday bars (e.g. "15m") instead
    of daily — docs/intraday_gaps.md §5. Pick `lookback_days` to match:
    a small value goes a long way on intraday bars (e.g. 5 days of 15m
    bars is ~125 bars, already past the 50-bar minimum below), and
    Upstox's intraday historical API caps lookback much tighter than
    daily (100-200 days depending on interval, see
    data_engine/upstox/upstox_data.py's _MAX_LOOKBACK_DAYS)."""
    cfg = Settings().as_dict()

    up_cfg = cfg.get("exchanges", {}).get("upstox", {})
    auth = UpstoxAuth(
        api_key=up_cfg.get("api_key", ""),
        api_secret=up_cfg.get("api_secret", ""),
        redirect_uri=up_cfg.get("redirect_uri", "http://localhost:3561/callback"),
    )
    auth.load_token()
    registry = InstrumentRegistry()
    registry.load()
    data_engine = UpstoxDataEngine(auth, registry)

    engine = CompositeSignalEngine(cfg)

    if symbols:
        scan_symbols = [s.strip().upper() for s in symbols if s.strip()]
        unknown = [s for s in scan_symbols if s not in STOCK_UNIVERSE]
        scan_symbols = [s for s in scan_symbols if s in STOCK_UNIVERSE]
        for s in unknown:
            logger.warning(f"{s}: not in STOCK_UNIVERSE — skipping")
    else:
        scan_symbols = list(STOCK_UNIVERSE.keys())
        if limit:
            scan_symbols = scan_symbols[:limit]

    counts = {d: 0 for d in SignalDirection}
    fetched = failed = 0
    results: list[dict] = []
    errors: list[dict] = []

    with session_scope() as db:
        for symbol in scan_symbols:
            try:
                df = data_engine.fetch_ohlcv(symbol, timeframe, lookback_days=lookback_days)
            except Exception as e:
                logger.warning(f"{symbol}: fetch failed — {e}")
                failed += 1
                errors.append({"symbol": symbol, "error": str(e)})
                continue

            if df.empty or len(df) < 50:
                failed += 1
                errors.append({"symbol": symbol, "error": f"only {len(df)} bars — need 50+"})
                continue
            fetched += 1

            try:
                scored = engine.score_symbol(db, symbol, df, timeframe=timeframe)
                engine.persist(db, scored)
                db.commit()  # per-symbol commit — one bad symbol must not roll back prior ones
                counts[scored.direction] += 1
                results.append({
                    "symbol": symbol, "direction": scored.direction.value,
                    "score": scored.score, "confidence": scored.confidence,
                })
                if scored.direction != SignalDirection.NO_SIGNAL:
                    logger.info(
                        f"{symbol}: {scored.direction.value} score={scored.score} "
                        f"confidence={scored.confidence}"
                    )
            except Exception as e:
                db.rollback()
                logger.warning(f"{symbol}: scoring failed — {e}")
                failed += 1
                errors.append({"symbol": symbol, "error": str(e)})

    summary = {
        "universe": len(scan_symbols), "scored": fetched, "skipped": failed,
        "directions": {d.value: n for d, n in counts.items()},
        "timeframe": timeframe, "results": results, "errors": errors,
    }
    logger.info(
        f"Universe: {len(scan_symbols)} symbols, {fetched} scored, {failed} skipped (no data/error). "
        f"Directions: {', '.join(f'{d.value}={n}' for d, n in counts.items())}"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="cap symbols scanned")
    parser.add_argument("--lookback-days", type=int, default=200)
    parser.add_argument("--timeframe", type=str, default="1d",
                         help='bar size to score, e.g. "1d", "15m", "5m"')
    args = parser.parse_args()
    run_signal_engine(limit=args.limit, lookback_days=args.lookback_days, timeframe=args.timeframe)


if __name__ == "__main__":
    main()
