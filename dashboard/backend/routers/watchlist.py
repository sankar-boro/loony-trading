from fastapi import APIRouter, HTTPException
from datetime import date, timedelta
import httpx
from ..utils import get_token, token_expired
from ..config import _WATCHLIST_SYMS
from config.instruments import INSTRUMENTS as _IKEYS

router = APIRouter()

@router.get("/watchlist")
async def get_watchlist() -> dict:
    token, age_h = get_token()
    if not token or token_expired(age_h):
        return {}

    keys = [_IKEYS[s] for s in _WATCHLIST_SYMS if s in _IKEYS]
    encoded = ",".join(k.replace("|", "%7C").replace(" ", "%20") for k in keys)

    async with httpx.AsyncClient(timeout=12) as client:
        ltp_resp = await client.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={encoded}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    ltp_data = {}
    if ltp_resp.status_code == 200:
        raw = ltp_resp.json().get("data", {})
        for sym in _WATCHLIST_SYMS:
            ikey = _IKEYS.get(sym, "")
            resp_key = ikey.replace("|", ":")
            entry = raw.get(resp_key, {})
            ltp = entry.get("last_price")
            if ltp is not None:
                ltp_data[sym] = float(ltp)

    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=5)).isoformat()

    async def _fetch_candles(sym: str):
        ikey = _IKEYS.get(sym, "")
        if not ikey:
            return sym, []
        key = ikey.replace("|", "%7C").replace(" ", "%20")
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            if r.status_code == 200:
                return sym, r.json().get("data", {}).get("candles", [])
        except Exception:
            pass
        return sym, []

    import asyncio
    candle_tasks = [_fetch_candles(s) for s in _WATCHLIST_SYMS]
    candle_results = await asyncio.gather(*candle_tasks)

    result = {}
    for sym, candles in candle_results:
        ltp = ltp_data.get(sym, 0.0)
        change = 0.0
        change_pct = 0.0
        volume = 0
        if candles and len(candles) >= 2:
            today_close = float(candles[0][4])
            yesterday_close = float(candles[1][4])
            change = round(today_close - yesterday_close, 2)
            change_pct = round((today_close - yesterday_close) / yesterday_close * 100, 2) if yesterday_close else 0.0
            volume = int(candles[0][5]) if len(candles[0]) > 5 else 0
            if ltp == 0.0:
                ltp = today_close
        elif candles:
            ltp = ltp or float(candles[0][4])
            volume = int(candles[0][5]) if len(candles[0]) > 5 else 0
        result[sym] = {"ltp": round(ltp, 2), "change": change, "change_pct": change_pct, "volume": volume}

    for sym in _WATCHLIST_SYMS:
        if sym not in result:
            result[sym] = {"ltp": 0.0, "change": 0.0, "change_pct": 0.0, "volume": 0}
    return result