"""
Kalman Filter for dynamic hedge ratio estimation in pair trading.

Why Kalman over rolling OLS:
- OLS uses a fixed window (e.g. 60 bars) — stale at the edges
- Kalman updates every tick — always optimal given all history
- Kalman tracks UNCERTAINTY — wider confidence intervals = weaker pairs signal
- Kalman handles non-stationary spreads gracefully

State space model:
  Observation:  y_t = β_t * x_t + ε_t       (ε ~ N(0, R))
  Transition:   β_t = β_{t-1} + w_t          (w ~ N(0, Q))

Where:
  y_t = price of asset A at time t
  x_t = price of asset B at time t
  β_t = dynamic hedge ratio (what we're estimating)
  R   = observation noise variance (how noisy prices are)
  Q   = transition noise variance (how fast β changes)

Tuning:
  - Small Q (e.g. 1e-5): hedge ratio changes slowly, more stable, misses fast regime shifts
  - Large Q (e.g. 1e-3): hedge ratio tracks quickly, noisier signals
  - Default Q=1e-4 works well for Indian equity pairs
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class KalmanState:
    """Current state of the Kalman filter."""
    beta: float          # current hedge ratio estimate
    P: float             # estimation variance (uncertainty in beta)
    spread_mean: float   # running Kalman-smoothed spread mean
    spread_var: float    # running spread variance estimate


class KalmanHedgeRatio:
    """
    Online Kalman filter for tracking dynamic hedge ratio β_t.

    After each update, provides:
    - beta:         current hedge ratio
    - spread:       current spread = y - beta * x
    - z_score:      how many std devs current spread is from its mean
    - uncertainty:  estimation uncertainty (P) — use to size position
    """

    def __init__(
        self,
        delta: float = 1e-4,    # transition noise variance (Q = delta * I)
        vt: float = 1e-3,       # initial observation noise estimate
    ):
        self.delta  = delta     # controls how fast beta can change
        self.vt     = vt        # observation noise
        self.theta  = np.zeros(2)           # state: [beta, alpha] (hedge ratio + intercept)
        self.P      = np.eye(2) * 1.0       # state covariance
        self.R      = np.array([[vt]])      # observation noise covariance
        self.Q      = delta * np.eye(2)     # transition noise covariance

        # Running spread statistics (for z-score)
        self._spread_sum:   float = 0.0
        self._spread_sq:    float = 0.0
        self._n:            int   = 0
        self._recent_spreads: List[float] = []
        self._window: int = 30              # window for spread z-score

    def update(self, y: float, x: float) -> Tuple[float, float, float]:
        """
        Process one observation pair (y, x) and return updated estimates.

        Returns:
            (beta, spread, z_score)
        """
        F = np.array([[x, 1.0]])    # observation matrix [x, 1] for [beta, alpha]
        H = F                       # same as F here

        # Predict
        theta_pred = self.theta                         # state transition = identity
        P_pred     = self.P + self.Q                    # predict covariance

        # Innovation (residual)
        y_hat  = (H @ theta_pred)[0]
        innov  = y - y_hat
        S      = (H @ P_pred @ H.T + self.R)[0, 0]     # innovation covariance

        # Kalman gain
        K = (P_pred @ H.T / S).flatten()

        # Update state
        self.theta = theta_pred + K * innov
        self.P     = (np.eye(2) - np.outer(K, H)) @ P_pred

        beta   = float(self.theta[0])
        spread = y - beta * x

        # Z-score of spread using rolling window
        self._recent_spreads.append(spread)
        if len(self._recent_spreads) > self._window:
            self._recent_spreads.pop(0)

        if len(self._recent_spreads) >= 5:
            mu    = float(np.mean(self._recent_spreads))
            sigma = float(np.std(self._recent_spreads))
            z     = (spread - mu) / sigma if sigma > 1e-10 else 0.0
        else:
            z = 0.0

        return beta, spread, z

    def fit(self, y: pd.Series, x: pd.Series) -> pd.DataFrame:
        """
        Fit Kalman filter on historical price series.
        Returns DataFrame with columns: beta, alpha, spread, z_score, uncertainty.
        """
        records = []
        for yi, xi in zip(y.values, x.values):
            beta, spread, z = self.update(float(yi), float(xi))
            records.append({
                "beta":        beta,
                "alpha":       float(self.theta[1]),
                "spread":      spread,
                "z_score":     z,
                "uncertainty": float(self.P[0, 0]),   # variance of beta estimate
            })
        return pd.DataFrame(records, index=y.index)

    @property
    def beta(self) -> float:
        return float(self.theta[0])

    @property
    def alpha(self) -> float:
        return float(self.theta[1])

    @property
    def uncertainty(self) -> float:
        """Variance of current beta estimate. Higher = less certain."""
        return float(self.P[0, 0])

    def reset(self) -> None:
        self.theta = np.zeros(2)
        self.P     = np.eye(2) * 1.0
        self._recent_spreads.clear()
        self._n = 0


class KalmanSpreadTracker:
    """
    Full spread tracking: hedge ratio + spread mean-reversion.
    Wraps KalmanHedgeRatio and adds cointegration checking.
    """

    def __init__(self, symbol_a: str, symbol_b: str, delta: float = 1e-4):
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b
        self.kf       = KalmanHedgeRatio(delta=delta)
        self._fitted  = False

    def fit(self, price_a: pd.Series, price_b: pd.Series) -> pd.DataFrame:
        self._fitted = True
        return self.kf.fit(price_a, price_b)

    def update(
        self, price_a: float, price_b: float,
    ) -> Tuple[float, float, float, float]:
        """
        Update with latest prices.
        Returns (beta, spread, z_score, uncertainty).
        """
        beta, spread, z = self.kf.update(price_a, price_b)
        return beta, spread, z, self.kf.uncertainty

    def is_cointegrated(
        self, price_a: pd.Series, price_b: pd.Series, p_value: float = 0.05,
    ) -> bool:
        """Engle-Granger cointegration test at the 1 / 5 / 10 % level."""
        return engle_granger_stat(price_a, price_b) < coint_critical_value(p_value)

    def half_life(self, spread: pd.Series) -> float:
        """Ornstein-Uhlenbeck half-life of mean reversion, in bars."""
        return half_life(spread)


# ── Cointegration statistics (numpy only) ────────────────────────────────────
# MacKinnon (1991/2010) asymptotic critical values of the Engle-Granger test
# for two series with a constant. A t-statistic below the value rejects "no
# cointegration" at that level.
_EG_CRITICAL = {0.01: -3.90, 0.05: -3.34, 0.10: -3.04}


def coint_critical_value(level: float = 0.05) -> float:
    """Critical value for the nearest supported level (1, 5 or 10 %)."""
    return _EG_CRITICAL[min(_EG_CRITICAL, key=lambda k: abs(k - level))]


def _ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef, y - X @ coef


def engle_granger_stat(price_a, price_b, lags: int = 1) -> float:
    """Augmented Dickey-Fuller t-statistic of the residuals of a ~ b (with
    a constant). More negative = more strongly mean-reverting; compare with
    coint_critical_value(). NaN-safe; returns +inf when undefined."""
    a = np.asarray(price_a, dtype=float)
    b = np.asarray(price_b, dtype=float)
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok], b[ok]
    if len(a) < 30:
        return float("inf")
    _, e = _ols(a, np.column_stack([b, np.ones_like(b)]))
    de = np.diff(e)
    rows = len(de) - lags
    if rows < 20:
        return float("inf")
    cols = [e[lags:-1]] + [de[lags - k - 1:len(de) - k - 1] for k in range(lags)]
    X = np.column_stack(cols)
    y = de[lags:]
    coef, resid = _ols(y, X)
    dof = rows - X.shape[1]
    sigma2 = resid @ resid / dof
    cov = sigma2 * np.linalg.pinv(X.T @ X)
    se = np.sqrt(cov[0, 0])
    return float(coef[0] / se) if se > 0 else float("inf")


def half_life(spread) -> float:
    """Ornstein-Uhlenbeck half-life from an AR(1) fit of the spread changes:
    -ln 2 / λ, or +inf if the spread is not mean-reverting."""
    s = pd.Series(spread).dropna().to_numpy(dtype=float)
    if len(s) < 10:
        return float("inf")
    coef, _ = _ols(np.diff(s), np.column_stack([s[:-1], np.ones(len(s) - 1)]))
    lam = coef[0]
    return float(-np.log(2) / lam) if lam < -1e-6 else float("inf")
