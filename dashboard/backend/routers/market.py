from fastapi import APIRouter
from datetime import date, timedelta
import httpx
from ..utils import get_token, token_expired
from ..config import _WATCHLIST_SYMS
from config.instruments import INSTRUMENTS as _IKEYS

router = APIRouter()

@router.get("/market")
async def get_market() -> dict:
    token, age_h = get_token()
    if not token or token_expired(age_h):
        return {}

    indices = ["NIFTY50", "BANKNIFTY", "NIFTYIT"]
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=5)).isoformat()

    async def _fetch_index(sym: str):
        ikey = _IKEYS.get(sym, "")
        if not ikey:
            return sym, {}
        key = ikey.replace("|", "%7C").replace(" ", "%20")
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            if r.status_code == 200:
                candles = r.json().get("data", {}).get("candles", [])
                if candles and len(candles) >= 2:
                    ltp = float(candles[0][4])
                    prev = float(candles[1][4])
                    ch_pct = round((ltp - prev) / prev * 100, 2) if prev else 0.0
                    return sym, {"ltp": round(ltp, 2), "change_pct": ch_pct}
                elif candles:
                    ltp = float(candles[0][4])
                    return sym, {"ltp": round(ltp, 2), "change_pct": 0.0}
        except Exception:
            pass
        return sym, {}

    import asyncio
    tasks = [_fetch_index(s) for s in indices]
    results = await asyncio.gather(*tasks)
    return {sym: data for sym, data in results if data}