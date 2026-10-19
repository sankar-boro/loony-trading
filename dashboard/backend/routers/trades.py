from fastapi import APIRouter, Query
from ..utils import read_jsonl, empty_stats
from ..config import _LIVE_LOG, _PAPER_LOG

router = APIRouter()

@router.get("/trades")
def get_trades(source: str = Query("paper", pattern="^(paper|live)$")) -> dict:
    path = _LIVE_LOG if source == "live" else _PAPER_LOG
    records = [r for r in read_jsonl(path) if "pnl" in r]

    if not records:
        return {"trades": [], "stats": empty_stats()}

    pnls    = [float(r.get("pnl", 0)) for r in records]
    wins    = [p for p in pnls if p > 0]
    losses  = [p for p in pnls if p <= 0]
    n       = len(pnls)
    avg_win  = sum(wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0.0

    return {
        "trades": records,
        "stats": {
            "total":          n,
            "wins":           len(wins),
            "losses":         len(losses),
            "win_rate":       len(wins) / n * 100,
            "total_pnl":      sum(pnls),
            "avg_win":        avg_win,
            "avg_loss":       avg_loss,
            "expectancy":     len(wins) / n * avg_win + len(losses) / n * avg_loss,
            "profit_factor":  round(pf, 3),
        },
    }

@router.get("/execution/quality")
def get_execution_quality(days: int = Query(30, ge=1, le=365),
                          mode: str | None = Query(None, pattern="^(paper|live)$")) -> dict:
    """Fill rate and slippage against the decision price, from
    logs/executions.jsonl (analytics/execution_quality.py)."""
    from analytics import execution_quality as eq
    return eq.report(eq.load(eq.EXECUTION_LOG), days=days, mode=mode)
