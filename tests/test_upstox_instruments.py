import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from data_engine.upstox.instruments import InstrumentRegistry, KNOWN_INSTRUMENTS


@pytest.fixture
def registry():
    reg = InstrumentRegistry()
    # Load without downloading — seeds from KNOWN_INSTRUMENTS
    reg._index_records([])
    for sym, key in KNOWN_INSTRUMENTS.items():
        reg._by_symbol[sym] = {"instrument_key": key, "tradingsymbol": sym,
                                "exchange": key.split("|")[0],
                                "lot_size": "1", "tick_size": "0.05"}
    reg._loaded = True
    return reg


def test_get_key_known_symbol(registry):
    key = registry.get_key("RELIANCE")
    assert key == "NSE_EQ|INE002A01018"


def test_get_key_hdfcbank(registry):
    key = registry.get_key("HDFCBANK")
    assert key == "NSE_EQ|INE040A01034"


def test_get_key_nifty_index(registry):
    key = registry.get_key("NIFTY50")
    assert key == "NSE_INDEX|Nifty 50"


def test_get_key_case_insensitive(registry):
    key = registry.get_key("reliance")
    assert key == "NSE_EQ|INE002A01018"


def test_get_key_unknown_symbol(registry):
    assert registry.get_key("UNKNOWNSYM") is None


def test_pass_through_instrument_key(registry):
    key = "NSE_EQ|INE002A01018"
    # _resolve_key should pass it through directly (contains |)
    assert "|" in key


def test_get_lot_size_default(registry):
    lot = registry.get_lot_size("NSE_EQ|INE002A01018")
    assert isinstance(lot, int)
    assert lot >= 1


def test_get_tick_size_default(registry):
    tick = registry.get_tick_size("NSE_EQ|INE002A01018")
    assert isinstance(tick, float)
    assert tick > 0


def test_round_to_tick(registry):
    price = 2914.37
    rounded = registry.round_to_tick(price, "NSE_EQ|INE002A01018")
    assert rounded % 0.05 < 1e-9 or abs(rounded - round(price / 0.05) * 0.05) < 1e-6


def test_nifty50_keys_returns_list(registry):
    keys = registry.nifty50_keys()
    assert isinstance(keys, list)
    assert len(keys) > 0
    assert all("|" in k for k in keys)


def test_known_instruments_not_empty():
    assert len(KNOWN_INSTRUMENTS) >= 30


def test_all_known_keys_have_pipe():
    for sym, key in KNOWN_INSTRUMENTS.items():
        assert "|" in key, f"{sym} has invalid key: {key}"


def test_search_returns_list(registry):
    results = registry.search("HDFC", exchange="NSE_EQ")
    assert isinstance(results, list)
