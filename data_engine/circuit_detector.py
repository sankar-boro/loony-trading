"""
Circuit Breaker Detection for Indian Markets.

SEBI circuit breaker rules (as of 2024):
1. Market-wide (index) circuit breakers — triggered by Nifty/Sensex movement:
   - ±10% move → 45-minute halt (before 1 PM) or 15-min halt (1-2:30 PM)
                → no halt after 2:30 PM
   - ±15% move → 1-hour 45-min halt (before 1 PM) or 45-min halt (1-2 PM)
                → rest-of-day halt after 2 PM
   - ±20% move → rest-of-day halt at any time

2. Stock-level circuit breakers:
   - F&O stocks: ±10% price band (no limit for F&O-listed usually, but applies
     to cash market pre-approval)
   - Non-F&O stocks: ±5%, ±10%, or ±20% bands (set daily by exchanges)
   - 2% additional band for stocks with circuit filters on consecutive days

3. Upper/Lower circuit:
   - Stock hits upper circuit (UC): only buyers, no sellers → illiquid
   - Stock hits lower circuit (LC): only sellers, no buyers → illiquid
   - CRITICAL: open positions in circuited stocks CANNOT be exited

Why this matters for algorithmic trading:
- Must detect circuits BEFORE entering a position
- Must immediately flag any open position if stock approaches circuit
- Market-wide halt means ALL strategies must pause — no new signals
- Resume signals only after halt ends + 5 minutes (liquidity normalisation)

Data sources:
- NSE live: bhavcopy + circuit filter list (available via NSE website)
- Upstox market depth: bid/ask spread collapse indicates circuit approach
"""
from __future__ import annotations

import json
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("circuit_detector")


# ── Constants ─────────────────────────────────────────────────────────────────

# Market-wide circuit thresholds (Nifty % move)
INDEX_CIRCUIT_LEVELS = [10.0, 15.0, 20.0]     # percentages

# Stock-level band defaults
DEFAULT_STOCK_BAND_PCT = 10.0    # most F&O stocks
CIRCUIT_WARNING_MARGIN = 0.005   # warn when within 0.5% of circuit

# Market halt durations (minutes) indexed by circuit level and time
# key: (level, "before_1pm" | "1_to_2pm" | "after_2pm")
INDEX_HALT_MINUTES: Dict[Tuple, int] = {
    (10, "before_1pm"):  45,
    (10, "1_to_230pm"):  15,
    (10, "after_230pm"): 0,       # no halt
    (15, "before_1pm"):  105,
    (15, "1_to_2pm"):    45,
    (15, "after_2pm"):   999,     # rest-of-day
    (20, "any"):         999,     # rest-of-day always
}


@dataclass
class CircuitStatus:
    symbol:         str
    current_price:  float
    upper_circuit:  float
    lower_circuit:  float
    band_pct:       float
    distance_uc_pct: float   # % gap to upper circuit
    distance_lc_pct: float   # % gap to lower circuit
    is_upper_hit:   bool
    is_lower_hit:   bool
    near_upper:     bool     # within CIRCUIT_WARNING_MARGIN
    near_lower:     bool
    timestamp:      datetime = field(default_factory=datetime.now)

    @property
    def is_circuited(self) -> bool:
        return self.is_upper_hit or self.is_lower_hit

    @property
    def is_near_circuit(self) -> bool:
        return self.near_upper or self.near_lower


@dataclass
class MarketHaltStatus:
    is_halted:       bool
    halt_reason:     str          # "10pct" | "15pct" | "20pct" | ""
    halt_start:      Optional[datetime]
    resume_at:       Optional[datetime]
    nifty_move_pct:  float


