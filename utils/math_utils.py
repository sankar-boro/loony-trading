import numpy as np


def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_change(new: float, old: float) -> float:
    return safe_divide(new - old, abs(old))


def rolling_zscore(series: np.ndarray, window: int = 20) -> np.ndarray:
    result = np.full_like(series, np.nan, dtype=float)
    for i in range(window, len(series)):
        window_data = series[i - window:i]
        mean = np.mean(window_data)
        std = np.std(window_data)
        result[i] = safe_divide(series[i] - mean, std)
    return result


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    std = np.std(excess)
    return safe_divide(np.mean(excess) * np.sqrt(periods), std)


def sortino_ratio(returns: np.ndarray, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    downside = excess[excess < 0]
    downside_std = np.std(downside) if len(downside) > 0 else 0.0
    return safe_divide(np.mean(excess) * np.sqrt(periods), downside_std)


def max_drawdown(equity_curve: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - peak) / peak
    return float(np.min(drawdown))


def profit_factor(pnl_series: np.ndarray) -> float:
    gross_profit = np.sum(pnl_series[pnl_series > 0])
    gross_loss = abs(np.sum(pnl_series[pnl_series < 0]))
    return safe_divide(gross_profit, gross_loss)
