import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List
import pandas as pd
import numpy as np
import requests as req_lib
from ..utils import get_token
from config.instruments import INSTRUMENTS as _IKEYS
from ..services.state import get_backtest_jobs

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2)

# ---- Timeframe → interval + default lookback (same as CLI) ----
_TF_CONFIG = {
    "1d":  ("day",      365),
    "1h":  ("60minute", 90),
    "30m": ("30minute", 60),
    "15m": ("15minute", 45),
}

# class BacktestRequest(BaseModel):
#     symbol:     str
#     strategy:   str = ""
#     strategies: list[str] = []
#     days:       int = 365
#     capital:    float = 500_000
#     product:    str = "CNC"
#     timeframe:  str = "1d"
#     risk:       dict[str, float] = {}
#     feature_engineer: bool = True
#     benchmark:  bool = False
#     monte_carlo: bool = False

class BacktestRequest(BaseModel):
    symbol:     str = ""           # single symbol (preferred for backward compatibility)
    symbols:    List[str] = []      # batch symbols for portfolio-style backtests
    strategy:   str = ""           # single strategy name (backward compat)
    strategies: List[str] = []      # multiple strategies – uses MetaStrategyEngine
    days:       int = 365
    capital:    float = 500_000
    product:    str = "CNC"        # CNC / MIS / NRML
    timeframe:  str = "1d"         # 1d, 1h, 30m, 15m
    risk:       dict[str, float] = {}
    feature_engineer: bool = True
    benchmark:  bool = False
    monte_carlo: bool = False
    walk_forward: bool = False
    walk_forward_splits: int = 5
    token:      str = ""          # optional explicit access token


def _choose_token(req: BacktestRequest) -> tuple[str, float]:
    if req.token:
        return req.token, 0.0
    return get_token()


def _make_cfg(req: BacktestRequest) -> dict:
    from config.loader import Settings
    cfg = Settings().as_dict()
    cfg.setdefault("data", {})["warmup_bars"] = 50
    cfg.setdefault("system", {})["mode"] = "backtest"
    if req.risk:
        cfg.setdefault("risk", {}).update(req.risk)
    return cfg


def _serialize_result(result, bench_df=None, include_curve=True, include_trades=True):
    m = result.metrics
    summary = {
        "symbol": result.symbol,
        "n_trades": m.get("n_trades", 0),
        "win_rate": round(m.get("win_rate", 0), 2),
        "total_return_pct": round(m.get("total_return_pct", 0), 2),
        "cagr_pct": round(m.get("cagr_pct", 0), 2),
        "sharpe": round(m.get("sharpe", 0), 3),
        "sortino": round(m.get("sortino", 0), 3),
        "max_drawdown_pct": round(m.get("max_drawdown_pct", 0), 2),
        "profit_factor": round(m.get("profit_factor", 0), 3),
        "avg_win": round(m.get("avg_win", 0), 2),
        "avg_loss": round(m.get("avg_loss", 0), 2),
        "expectancy": round(m.get("expectancy", 0), 2),
        "median_trade_return_pct": round(m.get("median_trade_return_pct", 0), 2),
        "avg_holding_bars": round(m.get("avg_holding_bars", 0), 1),
    }
    if include_curve:
        summary["equity_curve"] = result.equity_curve.tolist()
    if include_trades:
        summary["trades_pnl"] = [t.pnl for t in result.trades]
    if bench_df is not None and not bench_df.empty and len(result.equity_curve) > 1:
        summary["benchmark"] = _benchmark_metrics(result.equity_curve, bench_df)
    return summary

# ---------- benchmark fetch ----------
def _fetch_ohlcv(token: str, instrument_key: str, interval: str,
                 days: int) -> pd.DataFrame:
    key = instrument_key.replace("|", "%7C").replace(" ", "%20")
    to_d = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()
    url = f"https://api.upstox.com/v2/historical-candle/{key}/{interval}/{to_d}/{from_d}"
    r = req_lib.get(url, headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/json"}, timeout=15)
    if r.status_code != 200:
        raise ValueError(f"Data fetch failed: HTTP {r.status_code}")
    candles = r.json().get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])
    return df

