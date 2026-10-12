"""InstrumentRegistry resolution and F&O lot sizing (docs/appendix/status.md §4).

The master download URLs had moved (old ones return 403), leaving only 36
hardcoded instruments resolvable — 66 of the 99 universe symbols and
indices could not be fetched or traded. The registry now always seeds the
verified universe from config/instruments.py, which also wins over an
unrelated master instrument with the same ticker."""
from __future__ import annotations

import pytest

from config.instruments import INSTRUMENTS
from data_engine.upstox.instruments import InstrumentRegistry
from execution_engine.upstox_executor import UpstoxExecutor


@pytest.fixture
def offline(monkeypatch):
    import requests

    def _fail(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", _fail)


def test_every_universe_symbol_resolves_without_the_master(tmp_path, offline):
    reg = InstrumentRegistry(cache_dir=str(tmp_path))
    reg.load(exchanges=["NSE_EQ", "NSE_INDEX"])
    assert {s: reg.get_key(s) for s in INSTRUMENTS} == INSTRUMENTS


def test_universe_wins_over_same_ticker_in_master(tmp_path, offline):
    reg = InstrumentRegistry(cache_dir=str(tmp_path))
    # The real master lists an ETF under the ticker MIDCAP.
    reg._index_records([{"tradingsymbol": "MIDCAP", "instrument_key": "NSE_EQ|INF174KA1ZC5"}])
    reg.load(exchanges=[])
    assert reg.get_key("MIDCAP") == INSTRUMENTS["MIDCAP"]


def test_master_lot_size_beats_fallback_table():
    # Real F&O keys are numeric tokens with no underlying name in them.
    assert UpstoxExecutor._validate_quantity("NSE_FO|48906", 70, master_lot=65) == 65
    assert UpstoxExecutor._validate_quantity("NSE_FO|48906", 140, master_lot=65) == 130
    assert UpstoxExecutor._validate_quantity("NSE_FO|48906", 10, master_lot=65) == 65   # at least one lot


def test_symbolic_key_falls_back_to_table():
    assert UpstoxExecutor._validate_quantity("NSE_FO|BANKNIFTY25JUN52000PE", 47) == 30


def test_equity_quantity_untouched():
    assert UpstoxExecutor._validate_quantity("NSE_EQ|INE002A01018", 47, master_lot=1) == 47
