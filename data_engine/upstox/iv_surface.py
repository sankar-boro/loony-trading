"""
IV Surface builder for NSE options.

Builds a volatility surface from the live Upstox option chain,
computes IV rank/percentile, term structure, and skew metrics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from feature_engine.greeks import implied_volatility, iv_rank, iv_percentile, Greeks
from utils.logger import get_logger

logger = get_logger("iv_surface")

RISK_FREE_RATE = 0.065          # RBI repo rate proxy
TRADING_DAYS_PER_YEAR = 252


@dataclass
class IVPoint:
    strike: float
    expiry: str                 # "YYYY-MM-DD"
    days_to_expiry: int
    call_iv: float
    put_iv: float
    mid_iv: float               # average of call and put IV
    call_price: float
    put_price: float
    call_delta: float
    put_delta: float
    call_oi: int = 0
    put_oi: int = 0


@dataclass
class IVSmile:
    """IV smile for a single expiry."""
    expiry: str
    days_to_expiry: int
    atm_iv: float
    skew: float                 # 25-delta risk reversal (call IV - put IV)
    butterfly: float            # 25-delta butterfly (wing avg - ATM)
    points: List[IVPoint] = field(default_factory=list)

    @property
    def atm_vega_weighted_skew(self) -> float:
        """Normalise skew by ATM IV."""
        return self.skew / self.atm_iv if self.atm_iv > 0 else 0.0


@dataclass
class IVSurface:
    """Full volatility surface across all expiries."""
    underlying: str
    spot: float
    timestamp: datetime
    smiles: Dict[str, IVSmile] = field(default_factory=dict)   # expiry -> smile
    iv_history: List[float] = field(default_factory=list)      # ATM IV history for rank/pct

    # ── Accessors ──────────────────────────────────────────────────────────────

    def nearest_expiry(self) -> Optional[IVSmile]:
        smiles = sorted(self.smiles.values(), key=lambda s: s.days_to_expiry)
        return smiles[0] if smiles else None

    def atm_iv(self, expiry: Optional[str] = None) -> float:
        if expiry:
            return self.smiles[expiry].atm_iv if expiry in self.smiles else float("nan")
        smile = self.nearest_expiry()
        return smile.atm_iv if smile else float("nan")

    def term_structure(self) -> List[Tuple[int, float]]:
        """Returns [(days_to_expiry, atm_iv)] sorted by expiry."""
        return sorted(
            [(s.days_to_expiry, s.atm_iv) for s in self.smiles.values()],
            key=lambda x: x[0],
        )

    def iv_rank_current(self) -> float:
        return iv_rank(self.atm_iv(), self.iv_history)

    def iv_percentile_current(self) -> float:
        return iv_percentile(self.atm_iv(), self.iv_history)

    def is_high_iv(self, rank_threshold: float = 70.0) -> bool:
        """True when IV rank > threshold → good time to SELL options."""
        return self.iv_rank_current() > rank_threshold

    def is_low_iv(self, rank_threshold: float = 30.0) -> bool:
        """True when IV rank < threshold → good time to BUY options."""
        return self.iv_rank_current() < rank_threshold

    def max_pain(self, expiry: Optional[str] = None) -> Optional[float]:
        smile = self.smiles.get(expiry) if expiry else self.nearest_expiry()
        if not smile or not smile.points:
            return None
        return _calculate_max_pain(smile.points, self.spot)

    def pcr(self, expiry: Optional[str] = None) -> float:
        """Put/Call ratio by OI."""
        smile = self.smiles.get(expiry) if expiry else self.nearest_expiry()
        if not smile:
            return 1.0
        total_put_oi = sum(p.put_oi for p in smile.points)
        total_call_oi = sum(p.call_oi for p in smile.points)
        return total_put_oi / total_call_oi if total_call_oi > 0 else 1.0

    def summary(self) -> dict:
        atm = self.atm_iv()
        return {
            "underlying": self.underlying,
            "spot": self.spot,
            "atm_iv": round(atm * 100, 2),
            "iv_rank": round(self.iv_rank_current(), 1),
            "iv_percentile": round(self.iv_percentile_current(), 1),
            "pcr": round(self.pcr(), 3),
            "max_pain": self.max_pain(),
            "term_structure": [(d, round(iv * 100, 2)) for d, iv in self.term_structure()],
            "regime": "HIGH_IV" if self.is_high_iv() else ("LOW_IV" if self.is_low_iv() else "NORMAL_IV"),
        }


# ── Builder ────────────────────────────────────────────────────────────────────

def build_iv_surface(
    underlying: str,
    spot: float,
    option_chain: pd.DataFrame,
    iv_history: Optional[List[float]] = None,
) -> IVSurface:
    """
    Build an IVSurface from an option chain DataFrame.

    Expected DataFrame columns (from Upstox get_option_chain):
        strike, expiry, call_ltp, put_ltp, call_oi, put_oi,
        call_volume, put_volume, call_iv, put_iv  (optional — we compute if missing)
    """
    surface = IVSurface(
        underlying=underlying,
        spot=spot,
        timestamp=datetime.now(),
        iv_history=iv_history or [],
    )

    if option_chain.empty:
        return surface

    today = date.today()

    for expiry_str, grp in option_chain.groupby("expiry"):
        try:
            exp_date = pd.to_datetime(expiry_str).date()
        except Exception:
            continue
        dte = max((exp_date - today).days, 0)
        if dte > 90:        # ignore far-dated for now
            continue

        points: List[IVPoint] = []

        for _, row in grp.iterrows():
            K = float(row["strike"])
            call_px = float(row.get("call_ltp", 0) or 0)
            put_px  = float(row.get("put_ltp", 0) or 0)
            call_oi = int(row.get("call_oi", 0) or 0)
            put_oi  = int(row.get("put_oi", 0) or 0)

            T = max(dte, 1)
            call_iv_ = float(row.get("call_iv", 0) or 0)
            put_iv_  = float(row.get("put_iv", 0) or 0)

            # Compute IV if not provided or zero
            if call_iv_ <= 0 and call_px > 0:
                call_iv_ = implied_volatility(call_px, spot, K, T, RISK_FREE_RATE, "call")
            if put_iv_ <= 0 and put_px > 0:
                put_iv_ = implied_volatility(put_px, spot, K, T, RISK_FREE_RATE, "put")

            call_iv_ = call_iv_ if math.isfinite(call_iv_) else float("nan")
            put_iv_  = put_iv_  if math.isfinite(put_iv_)  else float("nan")

            mid_iv = np.nanmean([v for v in [call_iv_, put_iv_] if not math.isnan(v)])

            # Delta
            call_delta = 0.5
            put_delta  = -0.5
            iv_for_greeks = mid_iv if not math.isnan(mid_iv) else 0.2
            try:
                cg = Greeks(spot, K, T, RISK_FREE_RATE, iv_for_greeks, "call")
                call_delta = cg.delta
                pg = Greeks(spot, K, T, RISK_FREE_RATE, iv_for_greeks, "put")
                put_delta = pg.delta
            except Exception:
                pass

            points.append(IVPoint(
                strike=K,
                expiry=str(expiry_str),
                days_to_expiry=dte,
                call_iv=call_iv_ if not math.isnan(call_iv_) else 0.0,
                put_iv=put_iv_   if not math.isnan(put_iv_)  else 0.0,
                mid_iv=mid_iv    if not math.isnan(mid_iv)   else 0.0,
                call_price=call_px,
                put_price=put_px,
                call_delta=call_delta,
                put_delta=put_delta,
                call_oi=call_oi,
                put_oi=put_oi,
            ))

        if not points:
            continue

        # ATM IV: interpolate around spot
        atm_iv = _atm_iv(points, spot)

        # 25-delta skew and butterfly
        skew, butterfly = _compute_skew_butterfly(points, spot)

        surface.smiles[str(expiry_str)] = IVSmile(
            expiry=str(expiry_str),
            days_to_expiry=dte,
            atm_iv=atm_iv,
            skew=skew,
            butterfly=butterfly,
            points=points,
        )

    return surface


def _atm_iv(points: List[IVPoint], spot: float) -> float:
    """Interpolate ATM IV from points closest to spot."""
    if not points:
        return 0.0
    sorted_pts = sorted(points, key=lambda p: abs(p.strike - spot))
    best = sorted_pts[0]
    if best.mid_iv > 0:
        return best.mid_iv
    # fallback: average call and put IV
    ivs = [p.mid_iv for p in sorted_pts[:3] if p.mid_iv > 0]
    return float(np.mean(ivs)) if ivs else 0.0


def _compute_skew_butterfly(
    points: List[IVPoint], spot: float,
) -> Tuple[float, float]:
    """
    25-delta risk reversal (skew) and butterfly.
    Skew = 25d call IV − 25d put IV
    Butterfly = 0.5*(25d call IV + 25d put IV) − ATM IV
    """
    # Find points closest to ±25 delta
    call_pts = sorted(points, key=lambda p: abs(p.call_delta - 0.25))
    put_pts  = sorted(points, key=lambda p: abs(p.put_delta + 0.25))
    atm_pts  = sorted(points, key=lambda p: abs(p.strike - spot))

    c25_iv = call_pts[0].call_iv if call_pts and call_pts[0].call_iv > 0 else 0.0
    p25_iv = put_pts[0].put_iv   if put_pts  and put_pts[0].put_iv  > 0 else 0.0
    atm_iv = atm_pts[0].mid_iv   if atm_pts  and atm_pts[0].mid_iv  > 0 else 0.0

    skew      = c25_iv - p25_iv
    butterfly = 0.5 * (c25_iv + p25_iv) - atm_iv if atm_iv > 0 else 0.0
    return skew, butterfly


def _calculate_max_pain(points: List[IVPoint], spot: float) -> float:
    """
    Max pain = strike where total option writer loss is minimised.
    i.e. the strike where total OI pain for buyers is maximised.
    """
    if not points:
        return spot

    strikes = sorted(set(p.strike for p in points))
    point_map = {p.strike: p for p in points}

    min_pain = float("inf")
    max_pain_strike = spot

    for test_strike in strikes:
        pain = 0.0
        for p in points:
            # Call writers lose when expiry > strike
            call_pain = max(test_strike - p.strike, 0.0) * p.call_oi
            # Put writers lose when expiry < strike
            put_pain  = max(p.strike - test_strike, 0.0) * p.put_oi
            pain += call_pain + put_pain
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = test_strike

    return max_pain_strike
