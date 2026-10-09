from fastapi import APIRouter, HTTPException
from datetime import date, timedelta
import httpx
import pandas as pd
from ..utils import get_token, token_expired
from ..config import _WATCHLIST_SYMS
from config.instruments import INSTRUMENTS as _IKEYS

router = APIRouter()

@router.get("/signals")
async def get_signals() -> list:
    token, age_h = get_token()
    if not token or token_expired(age_h):
        return []

    scan_symbols = ["RELIANCE", "TCS", "HDFCBANK", "SBIN", "AXISBANK",
                    "INFY", "ICICIBANK", "BAJFINANCE", "WIPRO", "TATAMOTORS"]

    try:
        from config.loader import Settings
        cfg = Settings().as_dict()
    except Exception:
        cfg = {
            "strategies": {"enabled": [], "weights": {}},
            "risk": {"max_risk_per_trade": 0.01, "trailing_stop_pct": 0.02},
            "execution": {"commission": 0.001, "slippage_pct": 0.001},
            "data": {"warmup_bars": 50},
        }

    try:
        from strategies.meta_engine import MetaStrategyEngine
        from feature_engine.feature_builder import FeatureBuilder
        engine = MetaStrategyEngine(cfg)
        fb = FeatureBuilder()
    except Exception as exc:
        raise HTTPException(500, f"Engine load failed: {exc}")

    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=730)).isoformat()

    signals_out = []

    async def _scan_sym(sym: str):
        ikey = _IKEYS.get(sym, "")
        if not ikey:
            return
        key = ikey.replace("|", "%7C").replace(" ", "%20")
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            if r.status_code != 200:
                return
            candles = r.json().get("data", {}).get("candles", [])
            if len(candles) < 60:
                return
            df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.set_index("ts").sort_index()
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].apply(float)
            try:
                df = fb.build(df)
            except Exception:
                pass
            if len(df) < 55:
                return
            sigs = engine.generate_signals(sym, df)
            from strategies.base import SignalType
            for s in (sigs or []):
                if s.confidence >= 0.4:
                    signals_out.append({
                        "symbol": sym, "signal": "BUY" if s.signal_type == SignalType.BUY else "SELL",
                        "strategy": s.strategy, "confidence": round(float(s.confidence), 3),
                        "price": round(float(s.price), 2), "stop_loss": round(float(s.stop_loss), 2),
                        "take_profit": round(float(s.take_profit), 2),
                        "ts": date.today().isoformat() + "T09:32:00",
                    })
        except Exception:
            pass

    import asyncio
    await asyncio.gather(*[_scan_sym(s) for s in scan_symbols])
    signals_out.sort(key=lambda x: x["confidence"], reverse=True)
    top = signals_out[:10]

    if top:
        try:
            from utils.telegram_alerts import TelegramAlerter
            alerter = TelegramAlerter()
            if alerter.enabled:
                strong = [s for s in top if s["confidence"] >= 0.65]
                if strong:
                    lines = [f"🔔 <b>Signal Scanner — {len(strong)} signal(s)</b>"]
                    for s in strong[:5]:
                        emoji = "🟢" if s["signal"] == "BUY" else "🔴"
                        lines.append(f"{emoji} {s['symbol']} {s['signal']} @ ₹{s['price']:,.2f} ({s['strategy']} · {s['confidence']:.0%})")
                    alerter.send("\n".join(lines))
        except Exception:
            pass
    return top