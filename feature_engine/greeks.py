"""
Black-Scholes options Greeks calculator.
Supports European-style options (NSE index options are European).
Equity options on NSE are American — use Black-Scholes as approximation.
"""
from __future__ import annotations
import math
import numpy as np
from typing import Literal

OptionType = Literal["call", "put"]


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    """Compute d1, d2 for Black-Scholes. T in years."""
    if T <= 0 or sigma <= 0:
        return 0.0, 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class Greeks:
    """
    All first and second-order Greeks for a single option.

    Parameters
    ----------
    S      : Spot / underlying price
    K      : Strike price
    T      : Time to expiry in calendar days
    r      : Risk-free rate (annualised, e.g. 0.065 for 6.5%)
    sigma  : Implied volatility (annualised, e.g. 0.20 for 20%)
    opt    : "call" or "put"
    """

    __slots__ = (
        "S", "K", "T_days", "T", "r", "sigma", "opt",
        "d1", "d2",
        "price", "delta", "gamma", "theta", "vega", "rho",
        "vanna", "charm", "speed", "color", "vomma",
    )

    def __init__(
        self,
        S: float,
        K: float,
        T: float,      # calendar days to expiry
        r: float,
        sigma: float,
        opt: OptionType = "call",
    ):
        self.S = S
        self.K = K
        self.T_days = T
        self.T = max(T / 365.0, 1e-6)
        self.r = r
        self.sigma = max(sigma, 1e-6)
        self.opt = opt

        self.d1, self.d2 = _d1_d2(S, K, self.T, r, self.sigma)
        self._compute()

    def _compute(self) -> None:
        S, K, T, r, sigma = self.S, self.K, self.T, self.r, self.sigma
        d1, d2 = self.d1, self.d2
        nd1 = _norm_pdf(d1)
        sqrt_T = math.sqrt(T)

        if self.opt == "call":
            Nd1  = _norm_cdf(d1)
            Nd2  = _norm_cdf(d2)
            Nd1_ = _norm_cdf(-d1)
            self.price = S * Nd1 - K * math.exp(-r * T) * Nd2
            self.delta = Nd1
            self.rho   = K * T * math.exp(-r * T) * Nd2 / 100
            self.theta = (
                -(S * nd1 * sigma) / (2 * sqrt_T)
                - r * K * math.exp(-r * T) * Nd2
            ) / 365
        else:
            Nd1_ = _norm_cdf(-d1)
            Nd2_ = _norm_cdf(-d2)
            self.price = K * math.exp(-r * T) * Nd2_ - S * Nd1_
            self.delta = Nd1_ - 1.0
            self.rho   = -K * T * math.exp(-r * T) * Nd2_ / 100
            self.theta = (
                -(S * nd1 * sigma) / (2 * sqrt_T)
                + r * K * math.exp(-r * T) * Nd2_
            ) / 365

        # Gamma is same for call and put
        self.gamma = nd1 / (S * sigma * sqrt_T)

        # Vega (per 1% move in IV)
        self.vega = S * nd1 * sqrt_T / 100

        # Second-order
        self.vanna  = -nd1 * d2 / sigma                         # dDelta/dVol
        self.charm  = -nd1 * (2 * r * T - d2 * sigma * sqrt_T) / (2 * T * sigma * sqrt_T) / 365
        self.speed  = -self.gamma / S * (d1 / (sigma * sqrt_T) + 1)
        self.color  = -nd1 / (2 * S * T * sigma * sqrt_T) * (
            2 * r * T + 1 - d1 * d2
        ) / 365
        self.vomma  = self.vega * d1 * d2 / sigma

    def intrinsic(self) -> float:
        if self.opt == "call":
            return max(self.S - self.K, 0.0)
        return max(self.K - self.S, 0.0)

    def time_value(self) -> float:
        return max(self.price - self.intrinsic(), 0.0)

    def moneyness(self) -> str:
        if abs(self.S - self.K) / self.K < 0.005:
            return "ATM"
        if (self.opt == "call" and self.S > self.K) or (self.opt == "put" and self.S < self.K):
            return "ITM"
        return "OTM"

    def __repr__(self) -> str:
        return (
            f"Greeks({self.opt.upper()} K={self.K} T={self.T_days:.0f}d "
            f"σ={self.sigma:.1%} | price={self.price:.2f} "
            f"Δ={self.delta:.3f} Γ={self.gamma:.5f} "
            f"Θ={self.theta:.2f}/day Vega={self.vega:.2f})"
        )


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    opt: OptionType = "call",
    tol: float = 1e-5,
    max_iter: int = 100,
) -> float:
    """
    Newton-Raphson IV solver.
    Returns annualised IV or np.nan if it doesn't converge.
    """
    intrinsic = max(S - K, 0.0) if opt == "call" else max(K - S, 0.0)
    if market_price <= intrinsic:
        return float("nan")

    # Initial guess: Brenner-Subrahmanyam approximation
    sigma = math.sqrt(2 * math.pi / max(T / 365.0, 1e-6)) * market_price / S

    for _ in range(max_iter):
        g = Greeks(S, K, T, r, sigma, opt)
        diff = g.price - market_price
        if abs(diff) < tol:
            return sigma
        vega = g.vega * 100  # vega per unit, not per 1%
        if abs(vega) < 1e-10:
            break
        sigma -= diff / vega
        sigma = max(sigma, 1e-6)

    return float("nan")


def iv_rank(current_iv: float, iv_history: list[float] | np.ndarray) -> float:
    """IV Rank: where current IV sits in the 52-week range [0, 100]."""
    if len(iv_history) < 2:
        return 50.0
    iv_min = float(np.min(iv_history))
    iv_max = float(np.max(iv_history))
    if iv_max == iv_min:
        return 100.0 if current_iv > iv_max else (0.0 if current_iv < iv_min else 50.0)
    return float(np.clip((current_iv - iv_min) / (iv_max - iv_min) * 100.0, 0.0, 100.0))


def iv_percentile(current_iv: float, iv_history: list[float] | np.ndarray) -> float:
    """IV Percentile: % of days IV was below current IV over past year."""
    if len(iv_history) == 0:
        return 50.0
    arr = np.asarray(iv_history)
    return float(np.mean(arr < current_iv) * 100.0)


def delta_to_strike(
    S: float, T: float, r: float, sigma: float,
    target_delta: float, opt: OptionType = "call",
) -> float:
    """
    Find the strike corresponding to a target delta.
    Uses Newton-Raphson. Useful for selecting OTM strikes.
    """
    K = S  # initial guess = ATM
    for _ in range(50):
        g = Greeks(S, K, T, r, sigma, opt)
        d = g.delta
        err = d - target_delta
        if abs(err) < 1e-4:
            return K
        # dDelta/dK = -Gamma
        if abs(g.gamma) < 1e-12:
            break
        K = K + err / g.gamma
        K = max(K, 1.0)
    return K
