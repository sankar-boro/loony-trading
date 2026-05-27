from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List
from utils.logger import get_logger
from utils.math_utils import sharpe_ratio, max_drawdown, safe_divide

logger = get_logger("portfolio")


class PortfolioManager:
    """
    Tracks multi-asset portfolio performance, controls per-asset allocation,
    and prevents correlated overexposure.
    """

    def __init__(self, cfg: dict, initial_capital: float):
        self.cfg = cfg.get("portfolio", {})
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.base_currency = self.cfg.get("base_currency", "USDT")
        self.equity_curve: List[float] = [initial_capital]
        self.trade_log: List[dict] = []
        self._returns: List[float] = []
        self._correlation_limit = self.cfg.get("correlation_limit", 0.7)
        self._price_history: Dict[str, List[float]] = {}

    # ── Capital allocation ─────────────────────────────────────────────────────

    def max_allocation(self, symbol: str, current_allocations: Dict[str, float]) -> float:
        """Maximum capital that can be allocated to this symbol right now."""
        total_allocated = sum(current_allocations.values())
        max_portfolio = self.cfg.get("max_portfolio_risk", 0.20)
        current = current_allocations.get(symbol, 0.0)
        available = max(0.0, self.capital * max_portfolio - total_allocated + current)
        return available

    def is_correlated(self, symbol: str,
                       open_symbols: List[str]) -> bool:
        """Block trade if new symbol is highly correlated with existing positions."""
        if not open_symbols or symbol not in self._price_history:
            return False
        for existing in open_symbols:
            if existing == symbol or existing not in self._price_history:
                continue
            corr = self._pairwise_correlation(symbol, existing)
            if abs(corr) > self._correlation_limit:
                logger.warning(f"High correlation between {symbol} and {existing}: {corr:.2f}")
                return True
        return False

    def _pairwise_correlation(self, a: str, b: str, window: int = 30) -> float:
        prices_a = np.array(self._price_history[a][-window:])
        prices_b = np.array(self._price_history[b][-window:])
        n = min(len(prices_a), len(prices_b))
        if n < 10:
            return 0.0
        ret_a = np.diff(prices_a[-n:]) / prices_a[-n:-1]
        ret_b = np.diff(prices_b[-n:]) / prices_b[-n:-1]
        if np.std(ret_a) == 0 or np.std(ret_b) == 0:
            return 0.0
        return float(np.corrcoef(ret_a, ret_b)[0, 1])

    # ── State updates ──────────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        self._price_history.setdefault(symbol, []).append(price)
        if len(self._price_history[symbol]) > 200:
            self._price_history[symbol] = self._price_history[symbol][-200:]

    def record_trade(self, symbol: str, pnl: float, strategy: str) -> None:
        self.capital += pnl
        self.equity_curve.append(self.capital)
        ret = safe_divide(pnl, self.capital - pnl)
        self._returns.append(ret)
        self.trade_log.append({
            "symbol": symbol, "pnl": pnl,
            "strategy": strategy, "capital": self.capital,
        })

    # ── Analytics ──────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        equity = np.array(self.equity_curve)
        returns = np.array(self._returns) if self._returns else np.array([0.0])
        total_return = safe_divide(self.capital - self.initial_capital, self.initial_capital)
        n_trades = len(self.trade_log)
        wins = sum(1 for t in self.trade_log if t["pnl"] > 0)
        losses = [t["pnl"] for t in self.trade_log if t["pnl"] < 0]
        profits = [t["pnl"] for t in self.trade_log if t["pnl"] > 0]
        return {
            "total_return_pct": round(total_return * 100, 2),
            "capital": round(self.capital, 2),
            "n_trades": n_trades,
            "win_rate": round(safe_divide(wins, n_trades) * 100, 1),
            "profit_factor": round(safe_divide(sum(profits), abs(sum(losses))), 2),
            "sharpe_ratio": round(sharpe_ratio(returns), 3),
            "max_drawdown_pct": round(max_drawdown(equity) * 100, 2),
            "avg_win": round(safe_divide(sum(profits), len(profits)), 4) if profits else 0,
            "avg_loss": round(safe_divide(sum(losses), len(losses)), 4) if losses else 0,
        }
