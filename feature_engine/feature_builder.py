import pandas as pd
import numpy as np
from .indicators import TechnicalIndicators as TI
from utils.math_utils import rolling_zscore
from utils.logger import get_logger

logger = get_logger("feature_builder")


class FeatureBuilder:
    """
    Adds all indicator-derived columns to a raw OHLCV DataFrame.
    Returns the enriched frame — does NOT mutate the input.
    """

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        c = df["close"]
        df = self._moving_averages(df, c)
        df = self._oscillators(df, c)
        df = self._volatility(df, c)
        df = self._volume(df)
        df = self._trend(df)
        df = self._price_features(df, c)
        return df.dropna()

    def _moving_averages(self, df: pd.DataFrame, c: pd.Series) -> pd.DataFrame:
        for p in [9, 20, 50, 200]:
            df[f"ema_{p}"] = TI.ema(c, p)
            df[f"sma_{p}"] = TI.sma(c, p)
        df["vwap"] = TI.vwap(df)
        df["ema_cross_9_20"] = (df["ema_9"] - df["ema_20"]).apply(np.sign)
        df["ema_cross_20_50"] = (df["ema_20"] - df["ema_50"]).apply(np.sign)
        df["ema_cross_50_200"] = (df["ema_50"] - df["ema_200"]).apply(np.sign)
        return df

    def _oscillators(self, df: pd.DataFrame, c: pd.Series) -> pd.DataFrame:
        df["rsi_14"] = TI.rsi(c, 14)
        df["rsi_7"] = TI.rsi(c, 7)
        df["rsi_21"] = TI.rsi(c, 21)
        macd, signal, hist = TI.macd(c)
        df["macd"] = macd
        df["macd_signal"] = signal
        df["macd_hist"] = hist
        df["macd_cross"] = np.sign(df["macd_hist"])
        k, d = TI.stochastic(df)
        df["stoch_k"] = k
        df["stoch_d"] = d
        df["cci"] = TI.cci(df)
        df["roc_10"] = TI.roc(c, 10)
        df["roc_20"] = TI.roc(c, 20)
        return df

    def _volatility(self, df: pd.DataFrame, c: pd.Series) -> pd.DataFrame:
        df["atr_14"] = TI.atr(df, 14)
        df["atr_pct"] = df["atr_14"] / c
        upper, mid, lower = TI.bollinger_bands(c)
        df["bb_upper"] = upper
        df["bb_mid"] = mid
        df["bb_lower"] = lower
        df["bb_width"] = (upper - lower) / mid
        df["bb_pct"] = (c - lower) / (upper - lower).replace(0, np.nan)
        df["historical_vol"] = c.pct_change().rolling(20).std() * np.sqrt(252)
        return df

    def _volume(self, df: pd.DataFrame) -> pd.DataFrame:
        df["obv"] = TI.obv(df)
        df["volume_sma_20"] = TI.sma(df["volume"], 20)
        df["volume_ratio"] = df["volume"] / df["volume_sma_20"].replace(0, np.nan)
        df["vwap_diff"] = (df["close"] - df["vwap"]) / df["vwap"]
        return df

    def _trend(self, df: pd.DataFrame) -> pd.DataFrame:
        adx_result = TI.adx(df)
        df["adx"] = adx_result[0]
        df["di_plus"] = adx_result[1]
        df["di_minus"] = adx_result[2]
        st, direction = TI.supertrend(df)
        df["supertrend"] = st
        df["supertrend_dir"] = direction
        dc_upper, dc_mid, dc_lower = TI.donchian_channel(df)
        df["dc_upper"] = dc_upper
        df["dc_lower"] = dc_lower
        df["dc_pct"] = (df["close"] - dc_lower) / (dc_upper - dc_lower).replace(0, np.nan)
        return df

    def _price_features(self, df: pd.DataFrame, c: pd.Series) -> pd.DataFrame:
        df["return_1"] = c.pct_change(1)
        df["return_5"] = c.pct_change(5)
        df["return_10"] = c.pct_change(10)
        df["zscore_20"] = pd.Series(rolling_zscore(c.values, 20), index=df.index)
        df["zscore_50"] = pd.Series(rolling_zscore(c.values, 50), index=df.index)
        df["hl_range_pct"] = (df["high"] - df["low"]) / c
        df["close_position"] = (c - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)
        df["gap"] = (df["open"] - c.shift(1)) / c.shift(1)
        return df

    def build_multitimeframe(self, frames: dict[str, pd.DataFrame],
                              primary_tf: str = "1h") -> pd.DataFrame:
        """Merge features from multiple timeframes into the primary frame."""
        primary = self.build(frames[primary_tf])
        for tf, df_tf in frames.items():
            if tf == primary_tf:
                continue
            enriched = self.build(df_tf)
            for col in ["rsi_14", "adx", "macd_hist", "bb_pct", "supertrend_dir"]:
                if col in enriched.columns:
                    resampled = enriched[col].reindex(primary.index, method="ffill")
                    primary[f"{col}_{tf}"] = resampled
        return primary
