"""Regime detection: breakout and crisis regimes, the gated HMM, and how
the HMM and ADX rules combine."""
from __future__ import annotations
import time

import numpy as np
import pandas as pd
import pytest

import strategies.hmm_regime as hmm_regime
from strategies.hmm_regime import HMMRegimeDetector
from strategies.regime_detector import MarketRegime, RegimeDetector


def _ohlc(close, rng_width=None) -> pd.DataFrame:
    close = np.asarray(close, float)
    w = np.full(len(close), 1.0) if rng_width is None else np.asarray(rng_width, float)
    return pd.DataFrame({"open": close, "high": close + w / 2, "low": close - w / 2,
                         "close": close, "volume": 1000.0},
                        index=pd.date_range("2024-01-01", periods=len(close), freq="B"))


def test_crisis_from_rules_and_only_crisis_strategies_trade():
    rng = np.random.default_rng(0)
    calm = list(100 + np.cumsum(rng.normal(0, 0.3, 60)))
    crash = [calm[-1] * f for f in (0.90, 0.97, 0.86, 0.93, 0.80, 0.82)]   # −9 % over 5 bars
    det = RegimeDetector({"regime_detection": {"volatility_high_pct": 0.02}})
    assert det.detect(_ohlc(calm + crash)) == MarketRegime.CRISIS
    assert det.last_source == "rules"
    assert not det.regime_matches(MarketRegime.CRISIS, ["all"])
    assert det.regime_matches(MarketRegime.CRISIS, ["crisis"])


def test_breakout_from_rules_and_who_may_trade_it():
    close = [100.0] * 40 + [104.0]
    width = [1.0] * 40 + [4.0]
    det = RegimeDetector({})
    assert det.detect(_ohlc(close, width)) == MarketRegime.BREAKOUT
    assert det.regime_matches(MarketRegime.BREAKOUT, ["trending"])
    assert det.regime_matches(MarketRegime.BREAKOUT, ["volatile"])
    assert not det.regime_matches(MarketRegime.BREAKOUT, ["ranging"])
    assert det.regime_matches(MarketRegime.HIGH_VOLATILITY, ["high_volatility"])   # alias


def _switching(n=600, seed=1) -> pd.DataFrame:
    """Calm and turbulent stretches that persist — real regimes."""
    rng = np.random.default_rng(seed)
    vol = np.where((np.arange(n) // 60) % 2 == 0, 0.005, 0.03)
    close = 100 * np.exp(np.cumsum(rng.normal(0, vol)))
    return _ohlc(close, close * vol * 2)


def test_gate_passes_persistent_regimes_and_rejects_iid_noise():
    good = HMMRegimeDetector("GOOD").evaluate(_switching())
    assert good["passed"] and good["mean_run"] >= 3 and good["ll_hmm"] > good["ll_base"]
    rng = np.random.default_rng(2)
    iid = _ohlc(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 600))))
    assert not HMMRegimeDetector("IID").evaluate(iid)["passed"]


def test_fit_saves_gate_result_and_detector_respects_it():
    det = HMMRegimeDetector("SWITCH")
    assert det.fit(_switching()) is True
    loaded = HMMRegimeDetector("SWITCH")
    assert loaded.load() and loaded.meta["passed"] and loaded.usable()
    loaded.meta["fitted_at"] = time.time() - 100 * 86400
    assert not loaded.usable(max_age_days=45)                       # stale


def test_failed_or_missing_model_falls_back_to_adx():
    det = RegimeDetector({})
    df = _switching()
    det.detect(df, symbol="NOMODEL")
    assert det.last_source in ("adx", "rules")
    bad = HMMRegimeDetector("BAD")
    bad.fit(_ohlc(100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, 600)))))
    det2 = RegimeDetector({})
    det2.detect(df, symbol="BAD")
    assert det2.last_source in ("adx", "rules")


def test_hmm_decides_turbulence_and_adx_decides_trend(monkeypatch):
    class FakeHMM:
        def __init__(self, regime): self.regime = regime
        def predict(self, df): return self.regime, None
    det = RegimeDetector({})
    df = _ohlc(np.linspace(100, 160, 120))                          # steady trend
    det._hmm_cache["SYM"] = FakeHMM(MarketRegime.HIGH_VOLATILITY)
    assert det.detect(df, symbol="SYM") == MarketRegime.HIGH_VOLATILITY and det.last_source == "hmm"
    det._hmm_cache["SYM"] = FakeHMM(MarketRegime.RANGING)
    assert det.detect(df, symbol="SYM") == MarketRegime.TRENDING_UP and det.last_source == "hmm+adx"
    det2 = RegimeDetector({"regime_detection": {"use_hmm": False}})
    det2._hmm_cache["SYM"] = FakeHMM(MarketRegime.CRISIS)
    det2.detect(df, symbol="SYM")
    assert det2.last_source == "adx"


def test_state_labels_are_relative_to_the_symbol():
    det = HMMRegimeDetector("REL")
    det.fit(_switching())
    labels = set(r.value for r in det.state_map.values())
    assert labels & {"high_volatility", "crisis", "breakout"}        # the turbulent stretches
    assert labels & {"ranging", "low_volatility", "trending_up", "trending_down"}


def test_fit_regimes_reports_every_symbol():
    from scripts.fit_regimes import fit_regimes
    rows = fit_regimes(["SWITCH", "SHORT", "MISSING"], frames={"SWITCH": _switching(),
                                                               "SHORT": _switching(n=100)})
    by = {r["symbol"]: r for r in rows}
    assert by["SWITCH"]["passed"] and "ll_hmm" in by["SWITCH"]
    assert "not enough bars" in by["SHORT"]["reason"] and by["MISSING"]["bars"] == 0


def test_chart_regime_helper():
    from dashboard.backend.routers.chart import _regime
    df = _switching(n=80)
    candles = [{"time": int(t.timestamp()), "open": r.open, "high": r.high, "low": r.low,
                "close": r.close, "volume": r.volume} for t, r in df.iterrows()]
    out = _regime("NOMODEL", candles)
    assert out["value"] in {m.value for m in MarketRegime} and out["source"] in ("adx", "rules")
    assert _regime("X", candles[:10]) is None
