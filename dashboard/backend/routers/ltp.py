from fastapi import APIRouter, Query
import httpx
from ..utils import get_token
from config.instruments import INSTRUMENTS as _IKEYS

router = APIRouter()

@router.get("/ltp")
async def get_ltp(symbols: str = Query(...)) -> dict[str, float]:
    token, age_h = get_token()
    if not token or age_h > 23:
        return {}

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    keys = [_IKEYS[s] for s in sym_list if s in _IKEYS]
    if not keys:
        return {}

    encoded = ",".join(k.replace("|", "%7C").replace(" ", "%20") for k in keys)
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={encoded}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if resp.status_code != 200:
        return {}

    data = resp.json().get("data", {})
    result = {}
    for sym in sym_list:
        ikey = _IKEYS.get(sym, "")
        resp_key = ikey.replace("|", ":")
        entry = data.get(resp_key, {})
        ltp = entry.get("last_price")
        if ltp is not None:
            result[sym] = float(ltp)
    return result