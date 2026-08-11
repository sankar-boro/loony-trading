from fastapi import APIRouter
from data_engine.upstox.market_hours import is_market_open, minutes_to_close, next_market_open
from ..utils import get_token
from ..config import _STATE_FILE, _BOT_STALE
import json
import time

router = APIRouter()

@router.get("/status")
def get_status() -> dict:
    token, age_h = get_token()
    bot_running = False
    if _STATE_FILE.exists():
        try:
            s = json.loads(_STATE_FILE.read_text())
            bot_running = time.time() - s.get("saved_at", 0) < _BOT_STALE
        except Exception:
            pass
    open_ = is_market_open()
    nxt   = next_market_open()
    token_valid = bool(token) and age_h < 23
    return {
        "bot_running":      bot_running,
        "market_open":      open_,
        "mins_to_close":    minutes_to_close() if open_ else 0,
        "next_market_open": nxt.strftime("%a %d %b • %H:%M IST"),
        "token_valid":      token_valid,
        "token_age_h":      round(age_h, 1),
        # spec §41: no paid API key configured — prices/signals are
        # synthetic (data_engine/demo_ohlcv.py), never real market data.
        "demo_mode":        not token_valid,
    }

@router.get("/health")
def get_health():
    from fastapi.responses import JSONResponse
    from ..utils import get_token
    from ..config import _EQUITY_FILE, _STATE_FILE, ROOT
    token, age_h = get_token()
    checks = {}
    healthy = True

    if not token:
        checks["token"] = "missing"
        healthy = False
    elif age_h > 23:
        checks["token"] = f"expired ({age_h:.0f}h)"
        healthy = False
    else:
        checks["token"] = f"ok ({age_h:.1f}h)"

    checks["equity_data"]   = "ok" if _EQUITY_FILE.exists()  else "missing"
    checks["positions_data"] = "ok" if _STATE_FILE.exists()  else "missing"

    try:
        from strategies.meta_engine import MetaStrategyEngine
        checks["strategy_engine"] = "ok"
    except Exception as exc:
        checks["strategy_engine"] = f"error: {str(exc)[:60]}"
        healthy = False

    _ens = ROOT / "models" / "ensemble.pkl"
    checks["ml_model"] = "ok" if _ens.exists() else "not trained"

    payload = {"status": "healthy" if healthy else "degraded", "checks": checks}
    return JSONResponse(content=payload, status_code=200 if healthy else 503)