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
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
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
    "NIFTY50":    "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
}


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
    from_d = (date.today() - timedelta(days=days)).isoformat()

    if interval == "day":
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
    else:
        url = f"https://api.upstox.com/v2/historical-candle/intraday/{key}/{interval}"

    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.get(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Upstox API error: {resp.text[:200]}")

    raw = resp.json().get("data", {}).get("candles", [])
    # Convert to lightweight-charts format: { time (unix), open, high, low, close, volume }
    candles = []
    for c in raw:
        try:
            import datetime as dt
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
            "macd_momentum":       ("strategies.momentum",       "MacdMomentumStrategy"),
            "breakout_atr":        ("strategies.breakout",       "AtrBreakoutStrategy"),
            "supertrend":          ("strategies.trend",          "SupertrendStrategy"),
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
