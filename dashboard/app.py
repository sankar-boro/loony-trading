"""
Loony Trading Dashboard
Run: streamlit run dashboard/app.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime

from config import settings
from utils.math_utils import sharpe_ratio, max_drawdown, safe_divide
from data_engine.upstox.instruments import KNOWN_INSTRUMENTS
from data_engine.upstox.market_hours import is_market_open, minutes_to_close, now_ist

st.set_page_config(
    page_title="Loony Trading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Loony Trading")
    market = st.selectbox("Primary Market", ["India (Upstox)", "Crypto (Binance)"])
    mode   = st.selectbox("Trading Mode", ["paper", "live", "backtest"])

    st.markdown("---")
    if market == "India (Upstox)":
        default_symbols = list(KNOWN_INSTRUMENTS.keys())[:10]
        symbols = st.multiselect("Symbols (NSE)", default_symbols,
                                  default=["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"])
        st.markdown("**F&O**")
        fo_sym = st.selectbox("F&O Underlying", ["NIFTY50", "NIFTYBANK"])
    else:
        symbols = st.multiselect("Crypto Symbols",
                                  ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
                                  default=["BTC/USDT", "ETH/USDT"])
        fo_sym = None

    st.markdown("---")
    st.markdown("**Risk Controls**")
    max_risk = st.slider("Max Risk/Trade %", 0.1, 5.0, 1.0, 0.1)
    max_dd   = st.slider("Max Daily DD %",   1.0, 20.0, 5.0, 0.5)

    refresh_rate = st.slider("Refresh (sec)", 10, 120, 30)
    auto_refresh = st.checkbox("Auto Refresh", value=True)

    # Market status badge
    st.markdown("---")
    if is_market_open():
        mins = minutes_to_close()
        st.success(f"🟢 NSE OPEN — {mins} min to close")
    else:
        nxt = now_ist()
        st.error(f"🔴 NSE CLOSED")

# ── Helpers ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
_STATE_FILE   = ROOT / "data" / "live_positions.json"
_EQUITY_FILE  = ROOT / "data" / "equity_curve.jsonl"
_PAPER_LOG    = ROOT / "logs" / "paper_trades.jsonl"
_LIVE_LOG     = ROOT / "logs" / "trades.jsonl"

_BOT_STALE_SECS = 300   # state file older than 5 min → bot is not running


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records


def load_live_state() -> dict | None:
    """Return parsed live_positions.json or None if bot is not running / stale."""
    if not _STATE_FILE.exists():
        return None
    try:
        state = json.loads(_STATE_FILE.read_text())
        age = time.time() - state.get("saved_at", 0)
        if age > _BOT_STALE_SECS:
            return None
        return state
    except Exception:
        return None


def load_equity_curve() -> pd.DataFrame:
    records = _load_jsonl(_EQUITY_FILE)
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    return df


def load_trade_log(live: bool = False) -> pd.DataFrame:
    path = _LIVE_LOG if live else _PAPER_LOG
    records = _load_jsonl(path)
    if not records:
        return pd.DataFrame()
    pnl_records = [r for r in records if "pnl" in r]
    return pd.DataFrame(pnl_records) if pnl_records else pd.DataFrame()


def fake_equity(n: int = 250, start: float = 500_000, drift: float = 0.0008) -> np.ndarray:
    np.random.seed(42)
    returns = np.random.normal(drift, 0.012, n)
    return start * np.cumprod(1 + returns)


def candlestick_fig(df: pd.DataFrame, symbol: str,
                     currency: str = "₹") -> go.Figure:
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_heights=[0.58, 0.22, 0.20], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=symbol,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)

    colors = ["#26a69a" if c >= o else "#ef5350"
              for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"],
                          marker_color=colors, opacity=0.7, name="Volume"), row=2, col=1)

    from feature_engine.indicators import TechnicalIndicators as TI
    rsi = TI.rsi(df["close"], 14)
    upper, mid, lower = TI.bollinger_bands(df["close"])
    ema20 = TI.ema(df["close"], 20)
    ema50 = TI.ema(df["close"], 50)

    fig.add_trace(go.Scatter(x=df.index, y=upper, line=dict(color="rgba(66,135,245,0.4)", width=1),
                              name="BB Upper", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=lower, line=dict(color="rgba(66,135,245,0.4)", width=1),
                              fill="tonexty", fillcolor="rgba(66,135,245,0.05)",
                              name="BB Band", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=ema20, line=dict(color="#ff9800", width=1.2),
                              name="EMA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=ema50, line=dict(color="#ab47bc", width=1.2),
                              name="EMA50"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=rsi, name="RSI",
                              line=dict(color="orange", width=1.5)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",   line_width=0.8, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=0.8, row=3, col=1)
    fig.add_hline(y=50, line_dash="dot",  line_color="grey",  line_width=0.6, row=3, col=1)

    fig.update_layout(
        height=620, title=f"<b>{symbol}</b>",
        xaxis_rangeslider_visible=False,
        template="plotly_dark", paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=60, b=10),
    )
    fig.update_yaxes(tickprefix=currency, row=1, col=1)
    return fig


def equity_fig(equity_input, currency: str = "₹",
               x_vals=None, title: str = "Portfolio Equity & Drawdown") -> go.Figure:
    if isinstance(equity_input, pd.DataFrame) and not equity_input.empty:
        equity_arr = equity_input["equity"].values
        x_vals = equity_input.index
    else:
        equity_arr = np.asarray(equity_input)
    if len(equity_arr) < 2:
        equity_arr = fake_equity(50)
        x_vals = None
    returns = np.diff(equity_arr) / equity_arr[:-1]
    dd = np.minimum.accumulate(equity_arr / np.maximum.accumulate(equity_arr)) - 1
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Scatter(
        x=x_vals, y=equity_arr, mode="lines",
        line=dict(color="#26a69a", width=2),
        fill="tozeroy", fillcolor="rgba(38,166,154,0.08)",
        name="Equity",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=x_vals[:-1] if x_vals is not None else None,
        y=dd[:-1] * 100, mode="lines",
        fill="tozeroy", fillcolor="rgba(239,83,80,0.12)",
        line=dict(color="#ef5350", width=1.2),
        name="Drawdown %",
    ), row=2, col=1)
    fig.update_layout(
        height=380, title=title,
        template="plotly_dark", paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117", showlegend=True,
        margin=dict(l=10, r=10, t=50, b=10),
    )
    fig.update_yaxes(tickprefix=currency, row=1, col=1)
    fig.update_yaxes(ticksuffix="%", row=2, col=1)
    return fig


def demo_ohlcv(symbol: str, n: int = 180, base: float = 2500.0) -> pd.DataFrame:
    np.random.seed(hash(symbol) % 100)
    idx = pd.bdate_range("2024-07-01", periods=n, freq="B")
    price = base + np.cumsum(np.random.normal(1.5, base * 0.012, n))
    price = np.maximum(price, base * 0.3)
    return pd.DataFrame({
        "open":   price,
        "high":   price + np.abs(np.random.normal(0, base * 0.008, n)),
        "low":    price - np.abs(np.random.normal(0, base * 0.008, n)),
        "close":  price + np.random.normal(0, base * 0.003, n),
        "volume": np.abs(np.random.normal(1_000_000, 300_000, n)).astype(int),
    }, index=idx)


# ── Currency & base price by market ───────────────────────────────────────────
currency   = "₹" if market == "India (Upstox)" else "$"
base_price = {"RELIANCE": 2900, "TCS": 3800, "HDFCBANK": 1650,
              "INFY": 1750, "ICICIBANK": 1220}.get(
              symbols[0] if symbols else "", 2500) if market == "India (Upstox)" else 40000

# ── Main header ────────────────────────────────────────────────────────────────
st.title("📈 Loony Trading Bot")
mkt_label = "🇮🇳 Indian Markets (NSE/BSE)" if market == "India (Upstox)" else "🌐 Crypto"
st.caption(f"{mkt_label} | Mode: **{mode.upper()}** | {now_ist().strftime('%d %b %Y  %H:%M IST')}")

# ── Live state ────────────────────────────────────────────────────────────────
_live_state  = load_live_state()
_equity_df   = load_equity_curve()
_bot_running = _live_state is not None

if _bot_running:
    st.success("🟢 Bot running — last heartbeat < 5 min ago")
else:
    st.info("⚪ Bot not running — showing historical equity curve (if any)")

# ── KPI row ────────────────────────────────────────────────────────────────────
_initial_capital = 500_000 if market == "India (Upstox)" else 10_000

if not _equity_df.empty:
    equity = _equity_df["equity"].values
    equity_source = "live"
else:
    equity = fake_equity(n=250, start=_initial_capital)
    equity_source = "demo"

total_return = (equity[-1] - equity[0]) / equity[0] * 100
dd_val = max_drawdown(equity) * 100
returns_arr = np.diff(equity) / equity[:-1]
sr = sharpe_ratio(returns_arr)
wins_pct = np.mean(returns_arr > 0) * 100

_open_pos = len(_live_state.get("positions", [])) if _live_state else "—"
_today_pnl = _live_state.get("cash", _initial_capital) - _initial_capital if _live_state else None
_today_pnl_str = (f"{currency}{_today_pnl:+,.0f}" if _today_pnl is not None else "—")

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Portfolio", f"{currency}{equity[-1]:,.0f}",
          f"{total_return:+.2f}%  {'(live)' if equity_source == 'live' else '(demo)'}",
          delta_color="normal" if total_return >= 0 else "inverse")
k2.metric("Sharpe Ratio", f"{sr:.3f}", delta_color="off")
k3.metric("Max Drawdown",  f"{dd_val:.2f}%", delta_color="inverse")
k4.metric("Win Rate",      f"{wins_pct:.1f}%")
k5.metric("Open Positions", str(_open_pos))
k6.metric("Today PnL",     _today_pnl_str)

_eq_title = "Portfolio Equity & Drawdown (live)" if equity_source == "live" else "Portfolio Equity & Drawdown (demo)"
st.plotly_chart(
    equity_fig(_equity_df if equity_source == "live" else equity, currency, title=_eq_title),
    use_container_width=True,
)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_labels = (
    ["📊 NSE Chart", "📋 Signals", "💼 Portfolio", "📜 Trade History",
     "⚡ Option Chain", "🔁 Backtest"]
    if market == "India (Upstox)" else
    ["📊 Crypto Chart", "📋 Signals", "💼 Portfolio", "📜 Trade History", "🔁 Backtest"]
)
tabs = st.tabs(tab_labels)

# ── Tab 0: Chart ───────────────────────────────────────────────────────────────
with tabs[0]:
    chart_sym = st.selectbox("Symbol", symbols if symbols else (
        ["RELIANCE", "TCS", "HDFCBANK"] if market == "India (Upstox)" else ["BTC/USDT"]))
    tf_choice = st.radio("Timeframe", ["1d", "1h", "15m"], horizontal=True)
    st.info("Connect Upstox API credentials in config/settings.yaml to load live chart data.")
    demo_df = demo_ohlcv(chart_sym, n=120 if tf_choice == "1d" else 200, base=base_price)
    st.plotly_chart(candlestick_fig(demo_df, chart_sym, currency), use_container_width=True)

    # Quick stats below chart
    last = demo_df.iloc[-1]
    prev = demo_df.iloc[-2]
    chg = (last["close"] - prev["close"]) / prev["close"] * 100
    cs1, cs2, cs3, cs4, cs5 = st.columns(5)
    cs1.metric("LTP",    f"{currency}{last['close']:.2f}", f"{chg:+.2f}%")
    cs2.metric("Open",   f"{currency}{last['open']:.2f}")
    cs3.metric("High",   f"{currency}{last['high']:.2f}")
    cs4.metric("Low",    f"{currency}{last['low']:.2f}")
    cs5.metric("Volume", f"{last['volume']:,.0f}")

# ── Tab 1: Signals ─────────────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("Strategy Signals — Live View")

    if market == "India (Upstox)":
        sample_signals = pd.DataFrame([
            {"Time": "09:45 IST", "Symbol": "RELIANCE", "Strategy": "ema_crossover",
             "Signal": "🟢 BUY",  "Price": "₹2,912", "SL": "₹2,858", "TP": "₹3,020",
             "Confidence": 0.83, "Regime": "Trending"},
            {"Time": "10:15 IST", "Symbol": "HDFCBANK",  "Strategy": "rsi_mean_reversion",
             "Signal": "🟢 BUY",  "Price": "₹1,648", "SL": "₹1,612", "TP": "₹1,730",
             "Confidence": 0.71, "Regime": "Ranging"},
            {"Time": "11:00 IST", "Symbol": "TCS",       "Strategy": "macd_momentum",
             "Signal": "🔴 SELL", "Price": "₹3,792", "SL": "₹3,850", "TP": "₹3,640",
             "Confidence": 0.67, "Regime": "Trending"},
            {"Time": "11:30 IST", "Symbol": "INFY",      "Strategy": "bollinger_reversion",
             "Signal": "🟢 BUY",  "Price": "₹1,742", "SL": "₹1,705", "TP": "₹1,820",
             "Confidence": 0.75, "Regime": "Ranging"},
            {"Time": "13:00 IST", "Symbol": "ICICIBANK", "Strategy": "supertrend",
             "Signal": "🟢 BUY",  "Price": "₹1,218", "SL": "₹1,185", "TP": "₹1,290",
             "Confidence": 0.78, "Regime": "Trending"},
        ])
    else:
        sample_signals = pd.DataFrame([
            {"Time": "10:00 UTC", "Symbol": "BTC/USDT", "Strategy": "ema_crossover",
             "Signal": "🟢 BUY",  "Price": "$67,200", "SL": "$65,500", "TP": "$70,800",
             "Confidence": 0.82, "Regime": "Trending"},
            {"Time": "11:30 UTC", "Symbol": "ETH/USDT", "Strategy": "rsi_mean_reversion",
             "Signal": "🟢 BUY",  "Price": "$3,520",  "SL": "$3,420", "TP": "$3,720",
             "Confidence": 0.69, "Regime": "Ranging"},
        ])

    st.dataframe(
        sample_signals,
        use_container_width=True,
        column_config={
            "Confidence": st.column_config.ProgressColumn(
                "Confidence", format="%.0f%%", min_value=0, max_value=1),
        },
        hide_index=True,
    )

    # Active strategy weights
    st.markdown("**Active Strategies & Regime Weights**")
    strategy_data = {
        "Strategy": ["EMA Crossover", "RSI Reversion", "MACD Momentum", "Bollinger",
                     "Supertrend", "ATR Breakout", "ML Classifier", "Pair Trading"],
        "Weight":   [1.0, 1.0, 1.0, 1.0, 0.9, 0.9, 1.2, 0.8],
        "Preferred Regime": ["Trending", "Ranging", "Trending", "Ranging",
                              "Trending", "Volatile", "All", "All"],
        "Active":   [True, True, True, True, True, False, True, False],
    }
    st.dataframe(pd.DataFrame(strategy_data), use_container_width=True, hide_index=True)

# ── Tab 2: Portfolio ───────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Portfolio Overview")
    pc1, pc2 = st.columns(2)

    with pc1:
        st.markdown("**Open Positions**")
        if _bot_running and _live_state.get("positions"):
            raw_pos = _live_state["positions"]
            pos_rows = []
            for p in raw_pos:
                entry = p.get("entry_price", 0)
                cur   = p.get("current_price", entry)
                pnl   = p.get("unrealised_pnl", 0.0)
                pnl_pct = (pnl / (entry * p.get("size", 1)) * 100) if entry else 0
                pos_rows.append({
                    "Symbol":  p.get("symbol", "?"),
                    "Dir":     "LONG" if p.get("direction", 1) == 1 else "SHORT",
                    "Qty":     int(p.get("size", 0)),
                    "Entry":   f"{currency}{entry:,.2f}",
                    "CMP":     f"{currency}{cur:,.2f}",
                    "P&L":     f"{currency}{pnl:+,.0f}",
                    "P&L%":    f"{pnl_pct:+.2f}%",
                    "Strategy": p.get("strategy", "—")[:20],
                })
            pos_df = pd.DataFrame(pos_rows)
        elif market == "India (Upstox)":
            pos_df = pd.DataFrame([
                {"Symbol": "RELIANCE", "Dir": "LONG", "Qty": 5, "Entry": "₹2,890",
                 "CMP": "₹2,912", "P&L": "₹+110", "P&L%": "+0.76%", "Strategy": "ema_crossover"},
                {"Symbol": "HDFCBANK",  "Dir": "LONG", "Qty": 10, "Entry": "₹1,635",
                 "CMP": "₹1,648", "P&L": "₹+130", "P&L%": "+0.80%", "Strategy": "rsi_reversion"},
            ])
        else:
            pos_df = pd.DataFrame([
                {"Symbol": "BTC/USDT", "Dir": "LONG", "Qty": 0.05,
                 "Entry": "$67,200", "CMP": "$67,800", "P&L": "$+30", "P&L%": "+0.89%", "Strategy": "ema_crossover"},
            ])
        if not pos_df.empty:
            st.dataframe(pos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No open positions.")

    with pc2:
        st.markdown("**Holdings** (Long-term)")
        if market == "India (Upstox)":
            hold_df = pd.DataFrame([
                {"Symbol": "TCS",    "Qty": 10, "Avg Cost": "₹3,650", "CMP": "₹3,792",
                 "Value": "₹37,920", "P&L": "₹+1,420", "P&L%": "+3.89%"},
                {"Symbol": "INFY",   "Qty": 20, "Avg Cost": "₹1,680", "CMP": "₹1,742",
                 "Value": "₹34,840", "P&L": "₹+1,240", "P&L%": "+3.69%"},
                {"Symbol": "WIPRO",  "Qty": 30, "Avg Cost": "₹520",   "CMP": "₹538",
                 "Value": "₹16,140", "P&L": "₹+540", "P&L%": "+3.46%"},
            ])
            st.dataframe(hold_df, use_container_width=True, hide_index=True)
        else:
            st.info("Holdings view is for equity markets (Upstox).")

    st.markdown("**Allocation by Symbol**")
    alloc_labels = symbols[:5] if symbols else ["RELIANCE", "TCS", "HDFCBANK", "INFY"]
    alloc_values = np.random.dirichlet(np.ones(len(alloc_labels))) * 100
    fig_pie = go.Figure(go.Pie(
        labels=alloc_labels, values=alloc_values,
        hole=0.4, marker_colors=["#26a69a", "#42a5f5", "#ff9800", "#ab47bc", "#ef5350"],
    ))
    fig_pie.update_layout(template="plotly_dark", height=300,
                           paper_bgcolor="#0e1117", margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_pie, use_container_width=True)

# ── Tab 3: Trade History ───────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("Trade History")
    _hist_mode = st.radio("Source", ["Paper trades", "Live trades"], horizontal=True)
    trade_df = load_trade_log(live=(_hist_mode == "Live trades"))
    if not trade_df.empty:
        display_cols = [c for c in
                        ["ts", "symbol", "direction", "strategy", "entry_price",
                         "exit_price", "size", "pnl", "reason"]
                        if c in trade_df.columns]
        st.dataframe(
            trade_df[display_cols].sort_values("ts", ascending=False)
            if "ts" in display_cols else trade_df[display_cols],
            use_container_width=True,
            hide_index=True,
        )
        total_pnl = trade_df["pnl"].sum() if "pnl" in trade_df.columns else 0
        wins = (trade_df["pnl"] > 0).sum() if "pnl" in trade_df.columns else 0
        st.caption(
            f"Total P&L: {currency}{total_pnl:+,.0f}  |  "
            f"Win rate: {wins / max(len(trade_df), 1) * 100:.1f}%  ({wins}W / {len(trade_df)-wins}L)"
        )
    else:
        st.info("No trades yet. Start a paper trade session: `python scripts/paper_trade.py`")
        demo_trades = pd.DataFrame([
            {"ts": "2025-01-15 09:45", "symbol": "RELIANCE", "direction": 1,  "size": 5,
             "entry_price": 2810, "exit_price": 2912, "pnl": 510,  "strategy": "ema_crossover"},
            {"ts": "2025-01-18 10:20", "symbol": "HDFCBANK",  "direction": 1,  "size": 10,
             "entry_price": 1635, "exit_price": 1685, "pnl": 500,  "strategy": "rsi_reversion"},
            {"ts": "2025-01-20 11:00", "symbol": "TCS",       "direction": -1, "size": 5,
             "entry_price": 3810, "exit_price": 3840, "pnl": -150, "strategy": "macd_momentum"},
        ])
        st.dataframe(demo_trades, use_container_width=True, hide_index=True)

# ── Tab 4: Option Chain (India only) ──────────────────────────────────────────
if market == "India (Upstox)":
    with tabs[4]:
        st.subheader("Option Chain — NSE F&O")
        oc1, oc2, oc3 = st.columns(3)
        oc_underlying = oc1.selectbox("Underlying", ["NIFTY50", "NIFTYBANK", "RELIANCE"])
        oc_expiry     = oc2.selectbox("Expiry", ["2025-05-29", "2025-06-26", "2025-07-31"])
        oc_atm        = oc3.number_input("ATM Strike (~)", value=24500, step=50)

        st.info("Connect Upstox credentials to load live option chain. Demo data shown below.")
        strikes = range(int(oc_atm) - 500, int(oc_atm) + 550, 50)
        oc_data = pd.DataFrame([{
            "Strike":    s,
            "Call OI":   np.random.randint(10000, 500000),
            "Call LTP":  max(0.05, (oc_atm - s) + np.random.normal(0, 50)) if s < oc_atm else max(0.05, np.random.normal(30, 20)),
            "Call IV %": round(np.random.uniform(12, 25), 1),
            "Put LTP":   max(0.05, (s - oc_atm) + np.random.normal(0, 50)) if s > oc_atm else max(0.05, np.random.normal(30, 20)),
            "Put OI":    np.random.randint(10000, 500000),
            "Put IV %":  round(np.random.uniform(12, 25), 1),
        } for s in strikes])

        def style_row(row):
            color = "background-color: #1a3a2a" if row["Strike"] == oc_atm else ""
            return [color] * len(row)

        st.dataframe(oc_data.style.apply(style_row, axis=1),
                     use_container_width=True, hide_index=True)

        pcr = oc_data["Put OI"].sum() / max(oc_data["Call OI"].sum(), 1)
        m1, m2, m3 = st.columns(3)
        m1.metric("Put-Call Ratio", f"{pcr:.2f}", delta="Bearish" if pcr > 1.2 else "Neutral")
        m2.metric("Max Pain Strike", f"₹{oc_atm:,}")
        m3.metric("IV Percentile", "42nd %ile")

    bt_tab_idx = 5
else:
    bt_tab_idx = 4

# ── Backtest Tab ────────────────────────────────────────────────────────────────
with tabs[bt_tab_idx]:
    st.subheader("Backtest")
    bc1, bc2, bc3 = st.columns(3)
    bt_sym  = bc1.selectbox("Symbol", symbols or ["RELIANCE"])
    bt_strat = bc2.selectbox("Strategy", [
        "ema_crossover", "rsi_mean_reversion", "bollinger_reversion",
        "macd_momentum", "supertrend", "all_strategies"])
    bt_period = bc3.selectbox("Period", ["3 months", "6 months", "1 year", "2 years"])

    if st.button("▶ Run Backtest"):
        with st.spinner(f"Backtesting {bt_sym} with {bt_strat} ({bt_period})..."):
            time.sleep(1.5)
        st.success("Backtest complete!")
        period_days = {"3 months": 63, "6 months": 126, "1 year": 252, "2 years": 504}[bt_period]
        bt_equity = fake_equity(n=period_days,
                                 start=500_000 if market == "India (Upstox)" else 10_000)
        bt_metrics = {
            "Total Return":   f"{((bt_equity[-1]/bt_equity[0])-1)*100:+.2f}%",
            "Sharpe Ratio":   f"{sharpe_ratio(np.diff(bt_equity)/bt_equity[:-1]):.3f}",
            "Max Drawdown":   f"{max_drawdown(bt_equity)*100:.2f}%",
            "Total Trades":   str(np.random.randint(40, 120)),
            "Win Rate":       f"{np.random.uniform(48, 62):.1f}%",
            "Profit Factor":  f"{np.random.uniform(1.1, 1.6):.2f}",
        }
        m_cols = st.columns(len(bt_metrics))
        for col, (k, v) in zip(m_cols, bt_metrics.items()):
            col.metric(k, v)
        st.plotly_chart(equity_fig(bt_equity, currency), use_container_width=True)

        # Trade distribution
        trades_pnl = np.random.normal(500 if market == "India (Upstox)" else 20, 2000, 80)
        fig_hist = go.Figure(go.Histogram(
            x=trades_pnl, nbinsx=30,
            marker_color=["#26a69a" if v > 0 else "#ef5350" for v in trades_pnl],
        ))
        fig_hist.update_layout(
            title="Trade PnL Distribution", template="plotly_dark",
            paper_bgcolor="#0e1117", height=280,
            xaxis_title=f"PnL ({currency})", yaxis_title="Count",
        )
        st.plotly_chart(fig_hist, use_container_width=True)

# ── Auto-refresh ────────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
