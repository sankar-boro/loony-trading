#!/usr/bin/env python
"""
Paper Trading Session
=====================

Runs a live paper-trading session that:
  • Polls Upstox LTP every N seconds for real market prices
  • Runs MetaStrategyEngine + FeatureBuilder to generate entry signals
  • Tracks virtual positions with full RiskManager (stop-loss, take-profit, trailing stop)
  • Displays a live dashboard: open positions, today's P&L, signal log

No real orders are ever placed.  All capital is virtual.

Usage:
    python scripts/paper_trade.py
    python scripts/paper_trade.py --symbols RELIANCE,TCS,HDFCBANK
    python scripts/paper_trade.py --capital 500000
    python scripts/paper_trade.py --tick 30           # poll every 30s (default: 60)
    python scripts/paper_trade.py --signal-every 5    # generate signals every 5 ticks
    python scripts/paper_trade.py --max-positions 5
    python scripts/paper_trade.py --timeframe 1d      # historical data timeframe
    python scripts/paper_trade.py --token eyJ0eXAi...
    python scripts/paper_trade.py --log-file paper_trade.jsonl  # append trade log
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Colour helpers ────────────────────────────────────────────────────────────

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
C = "\033[96m"; DIM = "\033[2m"; E = "\033[0m"; CLEAR = "\033[2J\033[H"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def yellow(s): return f"{Y}{s}{E}"
def cyan(s):   return f"{C}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"

def pnl_s(v: float) -> str:
    s = f"₹{v:>+11,.2f}"
    return green(s) if v > 0 else (red(s) if v < 0 else s)

def pct_s(v: float) -> str:
    s = f"{v:>+6.2f}%"
    return green(s) if v > 0 else (red(s) if v < 0 else s)


# ── Instrument registry ───────────────────────────────────────────────────────

INSTRUMENTS: dict[str, str] = {
    "NIFTY50":    "NSE_INDEX|Nifty 50",
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "FINNIFTY":   "NSE_INDEX|Nifty Fin Service",
    "RELIANCE":   "NSE_EQ|INE002A01018",
    "TCS":        "NSE_EQ|INE467B01029",
    "HDFCBANK":   "NSE_EQ|INE040A01034",
    "INFY":       "NSE_EQ|INE009A01021",
    "ICICIBANK":  "NSE_EQ|INE090A01021",
    "SBIN":       "NSE_EQ|INE062A01020",
    "BAJFINANCE": "NSE_EQ|INE296A01024",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "KOTAKBANK":  "NSE_EQ|INE237A01028",
    "LT":         "NSE_EQ|INE018A01030",
    "AXISBANK":   "NSE_EQ|INE238A01034",
    "WIPRO":      "NSE_EQ|INE075A01022",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "HCLTECH":    "NSE_EQ|INE860A01027",
    "ITC":        "NSE_EQ|INE154A01025",
    "SUNPHARMA":  "NSE_EQ|INE044A01036",
    "ONGC":       "NSE_EQ|INE213A01029",
    "TITAN":      "NSE_EQ|INE280A01028",
    "HINDUNILVR": "NSE_EQ|INE030A01027",
}

DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BAJFINANCE", "AXISBANK",
]

STATE_FILE = ROOT / "data" / "live_positions.json"

_TF_CONFIG = {
    "1d":  ("day",      365),
    "1h":  ("60minute", 90),
    "30m": ("30minute", 60),
    "15m": ("15minute", 45),
}

# How often (seconds) to refresh intraday candles — one candle period
_CANDLE_SECONDS = {
    "day":       86400,
    "60minute":  3600,
    "30minute":  1800,
    "15minute":  900,
}


# ── Token loading ─────────────────────────────────────────────────────────────

def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v


def _get_token(explicit: str = None) -> tuple[str, float]:
    """
    Returns (token, age_hours).
    age_hours = -1 means unknown (env var with no matching token file).
    Raises SystemExit if token is expired (>23h) or missing.
    """
    tf = ROOT / "data" / "upstox_token.json"

    file_token, file_age = "", -1.0
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            file_age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token"):
                file_token = d["access_token"]
        except Exception:
            pass

    token = explicit or os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip() or file_token

    if not token:
        print(f"\n{R}No token found.{E}")
        print("Run: python scripts/upstox_login.py")
        sys.exit(1)

    age = file_age if file_token and token == file_token else -1.0

    if age >= 23:
        print(f"\n{R}Token expired{E} (age {age:.1f}h — Upstox tokens last 23h).")
        print("Run: python scripts/upstox_login.py --force")
        print("Or set up auto-renewal: bash scripts/auto_login.sh")
        sys.exit(1)

    if 0 <= age >= 20:
        print(f"{Y}Token is {age:.1f}h old — expires in {23 - age:.1f}h.{E}")
        print("  Consider running: bash scripts/auto_login.sh")

    return token, age


# ── Upstox API helpers ────────────────────────────────────────────────────────

def _encode(key: str) -> str:
    return key.replace("|", "%7C").replace(" ", "%20")


def _fetch_ltp(token: str, instrument_keys: list[str]) -> dict[str, float]:
    import requests
    if not instrument_keys:
        return {}
    keys = ",".join(_encode(k) for k in instrument_keys)
    try:
        r = requests.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("data", {})
        result = {}
        for k, v in data.items():
            orig_key = k.replace(":", "|")
            result[orig_key] = float(v.get("last_price", 0) or 0)
        return result
    except Exception:
        return {}


def _fetch_ohlcv(token: str, instrument_key: str, interval: str, days: int):
    import requests
    import pandas as pd

    key = _encode(instrument_key)
    to_d = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()
    url = f"https://api.upstox.com/v2/historical-candle/{key}/{interval}/{to_d}/{from_d}"

    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=12,
        )
        if r.status_code != 200:
            return pd.DataFrame()
        candles = r.json().get("data", {}).get("candles", [])
    except Exception:
        return pd.DataFrame()

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].apply(float)
    return df


# ── Intraday data refresh ─────────────────────────────────────────────────────

def _refresh_intraday(token: str, sym: str, ikey: str,
                      interval: str, df_old, fb) -> "pd.DataFrame":
    """
    Fetch the latest intraday candles and merge with df_old.
    For daily data this is a no-op — LTP update is sufficient.
    Returns the updated DataFrame (or df_old on failure).
    """
    if interval == "day":
        return df_old

    df_new = _fetch_ohlcv(token, ikey, interval, days=2)
    if df_new.empty:
        return df_old

    import pandas as pd
    df_combined = pd.concat([df_old, df_new])
    df_combined = df_combined[~df_combined.index.duplicated(keep="last")]
    df_combined = df_combined.sort_index()

    if fb is not None:
        try:
            df_combined = fb.build(df_combined)
        except Exception:
            pass
    return df_combined


# ── Virtual position tracking ─────────────────────────────────────────────────

@dataclass
class VirtualPosition:
    symbol: str
    direction: int          # 1=long, -1=short
    size: float             # number of shares/units
    entry_price: float
    stop_loss: float
    take_profit: float
    trailing_stop_pct: float
    strategy: str
    entry_time: str
    peak_price: float = 0.0
    current_price: float = 0.0
    unrealised_pnl: float = 0.0

    def mark(self, price: float) -> None:
        self.current_price = price
        if self.direction == 1 and price > self.peak_price:
            self.peak_price = price
            new_sl = price * (1 - self.trailing_stop_pct)
            if new_sl > self.stop_loss:
                self.stop_loss = new_sl
        elif self.direction == -1 and (self.peak_price == 0 or price < self.peak_price):
            self.peak_price = price
            new_sl = price * (1 + self.trailing_stop_pct)
            if new_sl < self.stop_loss:
                self.stop_loss = new_sl
        self.unrealised_pnl = (price - self.entry_price) * self.direction * self.size

    def should_close(self, price: float) -> Optional[str]:
        if self.direction == 1:
            if price <= self.stop_loss:
                return "stop_loss"
            if price >= self.take_profit:
                return "take_profit"
        else:
            if price >= self.stop_loss:
                return "stop_loss"
            if price <= self.take_profit:
                return "take_profit"
        return None


@dataclass
class ClosedTrade:
    symbol: str
    direction: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    reason: str
    strategy: str
    entry_time: str
    exit_time: str

    @property
    def pnl_pct(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price * self.direction * 100


class PaperPortfolio:
    def __init__(self, capital: float, max_positions: int,
                 risk_per_trade: float = 0.01, trailing_stop_pct: float = 0.02):
        self.initial_capital = capital
        self.cash = capital
        self.max_positions = max_positions
        self.risk_per_trade = risk_per_trade
        self.trailing_stop_pct = trailing_stop_pct
        self.positions: dict[str, VirtualPosition] = {}
        self.closed_trades: list[ClosedTrade] = []
        self.signal_log: list[dict] = []
        self._commission = 0.001

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.unrealised_pnl + p.entry_price * abs(p.size)
                               for p in self.positions.values())

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.initial_capital

    @property
    def realised_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def unrealised_pnl(self) -> float:
        return sum(p.unrealised_pnl for p in self.positions.values())

    def _position_size(self, price: float, stop_loss: float) -> float:
        risk_amount = self.cash * self.risk_per_trade
        price_risk = abs(price - stop_loss) if stop_loss else price * 0.02
        if price_risk == 0:
            return 0.0
        size = risk_amount / price_risk
        cost = size * price
        if cost > self.cash * 0.25:
            size = (self.cash * 0.25) / price
        return max(1.0, round(size, 0))

    def on_signal(self, signal) -> Optional[str]:
        from strategies.base import SignalType

        sym = signal.symbol
        st = signal.signal_type

        # Close on close-signals
        if st in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            if sym in self.positions:
                return self._close_position(sym, signal.price, "signal_close")
            return None

        # Skip HOLDs
        if st == SignalType.HOLD:
            return None

        # Don't re-enter if already in same direction
        if sym in self.positions:
            pos = self.positions[sym]
            if (st == SignalType.BUY and pos.direction == 1) or \
               (st == SignalType.SELL and pos.direction == -1):
                return None
            # Reverse: close old position first
            self._close_position(sym, signal.price, "reverse_signal")

        # Check position limit and available cash
        if len(self.positions) >= self.max_positions:
            return None
        if self.cash < 1000:
            return None

        direction = 1 if st == SignalType.BUY else -1
        price = signal.price
        sl = signal.stop_loss or price * (1 - direction * 0.02)
        tp = signal.take_profit or price * (1 + direction * 0.04)
        size = self._position_size(price, sl)

        if size < 1:
            return None

        cost = size * price * (1 + self._commission)
        if cost > self.cash:
            size = max(1.0, int(self.cash / (price * (1 + self._commission))))
            cost = size * price * (1 + self._commission)

        self.cash -= cost
        self.positions[sym] = VirtualPosition(
            symbol=sym,
            direction=direction,
            size=size,
            entry_price=price,
            stop_loss=sl,
            take_profit=tp,
            trailing_stop_pct=self.trailing_stop_pct,
            strategy=signal.strategy,
            entry_time=datetime.now().strftime("%H:%M:%S"),
            peak_price=price,
            current_price=price,
        )

        action = "BUY " if direction == 1 else "SELL"
        msg = (f"{action} {int(size)} × {sym} @ ₹{price:,.2f}  "
               f"SL:₹{sl:,.2f}  TP:₹{tp:,.2f}  [{signal.strategy}]")
        self.signal_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": action.strip(),
            "symbol": sym,
            "price": price,
            "size": size,
            "sl": sl,
            "tp": tp,
            "strategy": signal.strategy,
            "confidence": signal.confidence,
        })
        return msg

    def _close_position(self, symbol: str, price: float, reason: str) -> str:
        pos = self.positions.pop(symbol)
        exit_price = price
        pnl = (exit_price - pos.entry_price) * pos.direction * pos.size
        pnl -= exit_price * pos.size * self._commission
        self.cash += pos.entry_price * pos.size + pnl
        trade = ClosedTrade(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size,
            pnl=pnl,
            reason=reason,
            strategy=pos.strategy,
            entry_time=pos.entry_time,
            exit_time=datetime.now().strftime("%H:%M:%S"),
        )
        self.closed_trades.append(trade)
        self.signal_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": "CLOSE",
            "symbol": symbol,
            "price": exit_price,
            "size": pos.size,
            "pnl": pnl,
            "reason": reason,
        })
        dir_s = "LONG" if pos.direction == 1 else "SHORT"
        return (f"CLOSE {dir_s} {int(pos.size)} × {symbol} @ ₹{exit_price:,.2f}  "
                f"P&L:{pnl_s(pnl)}  [{reason}]")

    def update_prices(self, prices: dict[str, float]) -> list[str]:
        """Mark all positions to market. Returns list of auto-close messages."""
        events = []
        for sym, pos in list(self.positions.items()):
            price = prices.get(INSTRUMENTS.get(sym, ""), 0.0)
            if not price:
                continue
            pos.mark(price)
            reason = pos.should_close(price)
            if reason:
                msg = self._close_position(sym, price, reason)
                events.append(msg)
        return events

    @property
    def win_rate(self) -> float:
        wins = sum(1 for t in self.closed_trades if t.pnl > 0)
        return wins / len(self.closed_trades) * 100 if self.closed_trades else 0.0


# ── State persistence ─────────────────────────────────────────────────────────

def _save_state(portfolio: PaperPortfolio) -> None:
    """Snapshot portfolio to disk so a crash/restart can resume the session."""
    state = {
        "saved_at": time.time(),
        "initial_capital": portfolio.initial_capital,
        "cash": portfolio.cash,
        "positions": [
            {
                "symbol": p.symbol,
                "direction": p.direction,
                "size": p.size,
                "entry_price": p.entry_price,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "trailing_stop_pct": p.trailing_stop_pct,
                "strategy": p.strategy,
                "entry_time": p.entry_time,
                "peak_price": p.peak_price,
                "current_price": p.current_price,
                "unrealised_pnl": p.unrealised_pnl,
            }
            for p in portfolio.positions.values()
        ],
        "closed_trades": [
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size": t.size,
                "pnl": t.pnl,
                "reason": t.reason,
                "strategy": t.strategy,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
            }
            for t in portfolio.closed_trades
        ],
        "signal_log": portfolio.signal_log[-200:],  # keep last 200 entries
    }
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _load_state(portfolio: PaperPortfolio, max_age_hours: float = 1.0) -> int:
    """
    Restore positions from the last snapshot if it is fresh (<max_age_hours old)
    and was created with the same initial capital. Returns the number of positions
    restored (0 means nothing was loaded).
    """
    if not STATE_FILE.exists():
        return 0
    try:
        state = json.loads(STATE_FILE.read_text())
        age_h = (time.time() - state.get("saved_at", 0)) / 3600
        if age_h > max_age_hours:
            return 0
        if abs(state.get("initial_capital", 0) - portfolio.initial_capital) > 1:
            return 0  # different session — don't restore
        portfolio.cash = float(state.get("cash", portfolio.cash))
        portfolio.closed_trades = [
            ClosedTrade(**t) for t in state.get("closed_trades", [])
        ]
        portfolio.signal_log = list(state.get("signal_log", []))
        for pd in state.get("positions", []):
            portfolio.positions[pd["symbol"]] = VirtualPosition(**pd)
        return len(portfolio.positions)
    except Exception:
        return 0


# ── Dashboard rendering ───────────────────────────────────────────────────────

def _render_dashboard(portfolio: PaperPortfolio, prices: dict[str, float],
                      tick_no: int, next_signal_in: int, events: list[str],
                      session_start: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(CLEAR, end="")

    total_pnl = portfolio.total_pnl
    pnl_pct = total_pnl / portfolio.initial_capital * 100

    print(bold(f"\n  Paper Trading  •  {now_str}  •  Session: {session_start}"))
    print(f"  Capital: ₹{portfolio.initial_capital:,.0f}  "
          f"Cash: ₹{portfolio.cash:,.0f}  "
          f"Total: ₹{portfolio.total_value:,.0f}  "
          f"P&L: {pnl_s(total_pnl)} ({pct_s(pnl_pct)})")
    print("  " + "═" * 100)

    # ── Open Positions ────────────────────────────────────────────────────────
    print(bold(f"\n  Open Positions ({len(portfolio.positions)})"))
    if portfolio.positions:
        print(f"  {'Symbol':<14}  {'Dir':<6}  {'Size':>6}  {'Entry':>12}  "
              f"{'LTP':>12}  {'Unrealised':>13}  {'P&L%':>7}  {'SL':>12}  {'TP':>12}  Strategy")
        print("  " + "─" * 110)
        for sym, pos in portfolio.positions.items():
            ikey = INSTRUMENTS.get(sym, "")
            ltp = prices.get(ikey, pos.current_price)
            if ltp:
                pos.mark(ltp)

            dir_s = green("LONG  ") if pos.direction == 1 else red("SHORT ")
            pnl_pct_pos = (pos.unrealised_pnl / (pos.entry_price * pos.size) * 100) \
                           if pos.entry_price else 0
            ltp_s = green(f"₹{ltp:>10,.2f}") if ltp >= pos.entry_price else red(f"₹{ltp:>10,.2f}")

            print(f"  {sym:<14}  {dir_s}  {int(pos.size):>6}  "
                  f"₹{pos.entry_price:>10,.2f}  {ltp_s}  "
                  f"{pnl_s(pos.unrealised_pnl)}  {pct_s(pnl_pct_pos)}  "
                  f"₹{pos.stop_loss:>10,.2f}  ₹{pos.take_profit:>10,.2f}  "
                  f"{pos.strategy[:18]}")
    else:
        print(f"  {dim('No open positions.')}")

    # ── Recent Events ─────────────────────────────────────────────────────────
    print(bold(f"\n  Recent Activity"))
    recent = portfolio.signal_log[-10:][::-1]
    if recent:
        for entry in recent:
            t = entry.get("time", "")
            action = entry.get("type", "")
            sym = entry.get("symbol", "")
            price = entry.get("price", 0.0)
            size = entry.get("size", 0)
            strat = entry.get("strategy", "")
            pnl = entry.get("pnl")
            conf = entry.get("confidence", 0)

            if action in ("BUY", "SELL"):
                color_fn = green if action == "BUY" else red
                print(f"  {dim(t)}  {color_fn(f'{action:<5}')} {int(size):>4}×{sym:<14}  "
                      f"@ ₹{price:,.2f}  [{strat}]  conf={conf:.2f}")
            elif action == "CLOSE":
                reason = entry.get("reason", "")
                pnl_disp = pnl_s(pnl) if pnl is not None else ""
                print(f"  {dim(t)}  {yellow('CLOSE')} {int(size):>4}×{sym:<14}  "
                      f"@ ₹{price:,.2f}  {pnl_disp}  [{reason}]")
    else:
        print(f"  {dim('Waiting for signals...')}")

    # ── Today's Closed Trades ─────────────────────────────────────────────────
    print(bold(f"\n  Closed Trades Today ({len(portfolio.closed_trades)})  "
               f"Win Rate: {portfolio.win_rate:.0f}%  "
               f"Realised P&L: {pnl_s(portfolio.realised_pnl)}"))

    if portfolio.closed_trades:
        recent_trades = portfolio.closed_trades[-5:][::-1]
        for t in recent_trades:
            dir_s = green("L") if t.direction == 1 else red("S")
            print(f"  {t.entry_time}→{t.exit_time}  [{dir_s}] {int(t.size):>4}×{t.symbol:<14}  "
                  f"₹{t.entry_price:,.2f}→₹{t.exit_price:,.2f}  "
                  f"{pnl_s(t.pnl)}  ({pct_s(t.pnl_pct)})  [{t.reason}]")

    # ── Status bar ────────────────────────────────────────────────────────────
    print("\n  " + "─" * 100)
    print(f"  {dim(f'Tick #{tick_no}  •  Next signal scan in {next_signal_in} ticks')}  "
          f"{dim('Ctrl+C to exit')}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Live paper trading session")
    parser.add_argument("--symbols",       default="",
                        help="Comma-separated symbols")
    parser.add_argument("--capital",       type=float, default=500_000,
                        help="Virtual capital in ₹ (default: 5,00,000)")
    parser.add_argument("--tick",          type=int, default=60,
                        help="Price poll interval in seconds (default: 60)")
    parser.add_argument("--signal-every",  type=int, default=5,
                        help="Generate signals every N ticks (default: 5)")
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--risk-per-trade",type=float, default=0.01,
                        help="Max risk per trade as fraction (default: 0.01 = 1%%)")
    parser.add_argument("--timeframe",     default="1d",
                        choices=list(_TF_CONFIG.keys()))
    parser.add_argument("--log-file",      default="",
                        help="JSONL file to append trade log")
    parser.add_argument("--token",         help="Explicit access token")
    args = parser.parse_args()

    _load_env()
    token, token_age = _get_token(args.token)   # exits on expired/missing

    raw_syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] \
               if args.symbols else DEFAULT_SYMBOLS
    resolved: list[tuple[str, str]] = []
    for sym in raw_syms:
        key = INSTRUMENTS.get(sym)
        if key:
            resolved.append((sym, key))
        else:
            print(f"{Y}Unknown symbol '{sym}' — skipped.{E}")

    if not resolved:
        print(f"{R}No valid symbols.{E}")
        sys.exit(1)

    syms = [s for s, _ in resolved]
    ikeys = [k for _, k in resolved]

    # Bootstrap strategy engine + feature builder
    print(f"\n{DIM}Loading strategy engine...{E}", end="", flush=True)
    engine = None
    fb = None
    try:
        from strategies.meta_engine import MetaStrategyEngine
        from feature_engine.feature_builder import FeatureBuilder
        _cfg = {
            "strategies": {"enabled": [], "weights": {}},
            "risk": {"max_risk_per_trade": args.risk_per_trade, "trailing_stop_pct": 0.02},
            "execution": {"commission": 0.001, "slippage_pct": 0.001},
            "data": {"warmup_bars": 50},
            "system": {"mode": "paper"},
        }
        engine = MetaStrategyEngine(_cfg)
        fb = FeatureBuilder()
        print(f"\r{DIM}Strategy engine ready — {len(engine.strategies)} strategies{E}   ")
    except Exception as e:
        print(f"\n{Y}Strategy engine load failed: {e}{E}")
        print(f"  {dim('Signals will not be generated. Only price tracking will run.')}")

    portfolio = PaperPortfolio(
        capital=args.capital,
        max_positions=args.max_positions,
        risk_per_trade=args.risk_per_trade,
        trailing_stop_pct=0.02,
    )

    restored = _load_state(portfolio)
    if restored:
        print(f"{G}Restored {restored} open position(s) from previous session snapshot.{E}")

    interval, days = _TF_CONFIG[args.timeframe]

    # Pre-load historical data for all symbols
    print(f"{DIM}Pre-loading historical data for {len(syms)} symbols...{E}")
    hist_data: dict[str, "pd.DataFrame"] = {}
    for sym, ikey in resolved:
        print(f"  {dim(sym)}...", end="", flush=True)
        df = _fetch_ohlcv(token, ikey, interval, days)
        if not df.empty and len(df) >= 60 and fb is not None:
            try:
                df = fb.build(df)
            except Exception:
                pass
        if not df.empty:
            hist_data[sym] = df
            print(f" {green('OK')} ({len(df)} bars)", end="")
        else:
            print(f" {yellow('no data')}", end="")
        print()

    if not hist_data:
        print(f"\n{R}No historical data loaded. Cannot generate signals.{E}")
        sys.exit(1)

    log_file = open(args.log_file, "a") if args.log_file else None
    session_start = datetime.now().strftime("%H:%M:%S")
    tick_no = 0
    _mis_squaredoff = False     # ensure squareoff fires only once per session
    _last_refresh: dict[str, float] = {}  # sym → last refresh epoch
    candle_period = _CANDLE_SECONDS.get(interval, 86400)

    # ── Market hours guard ────────────────────────────────────────────────────
    from utils.timeutils import is_market_session, next_market_open, minutes_to_market_open

    if not is_market_session():
        nxt = next_market_open()
        mins = minutes_to_market_open()
        print(f"\n{Y}Market is currently closed.{E}")
        print(f"  Next open: {nxt.strftime('%A %Y-%m-%d %H:%M IST')}  ({mins} min)")
        print(f"  Paper trade will run on stale historical prices until market opens.")
        if mins > 60:
            print(f"\n  {DIM}Sleeping until {nxt.strftime('%H:%M IST')} — press Ctrl+C to start immediately.{E}")
            try:
                sleep_until = mins * 60 - 120  # wake 2 min before open
                time.sleep(max(0, sleep_until))
            except KeyboardInterrupt:
                print(f"\n  {DIM}Starting immediately.{E}\n")

    print(f"\n{bold('Paper trading started.')}")
    print(f"  Symbols: {', '.join(syms)}")
    print(f"  Capital: ₹{args.capital:,.0f}  •  Max positions: {args.max_positions}")
    print(f"  Tick: {args.tick}s  •  Signal every {args.signal_every} ticks")
    print(f"  Press Ctrl+C to stop.\n")
    time.sleep(2)

    try:
        while True:
            tick_no += 1
            t0 = time.perf_counter()

            # Fetch live prices
            prices = _fetch_ltp(token, ikeys)

            # ── MIS squareoff at 3:14 PM IST ─────────────────────────────────
            from utils.timeutils import should_squareoff_mis
            if should_squareoff_mis() and not _mis_squaredoff:
                _mis_squaredoff = True
                mis_syms = list(portfolio.positions.keys())
                if mis_syms:
                    print(f"\n  {yellow('MIS SQUAREOFF 3:14 PM')} — closing {len(mis_syms)} position(s)")
                    for sym in mis_syms:
                        ikey = INSTRUMENTS.get(sym, "")
                        ltp = prices.get(ikey, 0.0) or portfolio.positions[sym].entry_price
                        msg = portfolio._close_position(sym, ltp, "mis_squareoff_3:14pm")
                        print(f"  {msg}")
                else:
                    print(f"  {dim('3:14 PM — no open MIS positions to square off.')}")

            # Update positions → check SL/TP
            close_events = portfolio.update_prices(prices)

            # Refresh intraday candles once per candle period (no-op for daily)
            if interval != "day":
                for sym, ikey in resolved:
                    if time.time() - _last_refresh.get(sym, 0) >= candle_period:
                        refreshed = _refresh_intraday(token, sym, ikey, interval,
                                                      hist_data.get(sym), fb)
                        if refreshed is not None and not refreshed.empty:
                            hist_data[sym] = refreshed
                        _last_refresh[sym] = time.time()

            # Generate signals on schedule
            signal_events: list[str] = []
            if engine is not None and tick_no % args.signal_every == 0:
                for sym, ikey in resolved:
                    df = hist_data.get(sym)
                    if df is None or df.empty:
                        continue
                    ltp = prices.get(ikey, 0.0)
                    if ltp and not df.empty:
                        import pandas as pd
                        last_ts = df.index[-1]
                        df.at[last_ts, "close"] = ltp

                    try:
                        signals = engine.generate_signals(sym, df)
                        best = engine.best_signal(signals)
                        if best and best.confidence >= 0.4:
                            msg = portfolio.on_signal(best)
                            if msg:
                                signal_events.append(msg)
                    except Exception:
                        pass

            all_events = close_events + signal_events
            next_signal_in = args.signal_every - (tick_no % args.signal_every)

            from utils.timeutils import minutes_to_market_close, is_market_session
            if is_market_session():
                mins_left = minutes_to_market_close()
                if 0 < mins_left <= 20:
                    all_events = [f"{Y}Market closes in {mins_left} min  (MIS squareoff at 3:14 PM){E}"] + all_events

            _render_dashboard(portfolio, prices, tick_no, next_signal_in,
                               all_events, session_start)

            if log_file and all_events:
                for entry in portfolio.signal_log[-len(all_events):]:
                    log_file.write(json.dumps(entry) + "\n")
                log_file.flush()

            _save_state(portfolio)

            elapsed = time.perf_counter() - t0
            sleep_sec = max(0.5, args.tick - elapsed)
            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        pass
    finally:
        _save_state(portfolio)
        if log_file:
            log_file.close()

    # Final summary
    print(f"\n{bold('Session ended.')}")
    print(f"  Capital:         ₹{portfolio.initial_capital:,.0f}")
    print(f"  Final value:     ₹{portfolio.total_value:,.0f}")
    print(f"  Total P&L:       {pnl_s(portfolio.total_pnl)}")
    print(f"  Realised P&L:    {pnl_s(portfolio.realised_pnl)}")
    print(f"  Unrealised P&L:  {pnl_s(portfolio.unrealised_pnl)}")
    print(f"  Closed trades:   {len(portfolio.closed_trades)}")
    print(f"  Win rate:        {portfolio.win_rate:.0f}%")
    print()


if __name__ == "__main__":
    main()