# ---------- benchmark metrics ----------
def _benchmark_metrics(strat_curve, bench_df):
    if bench_df is None or bench_df.empty or len(strat_curve) < 2:
        return {}
    strat_vals = np.array(strat_curve, dtype=float)
    strat_rets = np.diff(strat_vals) / strat_vals[:-1]
    bench_close = bench_df["close"].values.astype(float)
    n = min(len(strat_rets), len(bench_close) - 1)
    strat_rets = strat_rets[-n:]
    bench_rets = np.diff(bench_close)[-n:] / bench_close[-n-1:-1]
    if len(strat_rets) < 5:
        return {}
    strat_total_ret = (strat_vals[-1] / strat_vals[0] - 1) * 100
    bench_total_ret = (bench_close[-1] / bench_close[0] - 1) * 100
    cov_mat = np.cov(strat_rets, bench_rets)
    beta = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] != 0 else 0.0
    alpha = strat_total_ret - beta * bench_total_ret
    active_rets = strat_rets - bench_rets
    te = float(np.std(active_rets)) * np.sqrt(252) if len(active_rets) > 1 else 0.0
    ir = (alpha / te) if te != 0 else 0.0
    return {
        "bench_return_pct": round(bench_total_ret, 2),
        "strat_return_pct": round(strat_total_ret, 2),
        "alpha_pct":        round(alpha, 2),
        "beta":             round(beta, 3),
        "info_ratio":       round(ir, 3),
    }

# ---------- Monte Carlo ----------
def _monte_carlo_metrics(trades_pnl):
    try:
        from backtester.monte_carlo import run_monte_carlo
        mc = run_monte_carlo(trades_pnl, n_simulations=500, method="bootstrap")
        return {
            "sharpe_mean":    round(mc.sharpe_mean, 3),
            "sharpe_p5":      round(mc.sharpe_p5, 3),
            "sharpe_p95":     round(mc.sharpe_p95, 3),
            # mc.max_dd_* / final_return_mean are fractions (0.03 = 3%) — scale to percent
            "max_dd_mean":    round(mc.max_dd_mean * 100, 2),
            "max_dd_p95":     round(mc.max_dd_p95 * 100, 2),
            "return_mean_pct": round(mc.final_return_mean * 100, 2),
            "p_value_sharpe": round(mc.p_value_sharpe * 100, 1),
        }
    except Exception as e:
        return {"error": str(e)}

