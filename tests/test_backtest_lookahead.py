"""Regression test for spec section 44 (Data Leakage Prevention): a signal
generated at bar i must never see price data from bars > i. The backtester
achieves this via `window = df.iloc[:i]` in Backtester.run — this test
locks that guarantee in so a future refactor can't silently reintroduce
look-ahead bias."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from typing import Optional

from backtester import Backtester
from strategies.base import BaseStrategy, Signal

WARMUP = 10
N_BARS = 60
LEAK_BAR = 40          # index where a huge, otherwise-undetectable price spike appears
SPIKE_CLOSE = 1_000_000.0
BASELINE_CLOSE = 100.0

CFG = {
    "risk": {"max_risk_per_trade": 0.01},
    "execution": {"slippage_pct": 0.001, "commission": 0.001},
    "data": {"warmup_bars": WARMUP},
}


class RecordingStrategy(BaseStrategy):
    """Never trades — just records what it was shown at each call, so the
    test can assert the window boundary directly rather than inferring it
    from trade behaviour."""
    name = "recording"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.seen: list[tuple[int, float]] = []  # (window_len, max_close_in_window)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        self.seen.append((len(df), float(df["close"].max())))
        return None


def _make_leaking_df() -> pd.DataFrame:
    close = np.full(N_BARS, BASELINE_CLOSE)
    close[LEAK_BAR] = SPIKE_CLOSE
    return pd.DataFrame({
        "open": close, "high": close, "low": close, "close": close,
        "volume": np.full(N_BARS, 1000.0),
    })


def test_backtester_never_shows_strategy_future_bars():
    df = _make_leaking_df()
    bt = Backtester(CFG, initial_capital=10_000)
    strategy = RecordingStrategy({})
    bt.run(df, "TEST", strategy=strategy)

    assert strategy.seen, "strategy was never called — test setup is broken"
    # Sanity: the run must actually reach past LEAK_BAR, and the window length
    # at each call must equal the current bar index (df.iloc[:i] has len i).
    assert max(w for w, _ in strategy.seen) > LEAK_BAR

    for window_len, window_max_close in strategy.seen:
        if window_len <= LEAK_BAR:
            assert window_max_close == pytest.approx(BASELINE_CLOSE), (
                f"look-ahead bias: window of length {window_len} (bars [0, {window_len})) "
                f"saw the spike planted at bar {LEAK_BAR}"
            )
        else:
            assert window_max_close == pytest.approx(SPIKE_CLOSE), (
                "test setup invalid: window past the leak bar should see the spike"
            )


def _make_price_df(n: int = 600) -> pd.DataFrame:
    np.random.seed(0)
    price = 40000 + np.cumsum(np.random.normal(5, 300, n))
    return pd.DataFrame({
        "open": price,
        "high": price + np.abs(np.random.normal(0, 200, n)),
        "low": price - np.abs(np.random.normal(0, 200, n)),
        "close": price + np.random.normal(0, 100, n),
        "volume": np.abs(np.random.normal(1000, 300, n)),
    })


def test_truncating_future_bars_does_not_change_past_trades():
    """The gold-standard look-ahead check: feed the backtester a truncated
    slice of the same price history and confirm every trade that fully
    closed before the truncation point is byte-identical to the equivalent
    run on the full series. If future bars were leaking into past decisions,
    removing them would change earlier trades — it must not."""
    from strategies.trend.ema_crossover import EmaCrossoverStrategy

    df_full = _make_price_df(600)
    CUT = 300
    df_truncated = df_full.iloc[:CUT].copy()

    bt_full = Backtester(CFG, initial_capital=10_000)
    result_full = bt_full.run(df_full, "TEST", strategy=EmaCrossoverStrategy({}))

    bt_trunc = Backtester(CFG, initial_capital=10_000)
    result_trunc = bt_trunc.run(df_truncated, "TEST", strategy=EmaCrossoverStrategy({}))

    def _closed_before_cut(trades):
        # Exclude any trade force-closed by hitting end-of-data — that's an
        # artifact of truncation itself, not a look-ahead signal.
        return [
            (t.entry_bar, t.direction, t.entry_price, t.exit_bar, t.exit_price, t.pnl, t.reason)
            for t in trades
            if t.exit_bar < CUT and t.reason != "end_of_data"
        ]

    full_trades = _closed_before_cut(result_full.trades)
    trunc_trades = _closed_before_cut(result_trunc.trades)

    assert full_trades, "test setup produced no closed trades before the cutoff — widen the range"
    assert full_trades == trunc_trades
