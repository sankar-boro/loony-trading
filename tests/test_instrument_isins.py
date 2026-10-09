"""Hardcoded ISINs go stale when a company splits, issues bonus shares or
is renamed (10 had, in October 2026 — KOTAKBANK, BAJFINANCE, HAL, ...),
and Upstox then silently returns no data for that stock."""
from __future__ import annotations
import csv
from pathlib import Path

import pytest

from config.instruments import INSTRUMENTS

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "instruments" / "NSE.csv"


def test_registry_isins_exist_in_upstox_master():
    if not MASTER.exists():
        pytest.skip("data/instruments/NSE.csv not downloaded (scripts/fetch_instruments.sh)")
    keys = {row[0] for row in csv.reader(MASTER.open()) if row and row[0].startswith("NSE_EQ|")}
    stale = sorted(sym for sym, key in INSTRUMENTS.items() if key.startswith("NSE_EQ|") and key not in keys)
    assert stale == [], f"ISINs not in the Upstox instrument master: {stale}"


def test_duplicate_isin_maps_agree_with_registry():
    from data_engine.upstox import instruments as up_instruments
    from scripts.market_watch import EQUITY_ISIN
    from scripts.order import COMMON_ISINS

    copies = {f"scripts/market_watch.py:{s}": f"NSE_EQ|{i}" for s, i in EQUITY_ISIN.items()}
    copies |= {f"scripts/order.py:{s}": f"NSE_EQ|{i}" for s, i in COMMON_ISINS.items()}
    for name in dir(up_instruments):
        obj = getattr(up_instruments, name)
        if isinstance(obj, dict) and obj and all(isinstance(v, str) and v.startswith("NSE_EQ|")
                                                 for v in obj.values()):
            copies |= {f"data_engine/upstox/instruments.py:{s}": k for s, k in obj.items()}

    wrong = {where: key for where, key in copies.items()
             if where.split(":")[1] in INSTRUMENTS and INSTRUMENTS[where.split(":")[1]] != key}
    assert wrong == {}
