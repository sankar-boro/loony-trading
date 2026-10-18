"""
Portfolio analytics for the current holdings: Nifty beta and a hedge
suggestion (portfolio_manager/beta_neutral.py), factor exposures
(analytics/factor_model.py) and historical crisis stress tests
(backtester/stress_test.py).

Everything is computed "as if held": the current positions, at their
current signed market values, applied to the past year of daily returns.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from analytics.factor_model import FactorModel
from backtester.stress_test import run_stress_test
from portfolio_manager.beta_neutral import NIFTY_LOT_SIZE, BetaNeutralManager

# Factor name → index symbol in config/instruments.py
FACTOR_INDICES = {"market": "NIFTY50", "banking": "BANKNIFTY", "it": "NIFTYIT",
                  "fmcg": "NIFTYFMCG", "auto": "NIFTYAUTO", "midcap": "MIDCAP"}


def holdings(positions: list[dict]) -> dict[str, float]:
    """{symbol: signed market value} — shorts negative."""
    out: dict[str, float] = {}
    for p in positions:
        sym = p.get("symbol")
        if not sym:
            continue
        value = float(p.get("size", 0)) * float(p.get("current_price") or p.get("entry_price", 0))
        out[sym] = out.get(sym, 0.0) + value * (1 if p.get("direction", 1) >= 0 else -1)
    return out


def analyse(positions: list[dict], capital: float,
            fetch_daily: Callable[[list[str], int], dict], days: int = 365) -> dict:
    book = holdings(positions)
    if not book:
        return {"positions": 0}
    frames = fetch_daily(sorted(book) + list(FACTOR_INDICES.values()), days)
    closes = {s: f["close"] for s, f in frames.items() if f is not None and not f.empty}
    nifty = closes.get(FACTOR_INDICES["market"])
    gross = sum(abs(v) for v in book.values())
    out: dict = {"positions": len(book), "gross": round(gross, 2),
                 "net": round(sum(book.values()), 2), "missing": sorted(set(book) - set(closes))}

    # ── Beta and hedge ───────────────────────────────────────────────────────
    bnm = BetaNeutralManager(capital=capital, beta_lookback=120)
    per_symbol = {}
    for sym in book:
        if sym in closes and nifty is not None:
            est = bnm.compute_beta(sym, closes[sym], nifty)
            per_symbol[sym] = {"beta": est.beta, "r_squared": est.r_squared}
    port_beta = bnm.portfolio_beta({s: v for s, v in book.items() if s in per_symbol})
    hedge, hedge_note = None, ""
    if nifty is not None and per_symbol:
        lot_value = float(nifty.iloc[-1]) * NIFTY_LOT_SIZE
        order = bnm.compute_hedge({s: v for s, v in book.items() if s in per_symbol}, float(nifty.iloc[-1]))
        if order:
            hedge = {"direction": order.direction, "lots": order.lots, "notional": order.notional,
                     "instrument": "Nifty 50 futures", "reason": order.reason}
        elif abs(port_beta) >= bnm.rebalance_threshold:
            hedge_note = (f"Beta exposure ₹{abs(port_beta) * gross:,.0f} is below one Nifty futures "
                          f"lot (₹{lot_value:,.0f}) — too small to hedge with futures")
        else:
            hedge_note = f"Portfolio beta within ±{bnm.rebalance_threshold} — no hedge needed"
    out["beta"] = {"portfolio": port_beta, "per_symbol": per_symbol,
                   "beta_exposure": round(port_beta * gross, 2), "hedge": hedge, "hedge_note": hedge_note}

    # ── Factor exposures ─────────────────────────────────────────────────────
    fm = FactorModel()
    rets = pd.DataFrame({s: closes[s] for s in book if s in closes}).pct_change().dropna(how="all")
    weights = pd.Series({s: book[s] / gross for s in rets.columns})
    port_ret = (rets.fillna(0.0) * weights).sum(axis=1)
    factors = pd.DataFrame({name: closes[sym] for name, sym in FACTOR_INDICES.items()
                            if sym in closes}).pct_change().dropna()
    exposure = fm.fit(port_ret, factors) if len(factors.columns) else None
    out["factors"] = None if exposure is None or not exposure.n_obs else {
        "alpha_annual_pct": round(exposure.alpha * 100, 2),
        "loadings": exposure.factor_loadings, "t_stats": exposure.t_stats,
        "r_squared": exposure.r_squared, "residual_vol_pct": round(exposure.residual_vol * 100, 2),
        "n_obs": exposure.n_obs,
        "sector_exposure": fm.sector_exposure(book),
        "hedge_suggestion": fm.hedge_suggestion(book),
    }

    # ── Stress test ──────────────────────────────────────────────────────────
    # The stress test applies its beta to the whole capital; the book holds
    # gross / capital of it, so scale the beta to capital terms.
    daily_pnl = list((port_ret * gross).tail(250).values)
    capital_beta = (port_beta if per_symbol else 1.0) * gross / capital
    report = run_stress_test(daily_pnl, capital, beta_vs_nifty=capital_beta)
    out["stress"] = {
        "capital_beta": round(capital_beta, 3),
        "worst": report.worst_scenario,
        "tail_cvar_pct": report.tail_cvar,
        "scenarios": [{"key": k, "name": r.scenario_name, "return_pct": round(r.strategy_total_pct, 2),
                       "max_drawdown_pct": round(r.max_drawdown_pct, 2), "recovery_days": r.recovery_days,
                       "cvar_95_pct": round(r.cvar_95, 2), "survived": r.survived}
                      for k, r in report.results.items()],
    }
    return _plain(out)


def _plain(x):
    """numpy scalars → Python numbers/bools, recursively (JSON-safe)."""
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return None if not np.isfinite(x) else float(x)
    return x
