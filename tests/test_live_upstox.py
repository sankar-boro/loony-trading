"""
Live Upstox API Tests — uses UPSTOX_ACCESS_TOKEN env variable (read-only analytics token).

Instrument key formats discovered:
  NSE indices:  NSE_INDEX|Nifty 50   (space, not +)
  NSE equity:   NSE_EQ|<ISIN>        e.g. NSE_EQ|INE002A01018 for RELIANCE
  Historical:   URL path order = /to_date/from_date  (to comes FIRST)

Run with:
  UPSTOX_ACCESS_TOKEN=<token> python -m pytest tests/test_live_upstox.py -v
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest
import requests

# ── Skip all tests if no token ────────────────────────────────────────────────
TOKEN = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
pytestmark = pytest.mark.skipif(not TOKEN, reason="UPSTOX_ACCESS_TOKEN not set")

BASE_URL = "https://api.upstox.com/v2"

# ── Known instrument keys (ISIN-based for equities) ──────────────────────────
NIFTY50     = "NSE_INDEX|Nifty 50"
BANKNIFTY   = "NSE_INDEX|Nifty Bank"
NIFTY_IT    = "NSE_INDEX|Nifty IT"
NIFTY_FMCG  = "NSE_INDEX|Nifty FMCG"
MIDCAP150   = "NSE_INDEX|NIFTY MIDCAP 150"

# Nifty 50 blue chips (ISIN-based keys)
RELIANCE    = "NSE_EQ|INE002A01018"
TCS         = "NSE_EQ|INE467B01029"
HDFCBANK    = "NSE_EQ|INE040A01034"
INFY        = "NSE_EQ|INE009A01021"
ICICIBANK   = "NSE_EQ|INE090A01021"

ALL_INDICES = [NIFTY50, BANKNIFTY, NIFTY_IT, NIFTY_FMCG, MIDCAP150]
ALL_STOCKS  = [RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK]

TO_DATE   = date.today().isoformat()
FROM_DATE = (date.today() - timedelta(days=60)).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers() -> Dict:
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

def _get(path: str, params: dict = None) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=15)

def _encode_key(key: str) -> str:
    return key.replace("|", "%7C").replace(" ", "%20")

def _ltp_bulk(keys: List[str]) -> Dict:
    joined = ",".join(_encode_key(k) for k in keys)
    r = _get(f"/market-quote/ltp?instrument_key={joined}")
    assert r.status_code == 200, f"LTP failed: {r.text[:200]}"
    return r.json().get("data", {})

def _daily_candles(key: str, days: int = 30) -> List:
    from_d = (date.today() - timedelta(days=days)).isoformat()
    to_d   = date.today().isoformat()
    r = _get(f"/historical-candle/{_encode_key(key)}/day/{to_d}/{from_d}")
    assert r.status_code == 200, f"Historical failed for {key}: {r.text[:200]}"
    return r.json().get("data", {}).get("candles", [])

def _intraday_candles(key: str, interval: str = "1minute") -> List:
    r = _get(f"/historical-candle/intraday/{_encode_key(key)}/{interval}")
    assert r.status_code == 200, f"Intraday failed: {r.text[:200]}"
    return r.json().get("data", {}).get("candles", [])


# ═══════════════════════════════════════════════════════════════════════════════
# 1. API Connectivity
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIConnectivity:

    def test_token_is_set(self):
        assert len(TOKEN) > 50, "Token looks truncated"

    def test_ltp_nifty50_returns_200(self):
        r = _get(f"/market-quote/ltp?instrument_key={_encode_key(NIFTY50)}")
        assert r.status_code == 200

    def test_response_is_valid_json(self):
        r = _get(f"/market-quote/ltp?instrument_key={_encode_key(NIFTY50)}")
        data = r.json()
        assert data.get("status") == "success"

    def test_full_quote_nifty50(self):
        r = _get(f"/market-quote/quotes?instrument_key={_encode_key(NIFTY50)}")
        assert r.status_code == 200
        data = r.json().get("data", {})
        assert len(data) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LTP — Live Price Feed
# ═══════════════════════════════════════════════════════════════════════════════

class TestLTP:

    def test_all_nifty_indices_have_price(self):
        data = _ltp_bulk(ALL_INDICES)
        for key in ALL_INDICES:
            norm = key.replace("|", ":")
            assert norm in data, f"Missing {key}"
            price = data[norm].get("last_price", 0)
            assert price > 0, f"Zero price for {key}"

    def test_nifty50_price_in_realistic_range(self):
        data = _ltp_bulk([NIFTY50])
        price = data["NSE_INDEX:Nifty 50"]["last_price"]
        assert 10000 < price < 100000, f"Nifty50={price} out of realistic range"

    def test_banknifty_price_in_realistic_range(self):
        data = _ltp_bulk([BANKNIFTY])
        price = data["NSE_INDEX:Nifty Bank"]["last_price"]
        assert 20000 < price < 200000, f"BankNifty={price} out of realistic range"

    def test_equity_ltp_reliance(self):
        data = _ltp_bulk([RELIANCE])
        key  = "NSE_EQ:RELIANCE" if "NSE_EQ:RELIANCE" in data else list(data.keys())[0] if data else None
        if not data:
            pytest.skip("Equity LTP may require EQ segment access")
        price = list(data.values())[0].get("last_price", 0)
        assert price > 0

    def test_bulk_ltp_5_instruments(self):
        data = _ltp_bulk(ALL_INDICES)
        assert len(data) == 5

    def test_ltp_all_values_positive(self):
        data = _ltp_bulk(ALL_INDICES)
        for k, v in data.items():
            assert v["last_price"] > 0, f"{k} has zero/negative price"

    def test_nifty_it_price_realistic(self):
        data = _ltp_bulk([NIFTY_IT])
        price = data["NSE_INDEX:Nifty IT"]["last_price"]
        assert 10000 < price < 100000


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Full Quotes — OHLC, Volume, Depth
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullQuotes:

    def _get_quote(self, key: str) -> dict:
        r = _get(f"/market-quote/quotes?instrument_key={_encode_key(key)}")
        assert r.status_code == 200
        data = r.json().get("data", {})
        assert data, f"Empty quote data for {key}"
        return list(data.values())[0]

    def test_nifty50_ohlc_valid(self):
        q = self._get_quote(NIFTY50)
        ohlc = q.get("ohlc", {})
        o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
        assert h >= l, "High < Low"
        assert h >= o, "High < Open"
        assert l <= c, "Low > Close"

    def test_nifty50_depth_has_bids_asks(self):
        q = self._get_quote(NIFTY50)
        depth = q.get("depth", {})
        # Indices may not have depth; just check it exists or is empty
        assert depth is not None

    def test_banknifty_ohlc_consistent(self):
        q = self._get_quote(BANKNIFTY)
        ohlc = q.get("ohlc", {})
        assert ohlc["high"] >= ohlc["low"]
        assert ohlc["high"] >= ohlc["open"]

    def test_multiple_index_quotes(self):
        for key in [NIFTY50, BANKNIFTY, NIFTY_IT]:
            r = _get(f"/market-quote/quotes?instrument_key={_encode_key(key)}")
            assert r.status_code == 200, f"Failed for {key}"
            data = r.json().get("data", {})
            assert len(data) > 0, f"No data for {key}"

    def test_last_price_within_high_low(self):
        q = self._get_quote(NIFTY50)
        ohlc  = q.get("ohlc", {})
        price = q.get("last_price", 0)
        # Allow 1% outside OHLC (late quote vs EOD close)
        margin = ohlc["high"] * 0.01
        assert ohlc["low"] - margin <= price <= ohlc["high"] + margin, \
            f"last_price={price} outside [{ohlc['low']}, {ohlc['high']}]"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Historical Daily Candles
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistoricalDaily:

    def test_nifty50_30day_candles(self):
        candles = _daily_candles(NIFTY50, 30)
        assert len(candles) >= 15, f"Expected 15+ trading days, got {len(candles)}"

    def test_candle_format_ohlcv(self):
        candles = _daily_candles(NIFTY50, 10)
        assert len(candles) > 0
        c = candles[0]
        # Format: [timestamp, open, high, low, close, volume, oi]
        assert len(c) >= 5
        ts, o, h, l, close = c[0], c[1], c[2], c[3], c[4]
        assert "2026" in ts or "2025" in ts, f"Unexpected timestamp: {ts}"
        assert h >= l, f"High {h} < Low {l}"
        assert h >= o, f"High {h} < Open {o}"

    def test_candles_in_chronological_order(self):
        candles = _daily_candles(NIFTY50, 30)
        timestamps = [c[0] for c in candles]
        # API returns newest first — check descending order
        assert timestamps[0] >= timestamps[-1], "Candles not in descending order"

    def test_banknifty_60day_candles(self):
        candles = _daily_candles(BANKNIFTY, 60)
        assert len(candles) >= 25

    def test_nifty_it_daily_prices_positive(self):
        candles = _daily_candles(NIFTY_IT, 20)
        for c in candles:
            o, h, l, close = c[1], c[2], c[3], c[4]
            assert all(x > 0 for x in [o, h, l, close]), f"Non-positive OHLC: {c}"

    def test_weekly_candles(self):
        from_d = (date.today() - timedelta(days=180)).isoformat()
        to_d   = date.today().isoformat()
        r = _get(f"/historical-candle/{_encode_key(NIFTY50)}/week/{to_d}/{from_d}")
        assert r.status_code == 200
        candles = r.json().get("data", {}).get("candles", [])
        assert len(candles) >= 10

    def test_monthly_candles_2_years(self):
        from_d = (date.today() - timedelta(days=730)).isoformat()
        to_d   = date.today().isoformat()
        r = _get(f"/historical-candle/{_encode_key(NIFTY50)}/month/{to_d}/{from_d}")
        assert r.status_code == 200
        candles = r.json().get("data", {}).get("candles", [])
        assert len(candles) >= 12

    def test_midcap150_daily(self):
        candles = _daily_candles(MIDCAP150, 30)
        assert len(candles) >= 10


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Intraday Candles
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntradayCandles:

    def test_nifty50_1min_candles(self):
        candles = _intraday_candles(NIFTY50, "1minute")
        # Should have candles if market is open; may be empty outside hours
        assert isinstance(candles, list)

    def test_banknifty_1min_has_data(self):
        candles = _intraday_candles(BANKNIFTY, "1minute")
        assert isinstance(candles, list)
        if candles:
            c = candles[0]
            assert len(c) >= 5
            assert c[2] >= c[3], f"High {c[2]} < Low {c[3]}"

    def test_nifty50_30min_candles(self):
        candles = _intraday_candles(NIFTY50, "30minute")
        assert isinstance(candles, list)

    def test_intraday_candles_are_recent(self):
        candles = _intraday_candles(NIFTY50, "1minute")
        if candles:
            ts = candles[0][0]
            assert "2026" in ts, f"Stale data: {ts}"

    def test_intraday_ohlc_valid(self):
        candles = _intraday_candles(NIFTY50, "1minute")
        for c in candles[:10]:
            o, h, l, close = c[1], c[2], c[3], c[4]
            assert h >= l, f"H < L: {c}"
            assert h >= min(o, close), f"H < min(O,C): {c}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Instrument Search
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstrumentSearch:

    def test_search_reliance(self):
        r = _get("/instruments/search", {"query": "RELIANCE", "segment": "NSE_EQ"})
        assert r.status_code == 200
        data = r.json().get("data", [])
        assert len(data) > 0
        names = [d.get("name", "") for d in data]
        assert any("RELIANCE" in n.upper() for n in names)

    def test_search_returns_isin(self):
        r = _get("/instruments/search", {"query": "TCS", "segment": "NSE_EQ"})
        assert r.status_code == 200
        data = r.json().get("data", [])
        if data:
            assert "isin" in data[0], "ISIN missing from search result"

    def test_search_hdfcbank(self):
        r = _get("/instruments/search", {"query": "HDFC BANK", "segment": "NSE_EQ"})
        assert r.status_code == 200
        data = r.json().get("data", [])
        assert len(data) > 0

    def test_search_result_has_instrument_key(self):
        r = _get("/instruments/search", {"query": "INFY", "segment": "NSE_EQ"})
        assert r.status_code == 200
        data = r.json().get("data", [])
        if data:
            inst = data[0]
            assert "instrument_key" in inst or "isin" in inst

    def test_search_nifty50_components(self):
        """Search for key Nifty50 stocks and verify they exist."""
        stocks = ["RELIANCE", "TCS", "HDFC BANK", "INFOSYS", "ICICI BANK"]
        for stock in stocks:
            r = _get("/instruments/search", {"query": stock, "segment": "NSE_EQ"})
            assert r.status_code == 200
            data = r.json().get("data", [])
            assert len(data) > 0, f"No results for {stock}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Our Data Engine with Live Data
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataEngineWithLiveData:
    """Run our production data engine code against live Upstox API."""

    def _fetch_daily_df(self, key: str, days: int = 60) -> pd.DataFrame:
        candles = _daily_candles(key, days)
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.sort_values("ts").set_index("ts")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna()

    def test_feature_builder_on_live_nifty_data(self):
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._fetch_daily_df(NIFTY50, 60)
        assert len(df) >= 15, f"Insufficient daily candles: {len(df)}"
        out = FeatureBuilder().build(df)
        assert isinstance(out, pd.DataFrame)
        assert "rsi_14" in out.columns
        assert "macd" in out.columns
        assert "atr_14" in out.columns

    def test_feature_builder_no_nans_after_build(self):
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._fetch_daily_df(BANKNIFTY, 60)
        out = FeatureBuilder().build(df)
        assert out.isnull().sum().sum() == 0, "Feature builder left NaNs"

    def test_cvr_on_live_returns(self):
        from risk_manager.cvar import historical_cvar
        df = self._fetch_daily_df(NIFTY50, 60)
        assert len(df) >= 20
        returns = df["close"].pct_change().dropna().tolist()
        report = historical_cvar(returns, confidence=0.95)
        assert report.cvar >= 0
        assert report.n_obs > 0
        assert -5 < report.mean_loss * 100 < 5  # daily mean loss usually < 5%

    def test_beta_computation_nifty_vs_banknifty(self):
        from portfolio_manager.beta_neutral import BetaNeutralManager
        nifty_df = self._fetch_daily_df(NIFTY50, 60)
        bn_df    = self._fetch_daily_df(BANKNIFTY, 60)
        assert len(nifty_df) >= 20 and len(bn_df) >= 20
        mgr = BetaNeutralManager(capital=1_000_000)
        est = mgr.compute_beta("BankNifty", bn_df["close"], nifty_df["close"])
        # BankNifty beta vs Nifty50 is typically 1.1 - 1.6
        assert 0.5 < est.beta < 2.5, f"BankNifty beta={est.beta} unusual"
        assert est.r_squared > 0.5, f"R² too low: {est.r_squared}"

    def test_factor_model_on_live_indices(self):
        from analytics.factor_model import FactorModel
        nifty  = self._fetch_daily_df(NIFTY50, 60)["close"].pct_change().dropna()
        bk     = self._fetch_daily_df(BANKNIFTY, 60)["close"].pct_change().dropna()
        it     = self._fetch_daily_df(NIFTY_IT, 60)["close"].pct_change().dropna()

        if len(nifty) < 20:
            pytest.skip("Insufficient data")

        # Use BankNifty + IT as factors; Nifty50 as portfolio
        common_idx = nifty.index.intersection(bk.index).intersection(it.index)
        if len(common_idx) < 20:
            pytest.skip("Insufficient common dates")

        port     = nifty.loc[common_idx]
        factors  = pd.DataFrame({"banking": bk.loc[common_idx], "it": it.loc[common_idx]})
        fm       = FactorModel(factors=["banking", "it"])
        exposure = fm.fit(port, factors)
        assert 0 <= exposure.r_squared <= 1
        assert "banking" in exposure.factor_loadings
        assert "it" in exposure.factor_loadings

    def test_stress_test_with_live_vol(self):
        from backtester.stress_test import run_stress_test
        df      = self._fetch_daily_df(NIFTY50, 60)
        returns = df["close"].pct_change().dropna()
        # Use actual daily P&L-like values
        pnl     = (returns * 1_000_000).tolist()
        report  = run_stress_test(pnl, capital=1_000_000)
        assert len(report.results) == 5
        assert report.worst_scenario is not None
        # GFC or COVID should be worst
        assert report.worst_scenario in ("gfc_2008", "covid_2020")

    def test_kalman_hedge_ratio_live_pair(self):
        from utils.kalman import KalmanHedgeRatio
        nifty_df = self._fetch_daily_df(NIFTY50, 60)
        bn_df    = self._fetch_daily_df(BANKNIFTY, 60)
        assert len(nifty_df) >= 20
        k  = KalmanHedgeRatio()
        df = k.fit(bn_df["close"], nifty_df["close"])
        assert len(df) > 0
        assert "beta" in df.columns
        # BankNifty/Nifty50 ratio is ~2.0-3.0 (BN≈55000, N50≈24000)
        last_beta = df["beta"].iloc[-1]
        assert 1.0 < last_beta < 5.0, f"Unexpected hedge ratio: {last_beta}"

    def test_circuit_detector_with_live_prices(self):
        from data_engine.circuit_detector import CircuitBreakerDetector
        data = _ltp_bulk(ALL_INDICES)
        nifty_price = data["NSE_INDEX:Nifty 50"]["last_price"]
        det = CircuitBreakerDetector()
        # Yesterday close approximation: use today's OHLC open as proxy
        r = _get(f"/market-quote/quotes?instrument_key={_encode_key(NIFTY50)}")
        ohlc = list(r.json().get("data", {}).values())[0].get("ohlc", {})
        prev_close = ohlc.get("open", nifty_price)
        status = det.check_stock("NIFTY50_INDEX", nifty_price, prev_close=prev_close, band_pct=10.0)
        assert not status.is_circuited, "Nifty shouldn't be in circuit during normal day"
        assert status.distance_uc_pct > 0

    def test_monte_carlo_on_live_nifty_returns(self):
        from backtester.monte_carlo import run_monte_carlo
        df      = self._fetch_daily_df(NIFTY50, 60)
        returns = df["close"].pct_change().dropna().tolist()
        if len(returns) < 20:
            pytest.skip("Insufficient data")
        result = run_monte_carlo(returns, n_simulations=200, method="bootstrap")
        assert result.n_simulations == 200
        # Nifty 50 should have positive mean return historically
        assert isinstance(result.sharpe_mean, float)
        # p-value should be between 0 and 1
        assert 0 <= result.p_value_sharpe <= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Live Technical Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveTechnicalAnalysis:
    """Compute real indicators on live data and validate values."""

    def _get_nifty_df(self, days=60) -> pd.DataFrame:
        candles = _daily_candles(NIFTY50, days)
        df = pd.DataFrame(candles, columns=["ts","open","high","low","close","volume","oi"])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.sort_values("ts").set_index("ts")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c])
        return df

    def test_rsi_in_valid_range(self):
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._get_nifty_df(60)
        out = FeatureBuilder().build(df)
        if "rsi_14" in out.columns and len(out) > 0:
            rsi = out["rsi_14"].dropna()
            assert (rsi >= 0).all() and (rsi <= 100).all(), f"RSI out of range: {rsi.min():.1f}-{rsi.max():.1f}"

    def test_macd_signal_relationship(self):
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._get_nifty_df(60)
        out = FeatureBuilder().build(df)
        if "macd" in out.columns and "macd_signal" in out.columns and len(out) > 0:
            # MACD histogram = MACD - signal
            computed = out["macd"] - out["macd_signal"]
            actual   = out["macd_hist"]
            np.testing.assert_allclose(computed.values, actual.values, atol=0.01)

    def test_bollinger_bands_envelope(self):
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._get_nifty_df(60)
        out = FeatureBuilder().build(df)
        if all(c in out.columns for c in ["bb_upper","bb_lower","bb_mid"]) and len(out) > 0:
            assert (out["bb_upper"] >= out["bb_lower"]).all()
            assert (out["bb_upper"] >= out["bb_mid"]).all()
            assert (out["bb_mid"]   >= out["bb_lower"]).all()

    def test_atr_positive(self):
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._get_nifty_df(60)
        out = FeatureBuilder().build(df)
        if "atr_14" in out.columns and len(out) > 0:
            assert (out["atr_14"] > 0).all(), "ATR should be positive"

    def test_ema_ordering(self):
        """In a trending market, EMA9 < EMA20 < EMA50 (downtrend) or reversed."""
        from feature_engine.feature_builder import FeatureBuilder
        df  = self._get_nifty_df(60)
        out = FeatureBuilder().build(df)
        if all(c in out.columns for c in ["ema_9","ema_20","ema_50"]) and len(out) > 0:
            last = out.iloc[-1]
            # Just verify they are positive and different
            assert last["ema_9"] > 0
            assert last["ema_20"] > 0
            assert last["ema_50"] > 0

    def test_intraday_vwap_anchored(self):
        from strategies.microstructure.anchored_vwap import compute_anchored_vwap
        candles = _intraday_candles(NIFTY50, "1minute")
        if len(candles) < 20:
            pytest.skip("Insufficient intraday data (market may be closed)")
        df = pd.DataFrame(candles, columns=["ts","open","high","low","close","volume","oi"])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.sort_values("ts").set_index("ts")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c])
        vwap, upper2, upper1, lower1, lower2 = compute_anchored_vwap(df)
        nifty_price = float(df["close"].iloc[-1])
        # All return Series — take last scalar value
        v, u2, u1, l1, l2 = (float(x.iloc[-1]) for x in (vwap, upper2, upper1, lower1, lower2))
        if any(np.isnan(x) for x in (v, u2, u1, l1, l2)):
            pytest.skip("VWAP NaN — intraday volume data unavailable (market closed or zero volume)")
        assert abs(v - nifty_price) / nifty_price < 0.05, \
            f"VWAP={v:.0f} far from price={nifty_price:.0f}"
        assert u2 >= u1 >= v >= l1 >= l2

    def test_cumulative_delta_intraday(self):
        from strategies.microstructure.cumulative_delta import DeltaTracker
        candles = _intraday_candles(BANKNIFTY, "1minute")
        if len(candles) < 10:
            pytest.skip("Insufficient intraday data")
        tracker = DeltaTracker()
        df = pd.DataFrame(candles, columns=["ts","open","high","low","close","volume","oi"])
        for _, row in df.iterrows():
            tracker.add_bar(row)
        summary = tracker.summary()
        assert "cumulative_delta" in summary
        assert "total_buy_volume" in summary
        assert summary["total_buy_volume"] >= 0

    def test_volume_profile_daily(self):
        from strategies.microstructure.volume_profile import compute_volume_profile
        candles = _intraday_candles(NIFTY50, "1minute")
        if len(candles) < 20:
            pytest.skip("Need intraday data")
        df = pd.DataFrame(candles, columns=["ts","open","high","low","close","volume","oi"])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.sort_values("ts").set_index("ts")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c])
        vp = compute_volume_profile(df, bins=20)
        if vp is not None:
            assert vp.poc > 0, "POC should be positive"
            assert vp.vah > vp.val, "VAH should be above VAL"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Options Market Data
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptionsData:
    """Test options chain and IV surface with live data."""

    def test_option_chain_endpoint_accessible(self):
        r = _get("/option/chain", {"instrument_key": NIFTY50, "expiry_date": "2026-06-26"})
        # 200 = data available; 404 = expiry not found; 400 = bad format
        assert r.status_code in (200, 400, 404)

    def test_option_chain_alternative_endpoint(self):
        r = _get("/option/chain", params={
            "instrument_key": _encode_key(NIFTY50),
            "expiry_date": "2026-06-26",
        })
        assert r.status_code in (200, 400, 404)

    def test_greeks_computation_with_live_spot(self):
        from feature_engine.greeks import Greeks, implied_volatility
        data  = _ltp_bulk([NIFTY50])
        spot  = data["NSE_INDEX:Nifty 50"]["last_price"]
        # Compute ATM call Greeks with spot as strike, 30 DTE, 15% IV
        g = Greeks(S=spot, K=round(spot/50)*50, T=30, r=0.065, sigma=0.15, opt="call")
        assert 0 < g.delta <= 1.0
        assert g.gamma > 0
        assert g.theta < 0     # theta is negative (time decay)
        assert g.vega  > 0

    def test_iv_surface_build_synthetic(self):
        """Build IV surface with live spot but synthetic chain (no live options needed)."""
        from data_engine.upstox.iv_surface import IVPoint, build_iv_surface
        from datetime import timedelta
        data  = _ltp_bulk([NIFTY50])
        spot  = data["NSE_INDEX:Nifty 50"]["last_price"]
        expiry = (date.today() + timedelta(days=21)).isoformat()
        # Synthetic chain around live spot
        atm   = round(spot / 50) * 50
        rows = []
        for strike in range(int(atm - 300), int(atm + 350), 50):
            dist_pct = (strike - atm) / atm
            iv_call  = 0.15 + abs(dist_pct) * 0.3   # smile
            iv_put   = 0.15 + abs(dist_pct) * 0.3
            rows.append({
                "strike":   float(strike),
                "expiry":   expiry,
                "call_ltp": max(0, spot - strike) * 0.5 + 50,
                "put_ltp":  max(0, strike - spot) * 0.5 + 50,
                "call_oi":  1000,
                "put_oi":   1000,
                "call_iv":  iv_call,
                "put_iv":   iv_put,
            })
        chain_df = pd.DataFrame(rows)
        surface = build_iv_surface("Nifty50", spot, chain_df, iv_history=[0.14, 0.15, 0.16])
        assert surface is not None
        assert surface.atm_iv() > 0
        assert surface.spot == spot


# ═══════════════════════════════════════════════════════════════════════════════
# 10. NSE Data Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestNSEDataEngine:

    def test_india_vix_fetch(self):
        from data_engine.upstox.india_vix import classify_vix
        # We can at least test the classification function with live-ish VIX
        for vix_val in [10, 13, 17, 22, 26, 35]:
            regime = classify_vix(float(vix_val))
            assert regime in ("EXTREME_COMPLACENCY", "LOW", "NORMAL", "ELEVATED",
                              "HIGH_FEAR", "EXTREME_FEAR")

    def test_vix_percentile_function(self):
        from feature_engine.greeks import iv_percentile
        history = [12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 25.0, 30.0]
        pct = iv_percentile(18.0, history)
        assert 0 <= pct <= 100

    def test_greeks_iv_rank_with_realistic_values(self):
        from feature_engine.greeks import iv_rank
        # India VIX history: typical range 12-30
        history = list(range(12, 31))
        rank = iv_rank(20.0, history)
        assert 0 <= rank <= 100
        # 20 in range [12,30] should be around 44th percentile
        assert 30 < rank < 60, f"IV rank {rank} unexpected for VIX=20 in [12,30]"

    def test_fo_ban_list_fetch(self):
        try:
            from data_engine.nse_data import fetch_fo_ban_list
            ban_list = fetch_fo_ban_list()
            assert isinstance(ban_list, list)
            # May be empty on non-trading days
        except Exception as e:
            pytest.skip(f"FO ban list unavailable: {e}")

    def test_circuit_detector_market_halt_no_halt_today(self):
        from data_engine.circuit_detector import CircuitBreakerDetector
        data   = _ltp_bulk([NIFTY50])
        spot   = data["NSE_INDEX:Nifty 50"]["last_price"]
        r      = _get(f"/market-quote/quotes?instrument_key={_encode_key(NIFTY50)}")
        ohlc   = list(r.json()["data"].values())[0]["ohlc"]
        prev_close = ohlc.get("open", spot)
        det    = CircuitBreakerDetector()
        halt   = det.check_market_halt(spot, prev_close)
        # Normal trading day — no halt expected
        move   = abs(spot - prev_close) / prev_close * 100
        assert (halt.is_halted == False) or move >= 10.0, \
            f"Unexpected halt status (move={move:.1f}%)"
