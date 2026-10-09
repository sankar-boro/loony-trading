from fastapi import APIRouter, HTTPException, Query
from datetime import date, timedelta
import httpx
from ..utils import get_token, token_expired
from config.instruments import INSTRUMENTS as _IKEYS

router = APIRouter()

@router.get("/chart/{symbol}")
async def get_chart(symbol: str, interval: str = Query("day"), days: int = Query(365, ge=1, le=730)) -> dict:
    token, age_h = get_token()
    if not token or token_expired(age_h):
        raise HTTPException(401, "Token missing or expired")

    ikey = _IKEYS.get(symbol.upper())
    if not ikey:
        raise HTTPException(404, f"Unknown symbol: {symbol}")

    key = ikey.replace("|", "%7C").replace(" ", "%20")
    to_d = date.today().isoformat()

    _INTERVAL_MAP = {
        "day":       ("day",       None,  days),
        "60minute":  ("30minute",  "60T", min(days, 30)),
        "30minute":  ("30minute",  None,  min(days, 30)),
        "15minute":  ("1minute",   "15T", min(days, 7)),
        "5minute":   ("1minute",   "5T",  min(days, 5)),
        "1minute":   ("1minute",   None,  min(days, 3)),
    }
    native_interval, resample_rule, fetch_days = _INTERVAL_MAP.get(interval, ("day", None, days))
    from_d = (date.today() - timedelta(days=fetch_days)).isoformat()

    url = f"https://api.upstox.com/v2/historical-candle/{key}/{native_interval}/{to_d}/{from_d}"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Upstox API error: {resp.text[:200]}")

    import datetime as dt
    raw = resp.json().get("data", {}).get("candles", [])
    candles = []
    for c in raw:
        try:
            ts = dt.datetime.fromisoformat(str(c[0]).replace("Z", "+00:00"))
            candles.append({"time": int(ts.timestamp()), "open": float(c[1]), "high": float(c[2]),
                            "low": float(c[3]), "close": float(c[4]), "volume": float(c[5]) if len(c) > 5 else 0})
        except Exception:
            pass
    candles.sort(key=lambda c: c["time"])

    if resample_rule and candles:
        import pandas as _pd
        df_r = _pd.DataFrame(candles).set_index(_pd.to_datetime([c["time"] for c in candles], unit="s", utc=True))
        df_r = df_r.resample(resample_rule, label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna(subset=["open"])
        candles = [{"time": int(idx.timestamp()), "open": round(row["open"],2), "high": round(row["high"],2),
                    "low": round(row["low"],2), "close": round(row["close"],2), "volume": round(row["volume"],0)}
                   for idx, row in df_r.iterrows()]
    return {"symbol": symbol, "interval": interval, "candles": candles}