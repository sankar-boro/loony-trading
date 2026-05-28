from fastapi import APIRouter, HTTPException
from ..config import _STATE_FILE
import json

router = APIRouter()

@router.get("/positions")
def get_positions() -> dict:
    if not _STATE_FILE.exists():
        return {"positions": [], "signal_log": [], "cash": 0,
                "initial_capital": 500_000, "saved_at": 0}
    try:
        s = json.loads(_STATE_FILE.read_text())
        return {
            "positions":       s.get("positions", []),
            "signal_log":      s.get("signal_log", []),
            "cash":            s.get("cash", 0),
            "initial_capital": s.get("initial_capital", 500_000),
            "saved_at":        s.get("saved_at", 0),
        }
    except Exception as e:
        raise HTTPException(500, str(e))