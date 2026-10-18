"""
Stress Testing — Replay historical crisis scenarios on current strategy.

Historical Indian market crisis scenarios:
1. COVID Crash 2020        — Nifty fell 38% in 38 trading days (Feb-Mar 2020)
2. IL&FS / NBFC Crisis 2018 — Nifty fell 15% (Sep-Oct 2018), liquidity freeze
3. China-driven crash 2015 — Nifty fell 12% (Aug 2015), global contagion
4. Global Financial Crisis 2008 — Nifty fell 60% peak-to-trough
5. Demonetisation shock 2016 — Nifty fell 10% in 2 weeks (Nov 2016)

Methodology:
- For each scenario, replay the daily % moves from that period
- Apply to current strategy P&L assuming similar position sizing
- Report max drawdown, recovery days, CVaR under stress
- "Would your strategy have survived?"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from risk_manager.cvar import historical_cvar, CVaRReport
from utils.logger import get_logger

logger = get_logger("stress_test")


# ── Scenario definitions ──────────────────────────────────────────────────────
# Daily returns are approximate (realistic order-of-magnitude)
# Calibrated from NSE historical data

STRESS_SCENARIOS: Dict[str, Dict] = {
    "covid_2020": {
        "name":        "COVID Crash 2020",
        "description": "Nifty fell 38% in 38 trading days. Fastest bear market in NSE history.",
        "period":      "Feb 24 – Apr 3 2020",
        "nifty_total_pct": -38.0,
        # Daily returns (approximate distribution of the actual crash)
        "daily_returns": (
            [-0.03, -0.05, -0.08, -0.13, -0.04, -0.05, -0.03, -0.08, -0.04,
             -0.05, -0.13, -0.08, -0.04, 0.02, -0.05, -0.10, 0.03, -0.04,
             -0.05, -0.03, 0.04, -0.03, -0.05, 0.02, -0.02, -0.04, -0.03,
             0.01, -0.02, -0.03, 0.01, 0.03, -0.01, 0.02, 0.01, 0.02, 0.01, 0.02]
        ),
        "vix_peak": 83.6,
        "fii_net_cr": -65000,    # FII sold ₹65,000 Cr in ~40 days
    },
    "ilfs_nbfc_2018": {
        "name":        "IL&FS / NBFC Crisis 2018",
        "description": "Credit market freeze after IL&FS default. NBFCs collapsed, liquidity dried up.",
        "period":      "Sep – Oct 2018",
        "nifty_total_pct": -15.0,
        "daily_returns": (
            [-0.02, -0.03, -0.04, -0.02, -0.01, -0.03, 0.01, -0.02, -0.03,
             -0.02, 0.01, -0.01, -0.02, -0.03, -0.01, 0.01, -0.01, -0.02,
             0.01, 0.01, -0.01, -0.01, 0.02, 0.01, -0.01, 0.01]
        ),
        "vix_peak": 28.0,
        "fii_net_cr": -30000,
    },
    "china_crash_2015": {
        "name":        "China-Driven Crash 2015",
        "description": "Global contagion from China bubble burst. Nifty fell 12% in August.",
        "period":      "Aug 2015",
        "nifty_total_pct": -12.0,
        "daily_returns": (
            [-0.01, -0.03, -0.05, -0.04, 0.02, -0.02, -0.01, -0.01, 0.01,
             -0.01, 0.01, 0.02, 0.01, -0.01, -0.01, 0.01, 0.01, -0.01, 0.02, 0.02]
        ),
        "vix_peak": 27.0,
        "fii_net_cr": -18000,
    },
    "gfc_2008": {
        "name":        "Global Financial Crisis 2008",
        "description": "Lehman collapse contagion. Nifty fell 60% peak-to-trough in ~14 months.",
        "period":      "Jan 2008 – Mar 2009",
        "nifty_total_pct": -60.0,
        "daily_returns": (
            [-0.02, -0.03, -0.04, -0.05, -0.02, -0.03, 0.01, -0.04, -0.03,
             -0.02, -0.04, -0.06, -0.08, -0.04, -0.03, -0.05, 0.02, -0.03,
             -0.02, -0.04, -0.03, 0.01, -0.02, -0.05, -0.04, -0.06, -0.03,
             -0.02, 0.02, -0.03, -0.04, -0.02, -0.01, 0.01, -0.02, -0.03,
             -0.01, 0.01, -0.02, -0.03]
        ),
        "vix_peak": 85.0,
        "fii_net_cr": -52000,
    },
    "demonetisation_2016": {
        "name":        "Demonetisation Shock 2016",
        "description": "Indian demonetisation announced. Nifty fell 10% in 2 weeks on liquidity fears.",
        "period":      "Nov 8–25 2016",
        "nifty_total_pct": -10.0,
        "daily_returns": (
            [-0.01, -0.03, -0.04, -0.02, -0.03, -0.01, -0.02, 0.01, -0.01,
             -0.01, 0.01, 0.01, 0.02, 0.01, -0.01]
        ),
        "vix_peak": 22.0,
        "fii_net_cr": -12000,
    },
}


@dataclass
class ScenarioResult:
    scenario_name: str
    strategy_total_pct: float
    max_drawdown_pct: float
    recovery_days: int
    daily_pnl: List[float]
    cvar_95: float
    sharpe_in_crisis: float
    survived: bool              # True if strategy didn't breach drawdown limit
    description: str = ""


@dataclass
class StressTestReport:
    results: Dict[str, ScenarioResult] = field(default_factory=dict)
    worst_scenario: Optional[str] = None
    tail_cvar: Optional[float] = None   # CVaR across all scenarios combined

    def summary(self) -> pd.DataFrame:
        rows = []
        for name, r in self.results.items():
            rows.append({
                "Scenario":        r.scenario_name,
                "Strategy Return": f"{r.strategy_total_pct:.1f}%",
                "Max Drawdown":    f"{r.max_drawdown_pct:.1f}%",
                "Recovery Days":   r.recovery_days,
                "CVaR 95%":        f"{r.cvar_95:.2f}%",
                "Survived":        "✓" if r.survived else "✗",
            })
        return pd.DataFrame(rows)


# ── Core stress test engine ────────────────────────────────────────────────────

def run_stress_test(
    strategy_daily_pnl: List[float],
    capital: float,
    max_drawdown_limit_pct: float = 20.0,
    scenarios: Optional[List[str]] = None,
    beta_vs_nifty: float = 0.7,      # how correlated strategy is with Nifty
) -> StressTestReport:
    """
    Run strategy through historical stress scenarios.

    Args:
        strategy_daily_pnl: recent daily P&L (₹) used to calibrate strategy vol
        capital:            portfolio capital (₹)
        max_drawdown_limit_pct: kill-switch threshold (%)
        scenarios:          list of scenario keys; None = all
        beta_vs_nifty:      strategy's Nifty beta (0 = market-neutral, 1 = full market)

    Returns:
        StressTestReport with per-scenario results
    """
    scenario_keys = scenarios or list(STRESS_SCENARIOS.keys())
    report = StressTestReport()

    # Calibrate strategy vol from recent history
    if len(strategy_daily_pnl) >= 10:
        strategy_daily_ret = np.array(strategy_daily_pnl) / capital
        strategy_vol_daily = float(np.std(strategy_daily_ret))
    else:
        strategy_vol_daily = 0.01    # assume 1% daily vol

    for key in scenario_keys:
        if key not in STRESS_SCENARIOS:
            continue
        sc = STRESS_SCENARIOS[key]
        result = _simulate_scenario(
            sc, strategy_vol_daily, capital,
            max_drawdown_limit_pct, beta_vs_nifty,
        )
        report.results[key] = result

    if report.results:
        # Worst scenario by max drawdown
        report.worst_scenario = max(
            report.results.keys(),
            key=lambda k: abs(report.results[k].max_drawdown_pct),
        )
        # Tail CVaR across all scenarios
        all_daily = []
        for r in report.results.values():
            all_daily.extend(r.daily_pnl)
        if all_daily:
            cvar_report = historical_cvar(
                [x / capital * 100 for x in all_daily], 0.95
            )
            report.tail_cvar = round(cvar_report.cvar, 3)

    return report


def calibrated_returns(scenario: dict) -> np.ndarray:
    """The scenario's daily Nifty returns, rescaled in log space so they
    compound to its stated `nifty_total_pct`. The hand-entered daily paths
    keep the shape of each crisis but did not add up — COVID's compounded
    to −68 % against the −38 % it describes — which overstated every loss."""
    r = np.asarray(scenario["daily_returns"], dtype=float)
    target = scenario.get("nifty_total_pct")
    logs = np.log1p(r)
    if target is None or abs(logs.sum()) < 1e-12:
        return r
    return np.expm1(logs * np.log1p(target / 100) / logs.sum())


def _simulate_scenario(
    scenario: dict,
    strategy_vol_daily: float,
    capital: float,
    max_dd_limit: float,
    beta: float,
) -> ScenarioResult:
    """Simulate one scenario and compute metrics."""
    nifty_returns = calibrated_returns(scenario)
    n = len(nifty_returns)

    # Strategy returns = beta * nifty + idiosyncratic noise
    rng = np.random.RandomState(42)
    idio_noise = rng.randn(n) * strategy_vol_daily * np.sqrt(1 - beta**2)
    strategy_returns = beta * nifty_returns + idio_noise

    # Cumulative P&L
    cum_capital = capital
    peak        = capital
    max_dd      = 0.0
    daily_pnl   = []
    trough_day  = 0
    recovery_day = n

    for i, ret in enumerate(strategy_returns):
        pnl = cum_capital * ret
        cum_capital += pnl
        daily_pnl.append(pnl)

        if cum_capital > peak:
            peak = cum_capital
            if trough_day > 0:
                recovery_day = i
                trough_day   = 0
        else:
            dd = (peak - cum_capital) / peak * 100
            if dd > max_dd:
                max_dd    = dd
                trough_day = i

    total_return = (cum_capital - capital) / capital * 100
    recovery_days = recovery_day if trough_day > 0 else 0

    # CVaR of daily P&L
    cvar_report = historical_cvar([p / capital * 100 for p in daily_pnl], 0.95)

    # Sharpe in crisis
    rets = np.array(daily_pnl) / capital
    sharpe = (rets.mean() / (rets.std() + 1e-9)) * np.sqrt(252) if len(rets) > 1 else 0.0

    survived = max_dd <= max_dd_limit

    logger.info(
        f"Stress {scenario['name']}: total={total_return:.1f}% "
        f"max_dd={max_dd:.1f}% cvar95={cvar_report.cvar:.2f}% "
        f"survived={'✓' if survived else '✗'}"
    )

    return ScenarioResult(
        scenario_name=scenario["name"],
        strategy_total_pct=round(total_return, 2),
        max_drawdown_pct=round(max_dd, 2),
        recovery_days=recovery_days,
        daily_pnl=daily_pnl,
        cvar_95=round(cvar_report.cvar, 3),
        sharpe_in_crisis=round(float(sharpe), 3),
        survived=survived,
        description=scenario["description"],
    )
