"""
FastAPI backend for Loony Trading Dashboard.

Dev:  uvicorn dashboard.backend.main:app --reload --port 8000
Prod: uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_STATE_FILE   = ROOT / "data" / "live_positions.json"
_EQUITY_FILE  = ROOT / "data" / "equity_curve.jsonl"
_PAPER_LOG    = ROOT / "logs" / "paper_trades.jsonl"
_LIVE_LOG     = ROOT / "logs" / "trades.jsonl"
_DAILY_FILE   = ROOT / "data" / "daily_pnl.jsonl"
_TOKEN_FILE   = ROOT / "data" / "upstox_token.json"
_DIST_DIR     = Path(__file__).parent.parent / "frontend" / "dist"

_BOT_STALE    = 300
_executor     = ThreadPoolExecutor(max_workers=2)
_bt_jobs:     dict[str, dict] = {}

app = FastAPI(title="Loony Trading API", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174",
        "http://localhost:5175", "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records


def _get_token() -> tuple[str, float]:
    env = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if _TOKEN_FILE.exists():
        try:
            d = json.loads(_TOKEN_FILE.read_text())
            file_tok = d.get("access_token", "")
            age_h = (time.time() - d.get("obtained_at", 0)) / 3600
            return (env or file_tok), age_h
        except Exception:
            pass
    return env, -1.0


def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v


_load_env()


# ── Status ─────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status() -> dict:
    from data_engine.upstox.market_hours import (
        is_market_open, minutes_to_close, next_market_open,
    )
    token, age_h = _get_token()
    bot_running = False
    if _STATE_FILE.exists():
        try:
            s = json.loads(_STATE_FILE.read_text())
            bot_running = time.time() - s.get("saved_at", 0) < _BOT_STALE
        except Exception:
            pass
    open_ = is_market_open()
    nxt   = next_market_open()
    return {
        "bot_running":      bot_running,
        "market_open":      open_,
        "mins_to_close":    minutes_to_close() if open_ else 0,
        "next_market_open": nxt.strftime("%a %d %b • %H:%M IST"),
        "token_valid":      bool(token) and age_h < 23,
        "token_age_h":      round(age_h, 1),
    }


# ── Positions ──────────────────────────────────────────────────────────────────

@app.get("/api/positions")
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


# ── Equity curve ───────────────────────────────────────────────────────────────

@app.get("/api/equity")
def get_equity() -> list[dict]:
    return _read_jsonl(_EQUITY_FILE)


# ── Trades ─────────────────────────────────────────────────────────────────────

@app.get("/api/trades")
def get_trades(source: str = Query("paper", pattern="^(paper|live)$")) -> dict:
    path    = _LIVE_LOG if source == "live" else _PAPER_LOG
    records = [r for r in _read_jsonl(path) if "pnl" in r]

    if not records:
        return {"trades": [], "stats": _empty_stats()}

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


def _empty_stats() -> dict:
    return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
            "avg_win": 0, "avg_loss": 0, "expectancy": 0, "profit_factor": 0}


# ── Daily P&L ──────────────────────────────────────────────────────────────────

@app.get("/api/daily")
def get_daily() -> dict:
    records = _read_jsonl(_DAILY_FILE)
    if not records:
        return {"days": [], "summary": _empty_daily_summary()}

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
        import statistics
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


def _empty_daily_summary() -> dict:
    return {"total_realised": 0, "avg_daily": 0, "best_day": None,
            "worst_day": None, "sharpe_ann": 0, "total_trades": 0, "overall_win_rate": 0}


# ── Config ─────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config() -> dict:
    try:
        from config.loader import Settings
        s = Settings()
        return {
            "weights":       s.get("strategies.weights") or {},
            "enabled":       s.get("strategies.enabled") or [],
            "capital":       s.get("portfolio.initial_capital") or 500_000,
            "all_strategies": [
                "ema_crossover", "rsi_mean_reversion", "bollinger_reversion",
                "macd_momentum", "breakout_atr", "supertrend", "donchian_breakout",
                "zscore_reversion", "vwap_reversion", "sr_breakout", "range_breakout",
                "rsi_momentum", "volume_momentum", "candlestick_pattern",
                "order_book_imbalance", "pair_trading", "ml_classifier",
            ],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Chart (OHLCV proxy) ────────────────────────────────────────────────────────

_IKEYS: dict[str, str] = {
    "RELIANCE":   "NSE_EQ|INE002A01018",
    "TCS":        "NSE_EQ|INE467B01029",
    "HDFCBANK":   "NSE_EQ|INE040A01034",
    "INFY":       "NSE_EQ|INE009A01021",
    "ICICIBANK":  "NSE_EQ|INE090A01021",
    "SBIN":       "NSE_EQ|INE062A01020",
    "BAJFINANCE": "NSE_EQ|INE296A01024",
    "AXISBANK":   "NSE_EQ|INE238A01034",
    "WIPRO":      "NSE_EQ|INE075A01022",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "ITC":        "NSE_EQ|INE154A01025",
    "KOTAKBANK":  "NSE_EQ|INE237A01028",
    "LT":         "NSE_EQ|INE018A01030",
    "NIFTY50":    "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "NIFTYIT":    "NSE_INDEX|Nifty IT",
}

_WATCHLIST_SYMS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BAJFINANCE", "AXISBANK", "WIPRO", "TATAMOTORS",
    "ITC", "KOTAKBANK",
]


@app.get("/api/watchlist")
async def get_watchlist() -> dict:
    """Live prices + daily change% for 12 default symbols."""
    token, age_h = _get_token()
    if not token or age_h > 23:
        return {}

    # Fetch LTP for all watchlist symbols
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

    # Fetch 2-day candles for change%
    result: dict[str, dict] = {}
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=5)).isoformat()

    async def _fetch_candles(sym: str) -> tuple[str, list]:
        ikey = _IKEYS.get(sym, "")
        if not ikey:
            return sym, []
        key = ikey.replace("|", "%7C").replace(" ", "%20")
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"
                })
            if r.status_code == 200:
                return sym, r.json().get("data", {}).get("candles", [])
        except Exception:
            pass
        return sym, []

    import asyncio as _aio
    candle_tasks = [_fetch_candles(s) for s in _WATCHLIST_SYMS]
    candle_results = await _aio.gather(*candle_tasks)

    for sym, candles in candle_results:
        ltp = ltp_data.get(sym, 0.0)
        change = 0.0
        change_pct = 0.0
        volume = 0

        if candles and len(candles) >= 2:
            # candles[0] is most recent
            today_close     = float(candles[0][4])
            yesterday_close = float(candles[1][4])
            change     = round(today_close - yesterday_close, 2)
            change_pct = round((today_close - yesterday_close) / yesterday_close * 100, 2) \
                         if yesterday_close else 0.0
            volume = int(candles[0][5]) if len(candles[0]) > 5 else 0
            if ltp == 0.0:
                ltp = today_close
        elif candles:
            ltp = ltp or float(candles[0][4])
            volume = int(candles[0][5]) if len(candles[0]) > 5 else 0

        result[sym] = {
            "ltp":        round(ltp, 2),
            "change":     change,
            "change_pct": change_pct,
            "volume":     volume,
        }

    # Fill any missing symbols with zeros
    for sym in _WATCHLIST_SYMS:
        if sym not in result:
            result[sym] = {"ltp": 0.0, "change": 0.0, "change_pct": 0.0, "volume": 0}

    return result


@app.get("/api/market")
async def get_market() -> dict:
    """Index overview: NIFTY50, BANKNIFTY, NIFTYIT."""
    token, age_h = _get_token()
    if not token or age_h > 23:
        return {}

    indices = ["NIFTY50", "BANKNIFTY", "NIFTYIT"]
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=5)).isoformat()

    async def _fetch_index(sym: str) -> tuple[str, dict]:
        ikey = _IKEYS.get(sym, "")
        if not ikey:
            return sym, {}
        key = ikey.replace("|", "%7C").replace(" ", "%20")
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"
                })
            if r.status_code == 200:
                candles = r.json().get("data", {}).get("candles", [])
                if candles and len(candles) >= 2:
                    ltp      = float(candles[0][4])
                    prev     = float(candles[1][4])
                    ch_pct   = round((ltp - prev) / prev * 100, 2) if prev else 0.0
                    return sym, {"ltp": round(ltp, 2), "change_pct": ch_pct}
                elif candles:
                    ltp = float(candles[0][4])
                    return sym, {"ltp": round(ltp, 2), "change_pct": 0.0}
        except Exception:
            pass
        return sym, {}

    import asyncio as _aio
    tasks = [_fetch_index(s) for s in indices]
    results = await _aio.gather(*tasks)
    return {sym: data for sym, data in results if data}


@app.get("/api/signals")
async def get_signals() -> list:
    """Run signal scanner on default symbols, return top 10 by confidence."""
    token, age_h = _get_token()
    if not token or age_h > 23:
        return []

    import importlib
    import pandas as pd

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
                r = await client.get(url, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"
                })
            if r.status_code != 200:
                return
            candles = r.json().get("data", {}).get("candles", [])
            if len(candles) < 60:
                return

            df = pd.DataFrame(candles,
                              columns=["ts", "open", "high", "low", "close", "volume", "oi"])
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
            for s in (sigs or []):
                if s.confidence >= 0.4:
                    from strategies.base import SignalType
                    signals_out.append({
                        "symbol":     sym,
                        "signal":     "BUY" if s.signal_type == SignalType.BUY else "SELL",
                        "strategy":   s.strategy,
                        "confidence": round(float(s.confidence), 3),
                        "price":      round(float(s.price), 2),
                        "stop_loss":  round(float(s.stop_loss), 2),
                        "take_profit": round(float(s.take_profit), 2),
                        "ts":         date.today().isoformat() + "T09:32:00",
                    })
        except Exception:
            pass

    import asyncio as _aio
    await _aio.gather(*[_scan_sym(s) for s in scan_symbols])

    signals_out.sort(key=lambda x: x["confidence"], reverse=True)
    top = signals_out[:10]

    # Push high-confidence signals (≥0.65) to Telegram asynchronously
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
                        lines.append(
                            f"{emoji} {s['symbol']} {s['signal']} @ ₹{s['price']:,.2f} "
                            f"({s['strategy']} · {s['confidence']:.0%})"
                        )
                    alerter.send("\n".join(lines))
        except Exception:
            pass

    return top


# ── Telegram test endpoint ─────────────────────────────────────────────────────

@app.get("/api/telegram/test")
def test_telegram() -> dict:
    """
    Verify Telegram connectivity.  Returns {enabled, reachable, chat_id_set}.
    Sends a test message if the bot is configured.
    """
    try:
        from utils.telegram_alerts import TelegramAlerter
        alerter = TelegramAlerter()
        enabled  = alerter.enabled
        reachable = alerter.status_check() if enabled else False
        if enabled:
            alerter.send(
                "✅ <b>Loony Trading — Telegram test</b>\n"
                "Dashboard is connected and notifications are working.",
            )
        return {
            "enabled":     enabled,
            "reachable":   reachable,
            "chat_id_set": bool(alerter.chat_id),
            "token_set":   bool(alerter.bot_token),
            "message":     "Test message sent" if enabled else
                           "Telegram disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/chart/{symbol}")
async def get_chart(
    symbol: str,
    interval: str = Query("day"),
    days: int = Query(365, ge=1, le=730),
) -> dict:
    token, age_h = _get_token()
    if not token or age_h > 23:
        raise HTTPException(401, "Token missing or expired")

    ikey = _IKEYS.get(symbol.upper())
    if not ikey:
        raise HTTPException(404, f"Unknown symbol: {symbol}")

    key = ikey.replace("|", "%7C").replace(" ", "%20")
    to_d   = date.today().isoformat()

    # Map requested interval → native Upstox interval + resample rule
    # Upstox historical supports: 1minute, 30minute, day, week, month
    _INTERVAL_MAP = {
        "day":       ("day",       None,  days),
        "60minute":  ("30minute",  "60T", min(days, 30)),
        "30minute":  ("30minute",  None,  min(days, 30)),
        "15minute":  ("1minute",   "15T", min(days, 7)),
        "5minute":   ("1minute",   "5T",  min(days, 5)),
        "1minute":   ("1minute",   None,  min(days, 3)),
    }
    native_interval, resample_rule, fetch_days = _INTERVAL_MAP.get(
        interval, ("day", None, days)
    )
    from_d = (date.today() - timedelta(days=fetch_days)).isoformat()

    url = f"https://api.upstox.com/v2/historical-candle/{key}/{native_interval}/{to_d}/{from_d}"

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Upstox API error: {resp.text[:200]}")

    import datetime as dt
    raw = resp.json().get("data", {}).get("candles", [])

    candles = []
    for c in raw:
        try:
            ts = dt.datetime.fromisoformat(str(c[0]).replace("Z", "+00:00"))
            candles.append({
                "time":   int(ts.timestamp()),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]) if len(c) > 5 else 0,
            })
        except Exception:
            pass

    candles.sort(key=lambda c: c["time"])

    # Resample if native granularity is finer than requested interval
    if resample_rule and candles:
        import pandas as _pd
        df_r = _pd.DataFrame(candles).set_index(
            _pd.to_datetime([c["time"] for c in candles], unit="s", utc=True)
        )
        df_r = df_r.resample(resample_rule, label="left", closed="left").agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
        }).dropna(subset=["open"])
        candles = [
            {
                "time":   int(idx.timestamp()),
                "open":   round(row["open"],   2),
                "high":   round(row["high"],   2),
                "low":    round(row["low"],    2),
                "close":  round(row["close"],  2),
                "volume": round(row["volume"], 0),
            }
            for idx, row in df_r.iterrows()
        ]

    return {"symbol": symbol, "interval": interval, "candles": candles}


# ── LTP proxy ──────────────────────────────────────────────────────────────────

@app.get("/api/ltp")
async def get_ltp(symbols: str = Query(...)) -> dict[str, float]:
    token, age_h = _get_token()
    if not token or age_h > 23:
        return {}

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    keys = [_IKEYS[s] for s in sym_list if s in _IKEYS]
    if not keys:
        return {}

    encoded = ",".join(k.replace("|", "%7C").replace(" ", "%20") for k in keys)
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={encoded}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    if resp.status_code != 200:
        return {}

    data = resp.json().get("data", {})
    result: dict[str, float] = {}
    for sym in sym_list:
        ikey = _IKEYS.get(sym, "")
        resp_key = ikey.replace("|", ":")
        entry = data.get(resp_key, {})
        ltp = entry.get("last_price")
        if ltp is not None:
            result[sym] = float(ltp)
    return result


# ── SSE live price stream ──────────────────────────────────────────────────────
# Streams watchlist + index prices as Server-Sent Events every 2 seconds.
# Falls back to last-known prices outside market hours (Upstox LTP returns empty
# outside 9:15–15:30 IST, so we cache the previous values).

_SSE_SYMS    = list(_WATCHLIST_SYMS)                                 # 12 equity symbols
_SSE_INDICES = ["NSE_INDEX%7CNifty%2050", "NSE_INDEX%7CNifty%20Bank",
                "NSE_INDEX%7CNifty%20IT"]
_price_cache: dict[str, dict] = {}   # last known prices for SSE fallback


async def _fetch_sse_snapshot(token: str) -> dict:
    """Fetch LTP for watchlist + indices in one call; merge with cache on miss."""
    all_keys = [_IKEYS[s] for s in _SSE_SYMS if s in _IKEYS]
    all_keys += [k.replace("%7C", "|").replace("%20", " ") for k in _SSE_INDICES]
    encoded = ",".join(k.replace("|", "%7C").replace(" ", "%20") for k in all_keys)

    watchlist: dict = {}
    market: dict = {}

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(
                f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={encoded}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        if r.status_code == 200:
            data = r.json().get("data", {})
            # Equity watchlist
            for sym in _SSE_SYMS:
                ikey = _IKEYS.get(sym, "")
                entry = data.get(ikey.replace("|", ":"), {})
                ltp = entry.get("last_price")
                if ltp:
                    prev = _price_cache.get(sym, {}).get("ltp", float(ltp))
                    chg_pct = (float(ltp) - prev) / prev * 100 if prev else 0
                    _price_cache[sym] = {"ltp": float(ltp), "change_pct": round(chg_pct, 2)}
            # Indices
            _idx_map = {
                "NSE_INDEX|Nifty 50":    "NIFTY50",
                "NSE_INDEX|Nifty Bank":  "BANKNIFTY",
                "NSE_INDEX|Nifty IT":    "NIFTYIT",
            }
            for ikey, name in _idx_map.items():
                entry = data.get(ikey.replace("|", ":"), {})
                ltp = entry.get("last_price")
                if ltp:
                    prev = _price_cache.get(name, {}).get("ltp", float(ltp))
                    chg_pct = (float(ltp) - prev) / prev * 100 if prev else 0
                    _price_cache[name] = {"ltp": float(ltp), "change_pct": round(chg_pct, 2)}
    except Exception:
        pass

    # Build output from cache (live or last-known)
    for sym in _SSE_SYMS:
        cached = _price_cache.get(sym, {})
        watchlist[sym] = {
            "ltp":        cached.get("ltp", 0),
            "change_pct": cached.get("change_pct", 0),
        }
    for name in ("NIFTY50", "BANKNIFTY", "NIFTYIT"):
        cached = _price_cache.get(name, {})
        market[name] = {
            "ltp":        cached.get("ltp", 0),
            "change_pct": cached.get("change_pct", 0),
        }

    return {"watchlist": watchlist, "market": market, "ts": int(time.time())}


@app.get("/api/stream/prices")
async def stream_prices(request: Request):
    """SSE endpoint — pushes price updates every 2 seconds."""
    token, age_h = _get_token()

    async def generator():
        # Send an initial snapshot immediately
        snap = await _fetch_sse_snapshot(token)
        yield f"data: {json.dumps(snap)}\n\n"

        interval = 2 if (token and age_h <= 23) else 10
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

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Backtest ───────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol:   str
    strategy: str
    days:     int = 365
    capital:  float = 500_000


def _run_backtest_sync(job_id: str, req: BacktestRequest) -> None:
    """Runs in a thread pool — blocking is fine here."""
    _bt_jobs[job_id]["status"] = "running"
    try:
        token, age_h = _get_token()
        if not token or age_h > 23:
            raise ValueError("Token missing or expired")

        import requests as req_lib
        import pandas as pd

        ikey = _IKEYS.get(req.symbol.upper())
        if not ikey:
            raise ValueError(f"Unknown symbol: {req.symbol}")

        key    = ikey.replace("|", "%7C").replace(" ", "%20")
        to_d   = date.today().isoformat()
        from_d = (date.today() - timedelta(days=req.days)).isoformat()
        url    = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"

        r = req_lib.get(url, headers={"Authorization": f"Bearer {token}",
                                       "Accept": "application/json"}, timeout=15)
        if r.status_code != 200:
            raise ValueError(f"Data fetch failed: HTTP {r.status_code}")

        candles = r.json().get("data", {}).get("candles", [])
        if len(candles) < 60:
            raise ValueError(f"Only {len(candles)} candles — need 60+")

        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.set_index("ts").sort_index()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])

        try:
            from feature_engine.feature_builder import FeatureBuilder
            df = FeatureBuilder().build(df)
        except Exception:
            pass

        from config.loader import Settings
        cfg = Settings().as_dict()
        cfg.setdefault("data", {})["warmup_bars"] = 50

        _STRAT_MAP: dict[str, tuple[str, str]] = {
            "ema_crossover":       ("strategies.trend",          "EmaCrossoverStrategy"),
            "rsi_mean_reversion":  ("strategies.mean_reversion", "RsiReversionStrategy"),
            "bollinger_reversion": ("strategies.mean_reversion", "BollingerReversionStrategy"),
            "zscore_reversion":    ("strategies.mean_reversion", "ZscoreReversionStrategy"),
            "vwap_reversion":      ("strategies.mean_reversion", "VwapReversionStrategy"),
            "macd_momentum":       ("strategies.momentum",       "MacdMomentumStrategy"),
            "rsi_momentum":        ("strategies.momentum",       "RsiMomentumStrategy"),
            "volume_momentum":     ("strategies.momentum",       "VolumeMomentumStrategy"),
            "breakout_atr":        ("strategies.breakout",       "AtrBreakoutStrategy"),
            "sr_breakout":         ("strategies.breakout",       "SupportResistanceBreakoutStrategy"),
            "range_breakout":      ("strategies.breakout",       "RangeBreakoutStrategy"),
            "supertrend":          ("strategies.trend",          "SupertrendStrategy"),
            "donchian_breakout":   ("strategies.trend",          "DonchianBreakoutStrategy"),
            "candlestick_pattern": ("strategies.candlestick",    "CandlestickPatternStrategy"),
        }

        strat_obj = None
        if req.strategy in _STRAT_MAP:
            import importlib
            mod_name, cls_name = _STRAT_MAP[req.strategy]
            strat_obj = getattr(importlib.import_module(mod_name), cls_name)(cfg)

        from backtester.backtester import Backtester
        bt     = Backtester(cfg, initial_capital=req.capital, product="CNC")
        result = bt.run(df, req.symbol, strategy=strat_obj)
        m      = result.metrics

        _bt_jobs[job_id]["status"] = "done"
        _bt_jobs[job_id]["result"] = {
            "symbol":           req.symbol,
            "strategy":         req.strategy,
            "n_trades":         m.get("n_trades", 0),
            "win_rate":         m.get("win_rate", 0),
            "total_return_pct": m.get("total_return_pct", 0),
            "sharpe":           m.get("sharpe", 0),
            "max_drawdown_pct": m.get("max_drawdown_pct", 0),
            "profit_factor":    m.get("profit_factor", 0),
            "equity_curve":     result.equity_curve.tolist(),
            "trades_pnl":       [t.pnl for t in result.trades],
        }
    except Exception as exc:
        _bt_jobs[job_id]["status"] = "error"
        _bt_jobs[job_id]["error"]  = str(exc)


@app.post("/api/backtest")
def submit_backtest(req: BacktestRequest, background: BackgroundTasks) -> dict:
    job_id = str(uuid.uuid4())[:8]
    _bt_jobs[job_id] = {"status": "pending", "result": None, "error": None}
    background.add_task(_executor.submit, _run_backtest_sync, job_id, req)
    return {"job_id": job_id}


@app.get("/api/backtest/{job_id}")
def poll_backtest(job_id: str) -> dict:
    job = _bt_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job_id":  job_id,
        "status":  job["status"],
        "result":  job.get("result"),
        "error":   job.get("error"),
    }


# ── Serve React frontend (production) ─────────────────────────────────────────

if _DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = _DIST_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(404)
