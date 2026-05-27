"""
Advanced feature engineering for Indian markets.

Adds signals that are NOT in basic OHLCV:
1. Cross-asset features  — USD/INR, Gold, Crude, US futures (macro context)
2. F&O OI build-up       — rising price + rising OI = confirmed trend
3. Put/Call ratio (PCR)  — sentiment extremes signal reversals
4. Delivery ratio        — genuine vs intraday activity
5. Options skew          — 25-delta risk reversal (fear vs greed)
6. Max pain distance     — where market makers want expiry to settle
7. India VIX features    — level, change, percentile
8. FII/DII momentum      — rolling net flows

These features materially improve ML model accuracy because they capture
FUNDAMENTAL DRIVERS that pure price data misses.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("advanced_features")

_CACHE_DIR = Path("data/feature_cache")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Cross-Asset Feature Fetcher ───────────────────────────────────────────────

def fetch_cross_asset_features(lookback_days: int = 60) -> pd.DataFrame:
    """
    Fetch cross-asset OHLCV for macro context:
    - USDINR (currency)
    - Gold MCX (commodities)
    - Crude Oil MCX
    - US S&P 500 futures proxy (via NSE SGX)

    Uses Upstox for MCX/NSE, Yahoo Finance as fallback.
    Returns DataFrame indexed by date with columns per asset.
    """
    cache_path = _CACHE_DIR / f"cross_asset_{pd.Timestamp.today().date()}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    dfs: Dict[str, pd.DataFrame] = {}

    # Try yfinance as the most reliable free source
    try:
        import yfinance as yf
        symbols_yf = {
            "usdinr":   "USDINR=X",
            "gold":     "GC=F",
            "crude":    "CL=F",
            "sp500fut": "ES=F",
            "vix_us":   "^VIX",
        }
        end = pd.Timestamp.today()
        start = end - pd.Timedelta(days=lookback_days + 10)
        for name, ticker in symbols_yf.items():
            try:
                df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
                if not df.empty:
                    dfs[name] = df[["Close"]].rename(columns={"Close": name})
            except Exception:
                pass
    except ImportError:
        logger.debug("yfinance not available for cross-asset features")

    # Fallback: flat arrays (features will be zero)
    if not dfs:
        logger.warning("Cross-asset data unavailable — returning empty frame")
        return pd.DataFrame()

    result = pd.concat(dfs.values(), axis=1).dropna(how="all")

    # Compute returns and normalised levels
    for col in result.columns:
        result[f"{col}_ret"] = result[col].pct_change()
        result[f"{col}_z20"] = (
            (result[col] - result[col].rolling(20).mean()) /
            result[col].rolling(20).std()
        )

    try:
        result.to_parquet(cache_path)
    except Exception:
        pass
    return result.tail(lookback_days)


# ── F&O OI Features ───────────────────────────────────────────────────────────

def compute_oi_features(option_chain: pd.DataFrame, spot: float) -> Dict[str, float]:
    """
    Compute F&O open interest features from option chain.

    Returns dict:
    - pcr_oi           : total put OI / total call OI
    - pcr_volume       : put volume / call volume
    - call_oi_buildup  : calls with rising OI near ATM (bearish)
    - put_oi_buildup   : puts with rising OI near ATM (bullish)
    - max_pain         : already in iv_surface, re-export here
    - max_pain_dist_pct: (spot - max_pain) / spot * 100
    - atm_straddle_iv  : IV of ATM straddle
    - skew_25d         : 25-delta risk reversal (call IV - put IV)
    """
    if option_chain.empty:
        return {}

    # Normalise column names
    chain = option_chain.copy()
    chain.columns = [c.lower().strip() for c in chain.columns]

    total_put_oi  = chain.get("put_oi",  pd.Series(dtype=float)).sum()
    total_call_oi = chain.get("call_oi", pd.Series(dtype=float)).sum()
    total_put_vol = chain.get("put_volume",  pd.Series(dtype=float)).sum()
    total_call_vol= chain.get("call_volume", pd.Series(dtype=float)).sum()

    pcr_oi  = total_put_oi  / total_call_oi  if total_call_oi  > 0 else 1.0
    pcr_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

    # ATM ± 2% strikes for targeted OI analysis
    atm_mask = (chain["strike"] >= spot * 0.98) & (chain["strike"] <= spot * 1.02)
    atm_chain = chain[atm_mask]

    call_oi_atm = atm_chain.get("call_oi", pd.Series(dtype=float)).sum()
    put_oi_atm  = atm_chain.get("put_oi",  pd.Series(dtype=float)).sum()

    # Max pain
    from data_engine.upstox.iv_surface import _calculate_max_pain, IVPoint
    max_pain_strike = spot
    try:
        points = [
            IVPoint(
                strike=float(r.get("strike", spot)),
                expiry=str(r.get("expiry", "")),
                days_to_expiry=int(r.get("dte", 14)),
                call_iv=float(r.get("call_iv", 0.15)),
                put_iv=float(r.get("put_iv", 0.15)),
                mid_iv=float(r.get("mid_iv", 0.15)),
                call_price=float(r.get("call_ltp", 0)),
                put_price=float(r.get("put_ltp", 0)),
                call_delta=float(r.get("call_delta", 0.5)),
                put_delta=float(r.get("put_delta", -0.5)),
                call_oi=int(r.get("call_oi", 0)),
                put_oi=int(r.get("put_oi", 0)),
            )
            for _, r in chain.iterrows()
        ]
        max_pain_strike = _calculate_max_pain(points, spot)
    except Exception:
        pass

    max_pain_dist = (spot - max_pain_strike) / spot * 100.0

    # 25-delta skew (proxy: OTM call IV - OTM put IV)
    otm_calls = chain[chain["strike"] > spot * 1.01]
    otm_puts  = chain[chain["strike"] < spot * 0.99]
    call_iv_otm = float(otm_calls["call_iv"].mean()) if "call_iv" in otm_calls and not otm_calls.empty else 0.0
    put_iv_otm  = float(otm_puts["put_iv"].mean())   if "put_iv"  in otm_puts  and not otm_puts.empty  else 0.0
    skew_25d = call_iv_otm - put_iv_otm

    # ATM straddle IV
    atm_call_iv = float(atm_chain["call_iv"].mean()) if "call_iv" in atm_chain and not atm_chain.empty else 0.0

    return {
        "pcr_oi":           round(pcr_oi, 4),
        "pcr_volume":       round(pcr_vol, 4),
        "call_oi_atm":      float(call_oi_atm),
        "put_oi_atm":       float(put_oi_atm),
        "atm_put_call_ratio": round(put_oi_atm / call_oi_atm if call_oi_atm > 0 else 1.0, 4),
        "max_pain":         round(max_pain_strike, 2),
        "max_pain_dist_pct": round(max_pain_dist, 3),
        "atm_iv":           round(atm_call_iv, 5),
        "skew_25d":         round(skew_25d, 5),
    }


# ── Advanced Feature Builder ───────────────────────────────────────────────────

class AdvancedFeatureBuilder:
    """
    Builds the complete advanced feature matrix by combining:
    - OHLCV-derived technical features (from existing FeatureBuilder)
    - Options/F&O features
    - Cross-asset macro features
    - India VIX features
    - FII/DII flow features
    - Delivery ratio
    """

    def __init__(self, cfg: dict = None):
        self.cfg = cfg or {}
        self._cross_asset_cache: Optional[pd.DataFrame] = None
        self._cache_date: Optional[str] = None

    def _get_cross_asset(self) -> pd.DataFrame:
        today = str(pd.Timestamp.today().date())
        if self._cache_date != today or self._cross_asset_cache is None:
            self._cross_asset_cache = fetch_cross_asset_features(60)
            self._cache_date = today
        return self._cross_asset_cache

    def build(
        self,
        df: pd.DataFrame,
        symbol: str,
        option_chain: Optional[pd.DataFrame] = None,
        include_cross_asset: bool = True,
    ) -> pd.DataFrame:
        """
        Build full advanced feature matrix for ML training/inference.

        Returns DataFrame with all features, same length as df.
        """
        from feature_engine.feature_builder import FeatureBuilder
        # Start with standard OHLCV features
        fb   = FeatureBuilder()
        base = fb.build(df)

        result = base.copy()
        spot   = float(df["close"].iloc[-1]) if not df.empty else 0.0

        # ── F&O OI features ───────────────────────────────────────────────────
        if option_chain is not None and not option_chain.empty:
            oi_feats = compute_oi_features(option_chain, spot)
            for k, v in oi_feats.items():
                result[k] = v

        # ── India VIX features ────────────────────────────────────────────────
        try:
            from data_engine.upstox.india_vix import (
                fetch_vix_history_nse, classify_vix, vix_percentile,
            )
            vix_df = fetch_vix_history_nse(30)
            if not vix_df.empty and "close" in vix_df.columns:
                vix_vals     = vix_df["close"].values
                current_vix  = float(vix_vals[-1])
                vix_1d_chg   = float(vix_vals[-1] - vix_vals[-2]) if len(vix_vals) > 1 else 0.0
                vix_5d_chg   = float(vix_vals[-1] - vix_vals[-5]) if len(vix_vals) > 4 else 0.0
                vix_pct      = vix_percentile(current_vix, vix_vals[:-1].tolist())
                regime_code  = {
                    "EXTREME_FEAR": -2, "HIGH_FEAR": -1, "ELEVATED": 0,
                    "NORMAL": 0, "LOW": 1, "EXTREME_COMPLACENCY": 2,
                }.get(classify_vix(current_vix), 0)

                result["vix_level"]      = current_vix
                result["vix_1d_change"]  = vix_1d_chg
                result["vix_5d_change"]  = vix_5d_chg
                result["vix_percentile"] = vix_pct
                result["vix_regime"]     = regime_code
        except Exception as e:
            logger.debug(f"VIX features failed: {e}")

        # ── FII/DII flow features ─────────────────────────────────────────────
        try:
            from data_engine.nse_data import get_fii_sentiment
            sent = get_fii_sentiment(lookback_days=5)
            result["fii_net_5d"]   = sent.get("fii_net", 0.0)
            result["dii_net_5d"]   = sent.get("dii_net", 0.0)
            result["fii_signal"]   = {"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0}.get(
                sent.get("signal", "NEUTRAL"), 0
            )
        except Exception as e:
            logger.debug(f"FII features failed: {e}")

        # ── Cross-asset macro features ────────────────────────────────────────
        if include_cross_asset:
            try:
                ca = self._get_cross_asset()
                if not ca.empty and len(ca) >= 2:
                    last_row = ca.iloc[-1]
                    for col in ["usdinr_ret", "gold_ret", "crude_ret",
                                "usdinr_z20", "gold_z20", "crude_z20", "vix_us"]:
                        if col in last_row.index:
                            result[col] = float(last_row[col]) if not pd.isna(last_row[col]) else 0.0
            except Exception as e:
                logger.debug(f"Cross-asset features failed: {e}")

        # ── Delivery features ─────────────────────────────────────────────────
        try:
            from data_engine.nse_data import get_delivery_pct
            deliv = get_delivery_pct(symbol)
            result["delivery_pct"] = deliv if deliv is not None else 50.0
        except Exception:
            pass

        return result

    def feature_names(self, df: pd.DataFrame, symbol: str) -> List[str]:
        """Returns list of all feature column names."""
        feat_df = self.build(df.tail(30), symbol)
        return [c for c in feat_df.columns if c not in df.columns]


# ── Convenience: rolling cross-asset correlation ──────────────────────────────

def nifty_cross_asset_correlation(
    nifty_returns: pd.Series,
    lookback: int = 20,
) -> Dict[str, float]:
    """
    Rolling correlation of Nifty returns vs cross-asset returns.
    High correlation with Gold = flight-to-safety; high with crude = energy-driven.
    """
    ca = fetch_cross_asset_features(lookback + 5)
    if ca.empty:
        return {}

    result: Dict[str, float] = {}
    for col in ["usdinr_ret", "gold_ret", "crude_ret", "sp500fut_ret"]:
        if col not in ca.columns:
            continue
        asset_ret = ca[col].dropna()
        common    = nifty_returns.align(asset_ret, join="inner")[0]
        asset_common = nifty_returns.align(asset_ret, join="inner")[1]
        if len(common) >= 5:
            corr = float(common.tail(lookback).corr(asset_common.tail(lookback)))
            result[col.replace("_ret", "_corr")] = round(corr, 4)
    return result
