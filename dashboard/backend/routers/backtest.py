import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
import pandas as pd
import requests as req_lib
from ..utils import get_token
# from ..config import _IKEYS, ROOT
from config.instruments import INSTRUMENTS as _IKEYS
from ..services.state import get_backtest_jobs

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2)

class BacktestRequest(BaseModel):
    symbol:   str
    strategy: str
    days:     int = 365
    capital:  float = 500_000

def _run_backtest_sync(job_id: str, req: BacktestRequest) -> None:
    jobs = get_backtest_jobs()
    jobs[job_id]["status"] = "running"
    try:
        token, age_h = get_token()
        if not token or age_h > 23:
            raise ValueError("Token missing or expired")

        ikey = _IKEYS.get(req.symbol.upper())
        if not ikey:
            raise ValueError(f"Unknown symbol: {req.symbol}")

        key = ikey.replace("|", "%7C").replace(" ", "%20")
        to_d = date.today().isoformat()
        from_d = (date.today() - timedelta(days=req.days)).isoformat()
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
        r = req_lib.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=15)
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

        _STRAT_MAP = {
            "ema_crossover":       ("strategies.trend", "EmaCrossoverStrategy"),
            "rsi_mean_reversion":  ("strategies.mean_reversion", "RsiReversionStrategy"),
            "bollinger_reversion": ("strategies.mean_reversion", "BollingerReversionStrategy"),
            "zscore_reversion":    ("strategies.mean_reversion", "ZscoreReversionStrategy"),
            "vwap_reversion":      ("strategies.mean_reversion", "VwapReversionStrategy"),
            "macd_momentum":       ("strategies.momentum", "MacdMomentumStrategy"),
            "rsi_momentum":        ("strategies.momentum", "RsiMomentumStrategy"),
            "volume_momentum":     ("strategies.momentum", "VolumeMomentumStrategy"),
            "breakout_atr":        ("strategies.breakout", "AtrBreakoutStrategy"),
            "sr_breakout":         ("strategies.breakout", "SupportResistanceBreakoutStrategy"),
            "range_breakout":      ("strategies.breakout", "RangeBreakoutStrategy"),
            "supertrend":          ("strategies.trend", "SupertrendStrategy"),
            "donchian_breakout":   ("strategies.trend", "DonchianBreakoutStrategy"),
            "candlestick_pattern": ("strategies.candlestick", "CandlestickPatternStrategy"),
        }

        strat_obj = None
        if req.strategy in _STRAT_MAP:
            import importlib
            mod_name, cls_name = _STRAT_MAP[req.strategy]
            strat_obj = getattr(importlib.import_module(mod_name), cls_name)(cfg)

        from backtester.backtester import Backtester
        bt = Backtester(cfg, initial_capital=req.capital, product="CNC")
        result = bt.run(df, req.symbol, strategy=strat_obj)
        m = result.metrics

        jobs[job_id]["status"] = "done"
        jobs[job_id]["result"] = {
            "symbol": req.symbol, "strategy": req.strategy,
            "n_trades": m.get("n_trades", 0), "win_rate": m.get("win_rate", 0),
            "total_return_pct": m.get("total_return_pct", 0), "sharpe": m.get("sharpe", 0),
            "max_drawdown_pct": m.get("max_drawdown_pct", 0), "profit_factor": m.get("profit_factor", 0),
            "equity_curve": result.equity_curve.tolist(), "trades_pnl": [t.pnl for t in result.trades],
        }
    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(exc)

@router.post("/backtest")
def submit_backtest(req: BacktestRequest, background: BackgroundTasks) -> dict:
    job_id = str(uuid.uuid4())[:8]
    jobs = get_backtest_jobs()
    jobs[job_id] = {"status": "pending", "result": None, "error": None}
    background.add_task(_executor.submit, _run_backtest_sync, job_id, req)
    return {"job_id": job_id}

@router.get("/backtest/{job_id}")
def poll_backtest(job_id: str) -> dict:
    jobs = get_backtest_jobs()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job_id": job_id, "status": job["status"], "result": job.get("result"), "error": job.get("error")}