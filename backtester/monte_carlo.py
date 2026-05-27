"""
Monte Carlo Backtesting — Confidence Intervals for Strategy Performance.

Why Monte Carlo over simple backtest:
- A single backtest is one path through history — survivorship bias, luck
- MC resamples trades to simulate thousands of possible futures
- Gives confidence intervals: "90% probability that drawdown stays below X%"
- Detects if backtest Sharpe is real or just lucky (p-value on alpha)

Three methods:
1. Bootstrap resampling — draw N trades with replacement from trade history
   Most conservative; assumes trades are i.i.d. (not always true)

2. Block bootstrap — draw blocks of K consecutive trades
   Preserves autocorrelation (runs of wins/losses, regime clustering)

3. Parametric simulation — fit normal/t-distribution to returns, sample
   Fast but assumes distributional form

Outputs:
- Distribution of: final return, max drawdown, Sharpe ratio, win rate
- p-value: probability that Sharpe > 0 is due to chance alone
- VaR/CVaR at 95% and 99% confidence under MC paths
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from utils.logger import get_logger

logger = get_logger("monte_carlo")


@dataclass
class MCResult:
    """Results of one Monte Carlo simulation run."""
    n_simulations:      int
    n_trades:           int
    method:             str

    # Distribution statistics
    final_return_mean:  float
    final_return_std:   float
    final_return_p5:    float
    final_return_p95:   float
    max_dd_mean:        float
    max_dd_p95:         float
    sharpe_mean:        float
    sharpe_p5:          float
    sharpe_p95:         float
    win_rate_mean:      float

    # Risk
    cvar_95:            float   # mean loss in worst 5% of paths
    p_value_sharpe:     float   # P(Sharpe > 0 by chance)

    # Raw distributions (optional)
    returns_dist:  Optional[np.ndarray] = field(default=None, repr=False)
    drawdown_dist: Optional[np.ndarray] = field(default=None, repr=False)
    sharpe_dist:   Optional[np.ndarray] = field(default=None, repr=False)

    def summary(self) -> str:
        return (
            f"MC ({self.method}, N={self.n_simulations}):\n"
            f"  Return:  {self.final_return_mean:.1%} ± {self.final_return_std:.1%} "
            f"[5th: {self.final_return_p5:.1%}, 95th: {self.final_return_p95:.1%}]\n"
            f"  Max DD:  {self.max_dd_mean:.1%} (95th: {self.max_dd_p95:.1%})\n"
            f"  Sharpe:  {self.sharpe_mean:.2f} [5th: {self.sharpe_p5:.2f}, 95th: {self.sharpe_p95:.2f}]\n"
            f"  CVaR95:  {self.cvar_95:.1%}\n"
            f"  p-value: {self.p_value_sharpe:.3f}"
        )


def _compute_path_metrics(returns: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Compute (total_return, max_drawdown, sharpe, win_rate) for one return path.
    """
    if len(returns) == 0:
        return 0.0, 0.0, 0.0, 0.0

    # Total return (compound)
    total = float(np.prod(1 + returns) - 1)

    # Max drawdown
    cum_ret = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cum_ret)
    dd = (running_max - cum_ret) / running_max
    max_dd = float(dd.max())

    # Sharpe (annualised assuming 252 trading days)
    mu  = float(returns.mean())
    std = float(returns.std())
    sharpe = (mu / std * np.sqrt(252)) if std > 1e-9 else 0.0

    win_rate = float((returns > 0).mean())

    return total, max_dd, sharpe, win_rate


