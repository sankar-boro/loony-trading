"""
Options instrument key resolver for Upstox F&O.

Upstox F&O instrument key format:
  NSE_FO|{UNDERLYING}{YY}{MON}{STRIKE}{TYPE}

Examples:
  NSE_FO|NIFTY25JUN24500CE   — NIFTY Jun-25, 24500 Call
  NSE_FO|BANKNIFTY25JUN52000PE
  NSE_FO|FINNIFTY25JUN22500CE
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


_MONTH_MAP = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

# How many days before expiry the weekly rolls to the next series
_WEEKLY_ROLL_DAYS = 1


def resolve_option_key(
    underlying: str,
    expiry: date,
    strike: int,
    option_type: str,       # "CE" | "PE"
    exchange: str = "NSE_FO",
) -> str:
    """
    Build Upstox instrument key for a single-leg options contract.

    >>> resolve_option_key("NIFTY", date(2025, 6, 26), 24500, "CE")
    'NSE_FO|NIFTY25JUN24500CE'
    """
    yy  = expiry.strftime("%y")
    mon = _MONTH_MAP[expiry.month]
    ot  = option_type.upper()
    return f"{exchange}|{underlying.upper()}{yy}{mon}{strike}{ot}"


def nearest_expiry(underlying: str, reference: date | None = None) -> date:
    """
    Return the nearest weekly/monthly expiry for an underlying.
    NSE weekly expiries fall on Thursday; monthly on last Thursday.
    This is a best-effort estimate — production should use the
    instrument registry for accurate expiry dates.
    """
    ref = reference or date.today()
    # Find next Thursday (weekday 3)
    days_to_thursday = (3 - ref.weekday()) % 7
    if days_to_thursday == 0:
        days_to_thursday = 7  # if today is Thursday, use next week's
    candidate = ref + timedelta(days=days_to_thursday)
    return candidate


def build_legs_from_signal(signal) -> list[dict]:
    """
    Translate a multi-leg options signal's metadata into a normalised
    list of leg dicts compatible with UpstoxExecutor.place_basket_order().

    Each leg dict:
      {
        "instrument_key": str,   # resolved Upstox F&O key
        "action": "BUY"|"SELL",
        "qty": int,              # in lots (lot-size applied by executor)
        "price": float,          # 0 = market
        "tag": str,
      }

    Supports:
      • iron_condor  — 4 legs from short_call/long_call/short_put/long_put
      • straddle     — 2 legs (short call + short put at same strike)
      • strangle     — 2 legs (short call OTM + short put OTM at different strikes)
      • covered_call — 1 options leg (short call, underlying handled separately)
    """
    meta = signal.metadata or {}
    subtype = meta.get("strategy_subtype", "")
    symbol  = signal.symbol.upper()
    dte     = meta.get("dte", 7)
    expiry  = nearest_expiry(symbol, date.today() + timedelta(days=dte - 1))

    legs: list[dict] = []

    if subtype == "iron_condor":
        sc = int(meta.get("short_call", 0))
        lc = int(meta.get("long_call",  0))
        sp = int(meta.get("short_put",  0))
        lp = int(meta.get("long_put",   0))
        if not all([sc, lc, sp, lp]):
            return []
        legs = [
            {"instrument_key": resolve_option_key(symbol, expiry, sc, "CE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "ic_sc"},
            {"instrument_key": resolve_option_key(symbol, expiry, lc, "CE"),
             "action": "BUY",  "qty": 1, "price": 0.0, "tag": "ic_lc"},
            {"instrument_key": resolve_option_key(symbol, expiry, sp, "PE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "ic_sp"},
            {"instrument_key": resolve_option_key(symbol, expiry, lp, "PE"),
             "action": "BUY",  "qty": 1, "price": 0.0, "tag": "ic_lp"},
        ]

    elif subtype in ("straddle", "short_straddle"):
        strike = int(meta.get("atm_strike", meta.get("strike", 0)))
        if not strike:
            return []
        legs = [
            {"instrument_key": resolve_option_key(symbol, expiry, strike, "CE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "strd_ce"},
            {"instrument_key": resolve_option_key(symbol, expiry, strike, "PE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "strd_pe"},
        ]

    elif subtype in ("strangle", "short_strangle"):
        call_strike = int(meta.get("call_strike", 0))
        put_strike  = int(meta.get("put_strike",  0))
        if not (call_strike and put_strike):
            return []
        legs = [
            {"instrument_key": resolve_option_key(symbol, expiry, call_strike, "CE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "strngl_ce"},
            {"instrument_key": resolve_option_key(symbol, expiry, put_strike, "PE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "strngl_pe"},
        ]

    elif subtype == "covered_call":
        strike = int(meta.get("call_strike", 0))
        if not strike:
            return []
        legs = [
            {"instrument_key": resolve_option_key(symbol, expiry, strike, "CE"),
             "action": "SELL", "qty": 1, "price": 0.0, "tag": "cc_ce"},
        ]

    return legs
