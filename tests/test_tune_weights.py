"""scripts/tune_weights.py must write real strategy names and keep the
strategies it cannot backtest (docs/appendix/status.md §4)."""
from scripts.tune_weights import _get_strategy_classes, _merge_untuned
from strategies.meta_engine import registered_strategy_names


def test_tuned_names_are_real_strategy_names():
    names = set(_get_strategy_classes())
    assert names <= set(registered_strategy_names())
    assert {"mtf_trend", "candle_patterns", "anchored_vwap", "volume_profile"} <= names


def test_untuned_enabled_strategies_are_kept():
    weights = {"donchian_breakout": 1.3, "ema_crossover": 0.0}
    enabled = ["donchian_breakout"]
    current = {"enabled": ["donchian_breakout", "vix_strategy", "fii_dii"],
               "weights": {"vix_strategy": 1.1}}
    w, e = _merge_untuned(weights, enabled, current)
    assert e == ["donchian_breakout", "vix_strategy", "fii_dii"]
    assert w["vix_strategy"] == 1.1 and w["fii_dii"] == 1.0 and w["donchian_breakout"] == 1.3