def run_monte_carlo(
    trade_returns: List[float],      # list of per-trade P&L% (e.g. 0.02, -0.01, ...)
    n_simulations: int = 1000,
    method: str = "bootstrap",      # "bootstrap" | "block_bootstrap" | "parametric"
    block_size: int = 10,           # for block bootstrap
    seed: int = 42,
    store_distributions: bool = True,
) -> MCResult:
    """
    Run Monte Carlo simulation on trade return history.

    Args:
        trade_returns: list of trade-level returns (% as decimal, e.g. 0.02 = 2%)
        n_simulations: number of MC paths
        method: resampling method
        block_size: block size for block_bootstrap
        seed: random seed for reproducibility

    Returns:
        MCResult with distribution statistics
    """
    if len(trade_returns) < 5:
        logger.warning("MC: fewer than 5 trades — results unreliable")

    r = np.array(trade_returns, dtype=float)
    n = len(r)
    rng = np.random.RandomState(seed)

    logger.info(f"MC: running {n_simulations} simulations ({method}) on {n} trades")

    all_returns  = np.zeros(n_simulations)
    all_drawdowns= np.zeros(n_simulations)
    all_sharpes  = np.zeros(n_simulations)
    all_winrates = np.zeros(n_simulations)

    for i in range(n_simulations):
        if method == "bootstrap":
            sample = rng.choice(r, size=n, replace=True)

        elif method == "block_bootstrap":
            k     = block_size
            n_blocks = max(1, n // k)
            blocks = []
            for _ in range(n_blocks + 1):
                start = rng.randint(0, max(1, n - k))
                blocks.append(r[start: start + k])
            sample = np.concatenate(blocks)[:n]

        elif method == "parametric":
            mu_r    = float(r.mean())
            std_r   = float(r.std())
            df_t    = max(3, n - 1)    # student-t degrees of freedom
            sample  = mu_r + std_r * rng.standard_t(df_t, size=n)

        else:
            raise ValueError(f"Unknown method: {method}")

        total, max_dd, sharpe, win_rate = _compute_path_metrics(sample)
        all_returns[i]   = total
        all_drawdowns[i] = max_dd
        all_sharpes[i]   = sharpe
        all_winrates[i]  = win_rate

    # CVaR 95%: mean of worst 5% return paths
    loss_paths = -all_returns
    var_95     = float(np.percentile(loss_paths, 95))
    cvar_95    = float(loss_paths[loss_paths >= var_95].mean()) if any(loss_paths >= var_95) else var_95

    # p-value: probability Sharpe > 0 is due to chance
    # H0: true Sharpe = 0; test via t-test on returns
    t_stat, p_value = stats.ttest_1samp(r, 0)
    p_value_adj = float(p_value / 2) if t_stat > 0 else 1.0   # one-sided

    result = MCResult(
        n_simulations=n_simulations,
        n_trades=n,
        method=method,
        final_return_mean=round(float(all_returns.mean()), 4),
        final_return_std=round(float(all_returns.std()), 4),
        final_return_p5=round(float(np.percentile(all_returns, 5)), 4),
        final_return_p95=round(float(np.percentile(all_returns, 95)), 4),
        max_dd_mean=round(float(all_drawdowns.mean()), 4),
        max_dd_p95=round(float(np.percentile(all_drawdowns, 95)), 4),
        sharpe_mean=round(float(all_sharpes.mean()), 3),
        sharpe_p5=round(float(np.percentile(all_sharpes, 5)), 3),
        sharpe_p95=round(float(np.percentile(all_sharpes, 95)), 3),
        win_rate_mean=round(float(all_winrates.mean()), 3),
        cvar_95=round(cvar_95, 4),
        p_value_sharpe=round(p_value_adj, 4),
        returns_dist=all_returns if store_distributions else None,
        drawdown_dist=all_drawdowns if store_distributions else None,
        sharpe_dist=all_sharpes if store_distributions else None,
    )

    logger.info(result.summary())
    return result


def compare_methods(
    trade_returns: List[float],
    n_simulations: int = 500,
) -> Dict[str, MCResult]:
    """Run all three MC methods and return comparison."""
    results = {}
    for method in ("bootstrap", "block_bootstrap", "parametric"):
        results[method] = run_monte_carlo(
            trade_returns, n_simulations=n_simulations, method=method,
        )
    return results


def required_edge_for_profitability(
    target_sharpe:   float = 1.0,
    avg_trade_vol:   float = 0.02,    # average trade volatility (2%)
    n_trades_annual: int   = 200,
) -> float:
    """
    Compute minimum required win rate and edge for a target Sharpe.
    Returns required average return per trade.
    """
    # Sharpe = (mean_ret / vol) * sqrt(n) where n = annual trades
    # mean_ret = target_sharpe * vol / sqrt(n)
    required_mean = target_sharpe * avg_trade_vol / np.sqrt(n_trades_annual)
    return round(required_mean, 5)
