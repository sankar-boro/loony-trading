import asyncio
import json
import time
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import httpx
from ..utils import get_token, token_expired
from ..config import _WATCHLIST_SYMS
from ..services.state import get_price_cache
from config.instruments import INSTRUMENTS as _IKEYS

router = APIRouter()

_SSE_SYMS = list(_WATCHLIST_SYMS)
_SSE_INDICES = ["NSE_INDEX%7CNifty%2050", "NSE_INDEX%7CNifty%20Bank", "NSE_INDEX%7CNifty%20IT"]

async def _fetch_sse_snapshot(token: str):
    all_keys = [_IKEYS[s] for s in _SSE_SYMS if s in _IKEYS]
    all_keys += [k.replace("%7C", "|").replace("%20", " ") for k in _SSE_INDICES]
    encoded = ",".join(k.replace("|", "%7C").replace(" ", "%20") for k in all_keys)
    price_cache = get_price_cache()
    watchlist = {}
    market = {}

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={encoded}",
                                  headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code == 200:
            data = r.json().get("data", {})
            for sym in _SSE_SYMS:
                ikey = _IKEYS.get(sym, "")
                entry = data.get(ikey.replace("|", ":"), {})
                ltp = entry.get("last_price")
                if ltp:
                    prev = price_cache.get(sym, {}).get("ltp", float(ltp))
                    chg_pct = (float(ltp) - prev) / prev * 100 if prev else 0
                    price_cache[sym] = {"ltp": float(ltp), "change_pct": round(chg_pct, 2)}
            _idx_map = {_IKEYS[name]: name for name in ("NIFTY50", "BANKNIFTY", "NIFTYIT")}
            for ikey, name in _idx_map.items():
                entry = data.get(ikey.replace("|", ":"), {})
                ltp = entry.get("last_price")
                if ltp:
                    prev = price_cache.get(name, {}).get("ltp", float(ltp))
                    chg_pct = (float(ltp) - prev) / prev * 100 if prev else 0
                    price_cache[name] = {"ltp": float(ltp), "change_pct": round(chg_pct, 2)}
    except Exception:
        pass

    for sym in _SSE_SYMS:
        cached = price_cache.get(sym, {})
        watchlist[sym] = {"ltp": cached.get("ltp", 0), "change_pct": cached.get("change_pct", 0)}
    for name in ("NIFTY50", "BANKNIFTY", "NIFTYIT"):
        cached = price_cache.get(name, {})
        market[name] = {"ltp": cached.get("ltp", 0), "change_pct": cached.get("change_pct", 0)}
    return {"watchlist": watchlist, "market": market, "ts": int(time.time())}

@router.get("/stream/prices")
async def stream_prices(request: Request):
    token, age_h = get_token()
    async def generator():
        snap = await _fetch_sse_snapshot(token)
        yield f"data: {json.dumps(snap)}\n\n"
        interval = 2 if (token and not token_expired(age_h)) else 10
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(interval)
            if await request.is_disconnected():
                break
            try:
                snap = await _fetch_sse_snapshot(token)
                yield f"data: {json.dumps(snap)}\n\n"
            except Exception:
                yield f"data: {{}}\n\n"
    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})