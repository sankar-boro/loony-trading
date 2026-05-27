import numpy as np
import pandas as pd
from utils.math_utils import safe_divide


class TechnicalIndicators:
    """
    Pure-numpy / pandas indicator library.
    All methods operate on pd.Series or np.ndarray and return the same type.
    No ta-lib dependency; vendored implementations for portability.
    """

    # ── Moving Averages ───────────────────────────────────────────────────────

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()

    @staticmethod
    def wma(series: pd.Series, period: int) -> pd.Series:
        weights = np.arange(1, period + 1)
        return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        return (tp * df["volume"]).cumsum() / df["volume"].cumsum()

    # ── Oscillators ───────────────────────────────────────────────────────────

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26,
             signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def stochastic(df: pd.DataFrame, k_period: int = 14,
                   d_period: int = 3) -> tuple[pd.Series, pd.Series]:
        low_min = df["low"].rolling(k_period).min()
        high_max = df["high"].rolling(k_period).max()
        k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        d = k.rolling(d_period).mean()
        return k, d

    @staticmethod
    def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        return (tp - sma) / (0.015 * mad.replace(0, np.nan))

    @staticmethod
    def roc(series: pd.Series, period: int = 10) -> pd.Series:
        return series.pct_change(periods=period) * 100

    # ── Volatility ────────────────────────────────────────────────────────────

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.ewm(com=period - 1, adjust=False).mean()

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20,
                        std_dev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
        mid = series.rolling(period).mean()
        std = series.rolling(period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    @staticmethod
    def keltner_channels(df: pd.DataFrame, ema_period: int = 20,
                         atr_mult: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
        mid = TechnicalIndicators.ema(df["close"], ema_period)
        atr = TechnicalIndicators.atr(df, ema_period)
        return mid + atr_mult * atr, mid, mid - atr_mult * atr

    # ── Trend ─────────────────────────────────────────────────────────────────

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        up = df["high"].diff()
        down = -df["low"].diff()
        pos_dm = up.where((up > down) & (up > 0), 0)
        neg_dm = down.where((down > up) & (down > 0), 0)
        atr = TechnicalIndicators.atr(df, period)
        pos_di = 100 * pos_dm.ewm(com=period - 1, adjust=False).mean() / atr.replace(0, np.nan)
        neg_di = 100 * neg_dm.ewm(com=period - 1, adjust=False).mean() / atr.replace(0, np.nan)
        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan)
        return dx.ewm(com=period - 1, adjust=False).mean(), pos_di, neg_di

    @staticmethod
    def supertrend(df: pd.DataFrame, period: int = 7,
                   multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
        atr = TechnicalIndicators.atr(df, period)
        hl2 = (df["high"] + df["low"]) / 2
        upper = hl2 + multiplier * atr
        lower = hl2 - multiplier * atr
        supertrend = pd.Series(np.nan, index=df.index)
        direction = pd.Series(1, index=df.index)
        for i in range(1, len(df)):
            if df["close"].iloc[i] > upper.iloc[i - 1]:
                direction.iloc[i] = 1
            elif df["close"].iloc[i] < lower.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]
            if direction.iloc[i] == 1:
                supertrend.iloc[i] = lower.iloc[i]
            else:
                supertrend.iloc[i] = upper.iloc[i]
        return supertrend, direction

    @staticmethod
    def donchian_channel(df: pd.DataFrame,
                         period: int = 20) -> tuple[pd.Series, pd.Series, pd.Series]:
        upper = df["high"].rolling(period).max()
        lower = df["low"].rolling(period).min()
        mid = (upper + lower) / 2
        return upper, mid, lower

    # ── Volume ────────────────────────────────────────────────────────────────

    @staticmethod
    def obv(df: pd.DataFrame) -> pd.Series:
        direction = np.sign(df["close"].diff()).fillna(0)
        return (direction * df["volume"]).cumsum()

    @staticmethod
    def vwap_bands(df: pd.DataFrame, std_dev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
        vwap = TechnicalIndicators.vwap(df)
        tp = (df["high"] + df["low"] + df["close"]) / 3
        variance = ((tp - vwap) ** 2 * df["volume"]).cumsum() / df["volume"].cumsum()
        std = variance.apply(np.sqrt)
        return vwap + std_dev * std, vwap, vwap - std_dev * std

    # ── Support / Resistance ─────────────────────────────────────────────────

    @staticmethod
    def pivot_points(df: pd.DataFrame) -> dict:
        prev = df.iloc[-2]
        pp = (prev["high"] + prev["low"] + prev["close"]) / 3
        return {
            "pp": pp,
            "r1": 2 * pp - prev["low"],
            "r2": pp + (prev["high"] - prev["low"]),
            "r3": prev["high"] + 2 * (pp - prev["low"]),
            "s1": 2 * pp - prev["high"],
            "s2": pp - (prev["high"] - prev["low"]),
            "s3": prev["low"] - 2 * (prev["high"] - pp),
        }
