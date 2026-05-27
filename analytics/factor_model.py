"""
Factor Risk Decomposition — Fama-French + India-specific sectors.

What this gives you:
- Portfolio return = α (pure skill) + β_market * R_market + β_sector * R_sector + ε
- Identify HOW MUCH of your P&L is from market (luck) vs stock-picking (skill)
- Detect when you're over-exposed to IT/Banking/FMCG sectors

India-specific factors:
1. Market (Nifty 50)             — systematic market risk
2. Banking (Nifty Bank)          — rate-sensitive, largest weight in Nifty
3. IT (Nifty IT)                 — FX-sensitive, export-oriented
4. FMCG (Nifty FMCG)            — defensive, low-beta
5. Auto (Nifty Auto)             — capex/credit cycle proxy
6. Size (Nifty Midcap vs Nifty)  — small-cap premium
7. Momentum (trailing 12-1 month)— cross-sectional momentum factor

Usage:
    fm = FactorModel()
    fm.fit(portfolio_returns, factor_returns)
    print(fm.alpha, fm.factor_loadings, fm.r_squared)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from utils.logger import get_logger

logger = get_logger("factor_model")


# NSE indices to use as factors (Upstox instrument keys)
INDIA_FACTOR_KEYS = {
    "market":  "NSE_INDEX|Nifty 50",
    "banking": "NSE_INDEX|Nifty Bank",
    "it":      "NSE_INDEX|Nifty IT",
    "fmcg":    "NSE_INDEX|Nifty FMCG",
    "auto":    "NSE_INDEX|Nifty Auto",
    "midcap":  "NSE_INDEX|NIFTY MIDCAP 150",
}


@dataclass
class FactorExposure:
    """Factor regression results for one strategy or portfolio."""
    alpha:           float                  # annualised alpha (skill return)
    factor_loadings: Dict[str, float]       # β per factor
    t_stats:         Dict[str, float]       # t-statistic per factor
    r_squared:       float                  # explained variance
    residual_vol:    float                  # idiosyncratic risk (annualised)
    information_ratio: float                # alpha / residual_vol
    n_obs:           int


@dataclass
class PortfolioFactorReport:
    """Full portfolio factor decomposition report."""
    total_return:     float
    alpha_return:     float                 # factor-adjusted alpha
    factor_returns:   Dict[str, float]      # return attributed to each factor
    exposures:        FactorExposure
    sector_drift:     Dict[str, float]      # current sector over/under-weight
    hedge_suggestion: Optional[str] = None  # which factor to hedge


class FactorModel:
    """
    Multi-factor risk model for Indian equity portfolios.

    Regression: R_p = α + Σ β_i * F_i + ε
    """

    ANNUALISE = 252

    def __init__(self, factors: Optional[List[str]] = None):
        self.factors = factors or list(INDIA_FACTOR_KEYS.keys())
        self._model: Optional[Ridge] = None
        self._factor_returns: Optional[pd.DataFrame] = None
        self._exposure: Optional[FactorExposure] = None

    def fit(
        self,
        portfolio_returns: pd.Series,
        factor_returns: pd.DataFrame,
    ) -> FactorExposure:
        """
        Fit factor model via OLS regression.

        Args:
            portfolio_returns: daily returns of strategy/portfolio
            factor_returns: DataFrame with one column per factor, same index

        Returns:
            FactorExposure with alpha, betas, t-stats, R²
        """
        common = portfolio_returns.align(factor_returns, join="inner")
        y = common[0].values
        X = common[1].values

        if len(y) < 20:
            logger.warning("Factor model: fewer than 20 observations")
            return self._empty_exposure()

        # Add intercept manually
        X_aug = np.column_stack([np.ones(len(X)), X])
        try:
            from numpy.linalg import lstsq
            coefs, _, _, _ = lstsq(X_aug, y, rcond=None)
        except Exception as e:
            logger.error(f"Factor regression failed: {e}")
            return self._empty_exposure()

        alpha_daily   = coefs[0]
        betas         = coefs[1:]
        y_pred        = X_aug @ coefs
        residuals     = y - y_pred
        ss_res        = np.sum(residuals**2)
        ss_tot        = np.sum((y - y.mean())**2)
        r2            = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # T-statistics
        n, k        = len(y), len(coefs)
        sigma_sq    = ss_res / (n - k)
        var_coefs   = np.diag(np.linalg.pinv(X_aug.T @ X_aug) * sigma_sq)
        se_coefs    = np.sqrt(np.clip(var_coefs, 0, None))
        t_stats_all = coefs / (se_coefs + 1e-12)

        alpha_annual  = alpha_daily * self.ANNUALISE
        resid_vol_ann = float(np.std(residuals) * np.sqrt(self.ANNUALISE))
        ir            = alpha_annual / resid_vol_ann if resid_vol_ann > 0 else 0.0

        factor_cols = list(common[1].columns) if hasattr(common[1], "columns") else self.factors[:len(betas)]

        self._exposure = FactorExposure(
            alpha=round(alpha_annual, 6),
            factor_loadings=dict(zip(factor_cols, betas.round(4).tolist())),
            t_stats=dict(zip(factor_cols, t_stats_all[1:].round(3).tolist())),
            r_squared=round(r2, 4),
            residual_vol=round(resid_vol_ann, 4),
            information_ratio=round(ir, 3),
            n_obs=len(y),
        )

        logger.info(
            f"FactorModel: α={alpha_annual:.4%}/yr IR={ir:.2f} R²={r2:.3f} "
            f"betas={dict(zip(factor_cols, betas.round(3)))}"
        )

        return self._exposure

    def decompose_return(
        self,
        portfolio_return: float,
        current_factor_returns: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Decompose a single-period return into factor contributions + alpha.
        Returns dict: {factor_name: attributed_return, 'alpha': alpha, 'residual': ε}
        """
        if self._exposure is None:
            return {"alpha": portfolio_return, "residual": 0.0}

        decomp: Dict[str, float] = {}
        factor_total = 0.0
        for factor, beta in self._exposure.factor_loadings.items():
            f_ret = current_factor_returns.get(factor, 0.0)
            contribution = beta * f_ret
            decomp[factor] = round(contribution, 6)
            factor_total  += contribution

        decomp["alpha"]    = round(self._exposure.alpha / self.ANNUALISE, 6)
        decomp["residual"] = round(portfolio_return - factor_total - decomp["alpha"], 6)
        return decomp

    def sector_exposure(self, positions: Dict[str, float]) -> Dict[str, float]:
        """
        Compute current portfolio sector exposure as % of total capital.
        positions: {symbol: market_value}
        Returns: {sector: total_exposure_pct}
        """
        # Simple sector classification for Nifty50
        SECTOR_MAP = {
            "HDFCBANK": "banking", "ICICIBANK": "banking", "KOTAKBANK": "banking",
            "AXISBANK": "banking", "SBIN": "banking", "BAJFINANCE": "banking",
            "TCS": "it", "INFY": "it", "WIPRO": "it", "HCLTECH": "it", "TECHM": "it",
            "HINDUNILVR": "fmcg", "ITC": "fmcg", "NESTLEIND": "fmcg",
            "MARUTISUZUKI": "auto", "TATAMOTORS": "auto", "M&M": "auto",
            "RELIANCE": "energy", "ONGC": "energy", "BPCL": "energy",
            "SUNPHARMA": "pharma", "DRREDDY": "pharma", "CIPLA": "pharma",
        }
        total = sum(abs(v) for v in positions.values()) or 1.0
        sector_exp: Dict[str, float] = {}
        for sym, val in positions.items():
            sector = SECTOR_MAP.get(sym.upper(), "other")
            sector_exp[sector] = sector_exp.get(sector, 0.0) + abs(val) / total
        return {k: round(v, 4) for k, v in sector_exp.items()}

    def hedge_suggestion(
        self, positions: Dict[str, float], max_sector_pct: float = 0.35,
    ) -> Optional[str]:
        """
        Returns Nifty sub-index to short-hedge if sector concentration > threshold.
        """
        exposure = self.sector_exposure(positions)
        for sector, exp in exposure.items():
            if exp > max_sector_pct:
                nifty_hedge = {
                    "banking": "Nifty Bank futures (short)",
                    "it":      "Nifty IT futures (short)",
                    "fmcg":    "Nifty FMCG futures (short)",
                    "auto":    "Nifty Auto futures (short)",
                }.get(sector)
                if nifty_hedge:
                    logger.warning(
                        f"Sector concentration: {sector}={exp:.1%} > {max_sector_pct:.0%} "
                        f"→ consider hedging via {nifty_hedge}"
                    )
                    return nifty_hedge
        return None

    def _empty_exposure(self) -> FactorExposure:
        return FactorExposure(
            alpha=0.0, factor_loadings={}, t_stats={},
            r_squared=0.0, residual_vol=0.0,
            information_ratio=0.0, n_obs=0,
        )
