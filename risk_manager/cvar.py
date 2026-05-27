"""
CVaR (Conditional Value at Risk) / Expected Shortfall.

Why CVaR > Max Drawdown:
- Max drawdown is a single historical observation — lucky or unlucky path
- CVaR is the EXPECTED LOSS given we're in the worst X% of scenarios
- CVaR is sub-additive (portfolio CVaR ≤ sum of individual CVaRs) — makes it
  meaningful for portfolio-level risk management
- Standard at all risk-managed hedge funds and prop desks
- RBI/SEBI use CVaR for margin calculations on Indian exchanges

Three methods implemented:
1. Historical Simulation — use actual P&L history, no distributional assumption
2. Parametric (Gaussian) — assume Normal distribution, fast analytical formula
3. Cornish-Fisher expansion — adjusts for fat tails using skewness + kurtosis
   (financial returns are never Gaussian; CF captures the real tail better)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import scipy.stats as stats


@dataclass
class CVaRReport:
    confidence: float           # e.g. 0.95
    var:        float           # Value at Risk (loss at confidence percentile)
    cvar:       float           # Conditional VaR (expected loss beyond VaR)
    method:     str
    n_obs:      int
    mean_loss:  float
    std_loss:   float
    skewness:   float
    kurtosis:   float           # excess kurtosis

    @property
    def cvar_pct(self) -> float:
        """CVaR as % of portfolio (if losses are in ₹ terms)."""
        return self.cvar

    def __str__(self) -> str:
        return (
            f"CVaR({self.confidence:.0%}, {self.method}): "
            f"VaR={self.var:.2f} CVaR={self.cvar:.2f} "
            f"[n={self.n_obs} μ={self.mean_loss:.3f} σ={self.std_loss:.3f} "
            f"skew={self.skewness:.2f} kurt={self.kurtosis:.2f}]"
        )


def historical_cvar(
    returns: Sequence[float],
    confidence: float = 0.95,
) -> CVaRReport:
    """
    Historical simulation CVaR.
    Most accurate when you have sufficient history.
    No distributional assumption.

    Convention: returns are PnL (positive = profit, negative = loss).
    CVaR is reported as a POSITIVE number (magnitude of expected loss).
    """
    r = np.array(returns, dtype=float)
    n = len(r)
    losses = -r   # flip sign: loss is positive

    var_level = np.percentile(losses, confidence * 100)
    tail      = losses[losses >= var_level]
    cvar      = float(np.mean(tail)) if len(tail) > 0 else float(var_level)

    return CVaRReport(
        confidence=confidence,
        var=float(var_level),
        cvar=cvar,
        method="historical",
        n_obs=n,
        mean_loss=float(np.mean(losses)),
        std_loss=float(np.std(losses)),
        skewness=float(stats.skew(losses)),
        kurtosis=float(stats.kurtosis(losses)),
    )


def parametric_cvar(
    returns: Sequence[float],
    confidence: float = 0.95,
) -> CVaRReport:
    """
    Parametric (Gaussian) CVaR — fast analytical formula.
    CVaR = μ + σ * φ(z_α) / (1 - α)
    where φ is standard normal PDF, z_α is the α-quantile.
    """
    r      = np.array(returns, dtype=float)
    losses = -r
    mu     = float(np.mean(losses))
    sigma  = float(np.std(losses))

    alpha    = confidence
    z_alpha  = stats.norm.ppf(alpha)
    phi_z    = stats.norm.pdf(z_alpha)
    var      = mu + sigma * z_alpha
    cvar     = mu + sigma * phi_z / (1.0 - alpha)

    return CVaRReport(
        confidence=confidence,
        var=float(var),
        cvar=float(cvar),
        method="parametric",
        n_obs=len(r),
        mean_loss=mu,
        std_loss=sigma,
        skewness=float(stats.skew(losses)),
        kurtosis=float(stats.kurtosis(losses)),
    )


def cornish_fisher_cvar(
    returns: Sequence[float],
    confidence: float = 0.95,
) -> CVaRReport:
    """
    Cornish-Fisher CVaR — adjusts Gaussian for skewness and excess kurtosis.
    Best for financial returns which have fat tails and negative skew.

    Adjusted quantile:
    z_CF = z + (z² - 1)/6 * S + (z³ - 3z)/24 * K - (2z³ - 5z)/36 * S²
    where S = skewness, K = excess kurtosis
    """
    r      = np.array(returns, dtype=float)
    losses = -r
    mu     = float(np.mean(losses))
    sigma  = float(np.std(losses))
    S      = float(stats.skew(losses))
    K      = float(stats.kurtosis(losses))   # excess kurtosis

    alpha   = confidence
    z       = stats.norm.ppf(alpha)

    # Cornish-Fisher expansion
    z_cf = (z
            + (z**2 - 1) / 6 * S
            + (z**3 - 3*z) / 24 * K
            - (2*z**3 - 5*z) / 36 * S**2)

    var  = mu + sigma * z_cf

    # CVaR: integrate tail
    z_cvar = stats.norm.ppf(alpha)
    phi_z  = stats.norm.pdf(z_cvar)
    # Approximate CVaR correction for fat tails
    cvar = (mu + sigma * phi_z / (1.0 - alpha)
            * (1.0 + K / 6.0 * (z_cvar**2 - 1) + S / 2.0 * z_cvar))

    return CVaRReport(
        confidence=confidence,
        var=float(var),
        cvar=float(cvar),
        method="cornish_fisher",
        n_obs=len(r),
        mean_loss=mu,
        std_loss=sigma,
        skewness=S,
        kurtosis=K,
    )


def full_cvar_report(
    returns: Sequence[float],
    confidence: float = 0.95,
) -> Dict[str, CVaRReport]:
    """Run all three methods and return comparison dict."""
    return {
        "historical":    historical_cvar(returns, confidence),
        "parametric":    parametric_cvar(returns, confidence),
        "cornish_fisher": cornish_fisher_cvar(returns, confidence),
    }


# ── Portfolio-level CVaR integration ─────────────────────────────────────────

class CVaRRiskManager:
    """
    CVaR-based position limit enforcer.
    Integrates with the existing RiskManager as an additional layer.

    Rules:
    1. Portfolio CVaR95 ≤ max_cvar_pct of capital (default 3%)
    2. Single-strategy CVaR95 ≤ max_strategy_cvar_pct (default 1.5%)
    3. If portfolio CVaR breach → reduce all position sizes
    4. If strategy CVaR breach → disable that strategy
    """

    def __init__(
        self,
        capital: float,
        max_portfolio_cvar_pct: float = 0.03,    # 3% of capital
        max_strategy_cvar_pct: float  = 0.015,   # 1.5%
        min_history: int = 20,
        confidence: float = 0.95,
    ):
        self.capital               = capital
        self.max_portfolio_cvar    = capital * max_portfolio_cvar_pct
        self.max_strategy_cvar     = capital * max_strategy_cvar_pct
        self.min_history           = min_history
        self.confidence            = confidence
        self._portfolio_pnl:  List[float] = []
        self._strategy_pnl:   Dict[str, List[float]] = {}

    def record_pnl(self, pnl: float, strategy: Optional[str] = None) -> None:
        """Record a realised P&L observation."""
        self._portfolio_pnl.append(pnl)
        if strategy:
            self._strategy_pnl.setdefault(strategy, []).append(pnl)

    def portfolio_cvar(self) -> Optional[CVaRReport]:
        if len(self._portfolio_pnl) < self.min_history:
            return None
        return cornish_fisher_cvar(self._portfolio_pnl, self.confidence)

    def strategy_cvar(self, strategy: str) -> Optional[CVaRReport]:
        pnl = self._strategy_pnl.get(strategy, [])
        if len(pnl) < self.min_history:
            return None
        return cornish_fisher_cvar(pnl, self.confidence)

    def portfolio_size_multiplier(self) -> float:
        """
        Returns size multiplier for all new positions.
        < 1.0 when portfolio CVaR is elevated.
        """
        report = self.portfolio_cvar()
        if report is None:
            return 1.0
        ratio = report.cvar / self.max_portfolio_cvar
        if ratio <= 1.0:
            return 1.0
        # Reduce size proportionally: 2x CVaR → 0.5x size
        return float(np.clip(1.0 / ratio, 0.2, 1.0))

    def is_strategy_disabled(self, strategy: str) -> bool:
        """Returns True if strategy has breached its CVaR limit."""
        report = self.strategy_cvar(strategy)
        if report is None:
            return False
        return report.cvar > self.max_strategy_cvar

    def risk_summary(self) -> dict:
        pcvar = self.portfolio_cvar()
        return {
            "portfolio_cvar": round(pcvar.cvar, 2) if pcvar else None,
            "portfolio_var":  round(pcvar.var, 2)  if pcvar else None,
            "cvar_limit":     round(self.max_portfolio_cvar, 2),
            "size_multiplier": round(self.portfolio_size_multiplier(), 4),
            "strategies_at_risk": [
                s for s in self._strategy_pnl
                if self.is_strategy_disabled(s)
            ],
            "obs_count": len(self._portfolio_pnl),
        }