# ---------- Main run ----------
def _run_backtest_sync(job_id: str, req: BacktestRequest) -> None:
    jobs = get_backtest_jobs()
    jobs[job_id]["status"] = "running"
    try:
        token, age_h = _choose_token(req)
        if not token or age_h > 23:
            raise ValueError("Token missing or expired")

        symbols = [s.strip().upper() for s in req.symbols if s.strip()]
        if not symbols and req.symbol.strip():
            symbols = [req.symbol.strip().upper()]
        if not symbols:
            raise ValueError("No symbol(s) specified — provide 'symbol' or 'symbols'")

        interval, default_days = _TF_CONFIG.get(req.timeframe, ("day", 365))
        days = req.days if req.days else default_days

        bench_df = None
        if req.benchmark:
            try:
                tmp = _fetch_ohlcv(token, "NSE_INDEX|Nifty 50", interval, days)
                bench_df = tmp if not tmp.empty else None
            except Exception:
                bench_df = None

        results = []
        errors = []

        for symbol in symbols:
            try:
                ikey = _IKEYS.get(symbol)
                if not ikey:
                    raise ValueError(f"Unknown symbol: {symbol}")

                df = _fetch_ohlcv(token, ikey, interval, days)
                if len(df) < 60:
                    raise ValueError(f"Only {len(df)} candles — need 60+")

                if req.feature_engineer:
                    try:
                        from feature_engine.feature_builder import FeatureBuilder
                        df = FeatureBuilder().build(df)
                    except Exception:
                        pass

                if len(df) < 60:
                    raise ValueError(f"Only {len(df)} candles after features — need 60+")

                cfg = _make_cfg(req)
                strategies_to_run = req.strategies if req.strategies else ([req.strategy] if req.strategy else [])

                strat_obj = None
                engine = None
                if len(strategies_to_run) == 1 and req.strategy and not req.strategies:
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
                    strat_name = strategies_to_run[0]
                    if strat_name in _STRAT_MAP:
                        import importlib
                        mod_name, cls_name = _STRAT_MAP[strat_name]
                        strat_obj = getattr(importlib.import_module(mod_name), cls_name)(cfg)
                    else:
                        raise ValueError(f"Unknown single strategy: {strat_name}")
                else:
                    if strategies_to_run:
                        cfg.setdefault("strategies", {})["enabled"] = strategies_to_run
                    from strategies.meta_engine import MetaStrategyEngine
                    engine = MetaStrategyEngine(cfg)

                from backtester.backtester import Backtester
                bt = Backtester(cfg, initial_capital=req.capital, product=req.product)

                if req.walk_forward:
                    if engine is not None:
                        wf_results = bt.run_walk_forward(
                            df, symbol, engine=engine,
                            n_splits=req.walk_forward_splits,
                        )
                    else:
                        wf_results = bt.run_walk_forward(
                            df, symbol, strategy=strat_obj,
                            n_splits=req.walk_forward_splits,
                        )
                    if not wf_results:
                        raise ValueError("Walk-forward did not produce any valid splits")

                    symbol_result = {
                        "symbol": symbol,
                        "strategy": req.strategy if req.strategy else req.strategies,
                        "walk_forward": True,
                        "splits": [
                            {**_serialize_result(r, bench_df if req.benchmark else None,
                                                 include_curve=False, include_trades=False),
                             "split_index": idx + 1}
                            for idx, r in enumerate(wf_results)
                        ],
                        "final_split": _serialize_result(
                            wf_results[-1], bench_df if req.benchmark else None,
                        ),
                    }
                    if req.monte_carlo and wf_results[-1].trades:
                        # run_monte_carlo expects fractional per-trade returns
                        # (0.02 = 2%), not raw rupee P&L — normalize by capital.
                        pnl_list = [t.pnl / req.capital for t in wf_results[-1].trades]
                        symbol_result["monte_carlo"] = _monte_carlo_metrics(pnl_list)
                else:
                    if engine is not None:
                        result = bt.run(df, symbol, engine=engine)
                    else:
                        result = bt.run(df, symbol, strategy=strat_obj)

                    symbol_result = _serialize_result(result, bench_df if req.benchmark else None)
                    if req.monte_carlo and result.trades:
                        pnl_list = [t.pnl / req.capital for t in result.trades]
                        symbol_result["monte_carlo"] = _monte_carlo_metrics(pnl_list)

                results.append(symbol_result)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})

        if not results:
            raise ValueError(f"All backtests failed: {errors}")

        jobs[job_id]["status"] = "done"
        jobs[job_id]["result"] = {
            "symbols": [r["symbol"] for r in results],
            "results": results,
        }
        if errors:
            jobs[job_id]["result"]["errors"] = errors

    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(exc)

# ---- Endpoints unchanged ----
@router.post("/backtest")
def submit_backtest(req: BacktestRequest, background: BackgroundTasks) -> dict:
    job_id = str(uuid.uuid4())[:8]
    jobs = get_backtest_jobs()
    jobs[job_id] = {"status": "pending", "result": None, "error": None}
    background.add_task(_executor.submit, _run_backtest_sync, job_id, req)
    return {"job_id": job_id}

@router.post("/backtest/batch")
def submit_backtest_batch(req: BacktestRequest, background: BackgroundTasks) -> dict:
    return submit_backtest(req, background)

@router.get("/backtest/{job_id}")
def poll_backtest(job_id: str) -> dict:
    jobs = get_backtest_jobs()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job_id": job_id, "status": job["status"], "result": job.get("result"), "error": job.get("error")}