class CircuitBreakerDetector:
    """
    Monitors circuit breakers for individual stocks and market-wide halts.

    Usage:
        detector = CircuitBreakerDetector()
        status = detector.check_stock("RELIANCE", current_price=2450.0)
        if status.near_upper:
            # Don't enter new longs; prepare to exit
        halt = detector.check_market_halt(nifty_current, nifty_prev_close)
        if halt.is_halted:
            # Stop all signal generation
    """

    def __init__(self, default_band_pct: float = DEFAULT_STOCK_BAND_PCT):
        self.default_band        = default_band_pct
        self._circuit_limits:    Dict[str, Tuple[float, float]] = {}   # symbol → (UC, LC)
        self._band_pcts:         Dict[str, float]               = {}   # symbol → band%
        self._prev_closes:       Dict[str, float]               = {}
        self._halt_status:       MarketHaltStatus               = MarketHaltStatus(
            is_halted=False, halt_reason="", halt_start=None,
            resume_at=None, nifty_move_pct=0.0,
        )
        self._halt_history:      List[MarketHaltStatus]         = []

    # ── Circuit limit computation ─────────────────────────────────────────────

    def set_prev_close(self, symbol: str, prev_close: float, band_pct: Optional[float] = None) -> None:
        """
        Register previous close for a stock to compute circuit limits.
        band_pct: override default (use exchange-published value).
        """
        self._prev_closes[symbol] = prev_close
        bp = band_pct if band_pct is not None else self.default_band
        self._band_pcts[symbol]   = bp
        uc = round(prev_close * (1 + bp / 100), 2)
        lc = round(prev_close * (1 - bp / 100), 2)
        self._circuit_limits[symbol] = (uc, lc)
        logger.debug(f"Circuit limits: {symbol} UC={uc} LC={lc} band={bp}%")

    def compute_limits(
        self, prev_close: float, band_pct: float = DEFAULT_STOCK_BAND_PCT,
    ) -> Tuple[float, float]:
        """Return (upper_circuit, lower_circuit) for given prev_close and band."""
        uc = round(prev_close * (1 + band_pct / 100), 2)
        lc = round(prev_close * (1 - band_pct / 100), 2)
        return uc, lc

    # ── Stock-level checks ────────────────────────────────────────────────────

    def check_stock(
        self,
        symbol:        str,
        current_price: float,
        prev_close:    Optional[float] = None,
        band_pct:      Optional[float] = None,
    ) -> CircuitStatus:
        """
        Check if a stock is at or near its circuit limits.
        Uses registered prev_close if available, otherwise requires explicit argument.
        """
        # Set limits if new data provided
        if prev_close is not None:
            self.set_prev_close(symbol, prev_close, band_pct)

        if symbol not in self._circuit_limits:
            # No data: return safe defaults
            return CircuitStatus(
                symbol=symbol, current_price=current_price,
                upper_circuit=current_price * 1.10,
                lower_circuit=current_price * 0.90,
                band_pct=self.default_band,
                distance_uc_pct=10.0, distance_lc_pct=10.0,
                is_upper_hit=False, is_lower_hit=False,
                near_upper=False, near_lower=False,
            )

        uc, lc   = self._circuit_limits[symbol]
        bp       = self._band_pcts[symbol]
        dist_uc  = (uc - current_price) / current_price * 100
        dist_lc  = (current_price - lc) / current_price * 100

        is_uc_hit = current_price >= uc
        is_lc_hit = current_price <= lc
        near_uc   = dist_uc <= CIRCUIT_WARNING_MARGIN * 100
        near_lc   = dist_lc <= CIRCUIT_WARNING_MARGIN * 100

        if is_uc_hit or is_lc_hit:
            logger.warning(
                f"CIRCUIT HIT: {symbol} price={current_price} "
                f"{'UC=' + str(uc) if is_uc_hit else 'LC=' + str(lc)}"
            )
        elif near_uc or near_lc:
            logger.warning(
                f"CIRCUIT APPROACHING: {symbol} price={current_price} "
                f"dist_uc={dist_uc:.2f}% dist_lc={dist_lc:.2f}%"
            )

        return CircuitStatus(
            symbol=symbol, current_price=current_price,
            upper_circuit=uc, lower_circuit=lc, band_pct=bp,
            distance_uc_pct=round(dist_uc, 3),
            distance_lc_pct=round(dist_lc, 3),
            is_upper_hit=is_uc_hit, is_lower_hit=is_lc_hit,
            near_upper=near_uc, near_lower=near_lc,
        )

    def is_tradeable(self, symbol: str, current_price: float) -> bool:
        """
        Returns False if stock is circuited or within warning margin.
        Use before placing any new order.
        """
        status = self.check_stock(symbol, current_price)
        if status.is_circuited:
            logger.warning(f"UNTRADEABLE: {symbol} hit circuit")
            return False
        if status.is_near_circuit:
            logger.warning(f"NEAR-CIRCUIT: {symbol} risky to trade")
            return False
        return True

    # ── Market-wide halt checks ───────────────────────────────────────────────

    def check_market_halt(
        self,
        nifty_current:  float,
        nifty_prev_close: float,
        current_time:   Optional[datetime] = None,
    ) -> MarketHaltStatus:
        """
        Check if market-wide circuit breaker is triggered.
        Updates internal halt status and returns current state.
        """
        if nifty_prev_close <= 0:
            return self._halt_status

        move_pct = (nifty_current - nifty_prev_close) / nifty_prev_close * 100
        abs_move = abs(move_pct)
        now      = current_time or datetime.now()

        triggered_level = None
        for level in sorted(INDEX_CIRCUIT_LEVELS, reverse=True):
            if abs_move >= level:
                triggered_level = level
                break

        if triggered_level is None:
            # Clear halt if already resolved
            if self._halt_status.is_halted:
                if self._halt_status.resume_at and now >= self._halt_status.resume_at:
                    self._halt_status = MarketHaltStatus(
                        is_halted=False, halt_reason="", halt_start=None,
                        resume_at=None, nifty_move_pct=move_pct,
                    )
            return self._halt_status

        # Determine halt duration
        hour = now.hour
        minute_of_day = hour * 60 + now.minute
        if triggered_level == 20:
            time_key = "any"
        elif minute_of_day < 13 * 60:      # before 1:00 PM
            time_key = "before_1pm"
        elif minute_of_day < 14 * 60:      # 1:00-2:00 PM
            time_key = "1_to_2pm"
        elif minute_of_day < 14 * 60 + 30: # 2:00-2:30 PM
            time_key = "1_to_230pm"
        else:
            time_key = "after_230pm" if triggered_level == 10 else "after_2pm"

        halt_key = (triggered_level, time_key)
        halt_mins = INDEX_HALT_MINUTES.get(halt_key, 0)

        if halt_mins == 0:
            return self._halt_status

        from datetime import timedelta
        resume = now + timedelta(minutes=halt_mins) if halt_mins < 999 else None

        halt_reason = f"{triggered_level}pct"
        new_halt = MarketHaltStatus(
            is_halted=True, halt_reason=halt_reason,
            halt_start=now, resume_at=resume,
            nifty_move_pct=round(move_pct, 2),
        )

        if not self._halt_status.is_halted:
            logger.critical(
                f"MARKET CIRCUIT BREAKER: Nifty moved {move_pct:.1f}% "
                f"→ {triggered_level}% circuit triggered. "
                f"Halt for {halt_mins} min. Resume at {resume}"
            )
            self._halt_history.append(new_halt)

        self._halt_status = new_halt
        return new_halt

    def is_market_halted(self, current_time: Optional[datetime] = None) -> bool:
        """Quick check: is market currently halted?"""
        if not self._halt_status.is_halted:
            return False
        # Check if resume time has passed
        now = current_time or datetime.now()
        if self._halt_status.resume_at and now >= self._halt_status.resume_at:
            self._halt_status.is_halted = False
            return False
        return True

    # ── Bulk circuit scan ─────────────────────────────────────────────────────

    def scan_portfolio(
        self,
        positions: Dict[str, float],     # symbol → current_price
    ) -> Dict[str, CircuitStatus]:
        """
        Scan all portfolio positions for circuit risk.
        Returns dict of symbol → CircuitStatus for any at-risk positions.
        """
        at_risk = {}
        for symbol, price in positions.items():
            status = self.check_stock(symbol, price)
            if status.is_circuited or status.is_near_circuit:
                at_risk[symbol] = status
        if at_risk:
            logger.warning(
                f"Portfolio circuit scan: {len(at_risk)} positions at risk: "
                f"{list(at_risk.keys())}"
            )
        return at_risk

    def load_circuit_list_nse(self) -> List[str]:
        """
        Fetch today's circuit filter list from NSE.
        Returns list of symbols with circuit filters applied today.
        """
        try:
            import requests
            url = "https://archives.nseindia.com/content/fo/fo_secban.csv"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                df = pd.read_csv(pd.io.common.StringIO(resp.text))
                symbols = df.iloc[:, 0].str.strip().tolist() if not df.empty else []
                logger.info(f"NSE circuit list loaded: {len(symbols)} symbols")
                return symbols
        except Exception as e:
            logger.debug(f"NSE circuit list fetch failed: {e}")
        return []

    def halt_history(self) -> pd.DataFrame:
        """Return DataFrame of all market halts in current session."""
        if not self._halt_history:
            return pd.DataFrame()
        rows = [{
            "reason":    h.halt_reason,
            "start":     h.halt_start,
            "resume":    h.resume_at,
            "nifty_pct": h.nifty_move_pct,
        } for h in self._halt_history]
        return pd.DataFrame(rows)
