from fastapi import APIRouter
from ..utils import read_jsonl, empty_daily_summary
from ..config import _DAILY_FILE
import statistics

router = APIRouter()

@router.get("/daily")
def get_daily() -> dict:
    records = read_jsonl(_DAILY_FILE)
    if not records:
        return {"days": [], "summary": empty_daily_summary()}

    total_realised  = sum(r.get("realised", 0) for r in records)
    total_trades    = sum(r.get("trades", 0)   for r in records)
    total_wins      = sum(r.get("wins", 0)     for r in records)
    avg_daily       = total_realised / len(records)
    best  = max(records, key=lambda r: r.get("realised", 0))
    worst = min(records, key=lambda r: r.get("realised", 0))

    try:
        from config.loader import Settings
        capital = Settings().get("portfolio.initial_capital") or 500_000
    except Exception:
        capital = 500_000

    daily_pnls = [r.get("realised", 0) for r in records]
    if len(daily_pnls) > 1:
        rets = [p / capital for p in daily_pnls]
        mean = statistics.mean(rets)
        std  = statistics.stdev(rets)
        sharpe = (mean / std * (252 ** 0.5)) if std else 0.0
    else:
        sharpe = 0.0

    return {
        "days": records,
        "summary": {
            "total_realised":    total_realised,
            "avg_daily":         avg_daily,
            "best_day":          best,
            "worst_day":         worst,
            "sharpe_ann":        round(sharpe, 3),
            "total_trades":      total_trades,
            "overall_win_rate":  total_wins / max(total_trades, 1) * 100,
        },
    }