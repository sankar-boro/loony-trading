"""
Loony Trading Dashboard
Run: streamlit run dashboard/app.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config.loader import Settings
from utils.math_utils import sharpe_ratio, max_drawdown
from data_engine.upstox.market_hours import (
    is_market_open, minutes_to_close, now_ist, next_market_open,
)

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Loony Trading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT = Path(__file__).resolve().parent.parent

_STATE_FILE   = ROOT / "data" / "live_positions.json"
_EQUITY_FILE  = ROOT / "data" / "equity_curve.jsonl"
_PAPER_LOG    = ROOT / "logs" / "paper_trades.jsonl"
_LIVE_LOG     = ROOT / "logs" / "trades.jsonl"
_DAILY_FILE   = ROOT / "data" / "daily_pnl.jsonl"
_TOKEN_FILE   = ROOT / "data" / "upstox_token.json"

_BOT_STALE_SECS = 300

PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="#0e1117",
    plot_bgcolor="#0e1117",
    margin=dict(l=10, r=10, t=50, b=10),
    font=dict(family="Inter, sans-serif", size=12),
)


# ── Data loading (cached) ──────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def load_live_state() -> dict | None:
    if not _STATE_FILE.exists():
        return None
    try:
        state = json.loads(_STATE_FILE.read_text())
        if time.time() - state.get("saved_at", 0) > _BOT_STALE_SECS:
            return None
        return state
    except Exception:
        return None


@st.cache_data(ttl=30)
def load_equity_curve() -> pd.DataFrame:
    if not _EQUITY_FILE.exists():
        return pd.DataFrame()
    records = []
    try:
        for line in _EQUITY_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return pd.DataFrame()
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["ts"] = pd.to_datetime(df["ts"])
    return df.set_index("ts").sort_index()


@st.cache_data(ttl=30)
def load_trade_log(live: bool = False) -> pd.DataFrame:
    path = _LIVE_LOG if live else _PAPER_LOG
    if not path.exists():
        return pd.DataFrame()
    records = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    if "pnl" in r:
                        records.append(r)
                except Exception:
                    pass
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(records) if records else pd.DataFrame()


@st.cache_data(ttl=60)
def load_daily_pnl() -> pd.DataFrame:
    if not _DAILY_FILE.exists():
        return pd.DataFrame()
    records = []
    try:
        for line in _DAILY_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return pd.DataFrame()
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


@st.cache_data(ttl=3600)
def load_config_weights() -> dict:
    try:
        s = Settings()
        return {
            "weights":  s.get("strategies.weights") or {},
            "enabled":  s.get("strategies.enabled") or [],
            "capital":  s.get("portfolio.initial_capital") or 500_000,
        }
    except Exception:
        return {"weights": {}, "enabled": [], "capital": 500_000}


@st.cache_data(ttl=10)
def get_upstox_token() -> tuple[str, float]:
    """Returns (token, age_hours). token="" if unavailable."""
    env_token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if _TOKEN_FILE.exists():
        try:
            d = json.loads(_TOKEN_FILE.read_text())
            file_token = d.get("access_token", "")
            age_h = (time.time() - d.get("obtained_at", 0)) / 3600
            token = env_token or file_token
            return token, age_h
        except Exception:
            pass
    return env_token, -1.0


@st.cache_data(ttl=300)
def fetch_ohlcv(instrument_key: str, interval: str, days: int) -> pd.DataFrame:
    token, age = get_upstox_token()
    if not token or age > 23:
        return pd.DataFrame()
    import requests
    key = instrument_key.replace("|", "%7C").replace(" ", "%20")
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()

    if interval == "day":
        url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
    else:
        url = f"https://api.upstox.com/v2/historical-candle/intraday/{key}/{interval}"

    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
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
        df[col] = pd.to_numeric(df[col])
    return df


@st.cache_data(ttl=60)
def fetch_ltp(instrument_keys: tuple[str]) -> dict[str, float]:
    token, age = get_upstox_token()
    if not token or age > 23:
        return {}
    import requests
    keys = ",".join(k.replace("|", "%7C").replace(" ", "%20") for k in instrument_keys)
    try:
        r = requests.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("data", {})
        return {k.replace(":", "|"): float(v.get("last_price", 0) or 0)
                for k, v in data.items()}
    except Exception:
        return {}


# ── Instrument map ─────────────────────────────────────────────────────────────

IKEYS = {
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
    "NIFTY50":    "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
}

TF_INTERVAL = {
    "1d":  ("day",       365),
    "1h":  ("60minute",  7),
    "15m": ("30minute",  2),
}


# ── Plot helpers ───────────────────────────────────────────────────────────────

def candlestick_fig(df: pd.DataFrame, symbol: str) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20], vertical_spacing=0.02,
        subplot_titles=("", "Volume", "RSI"),
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=symbol,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350",
    ), row=1, col=1)

    vol_colors = ["#26a69a" if c >= o else "#ef5350"
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df.index, y=df["volume"],
        marker_color=vol_colors, opacity=0.6, name="Volume", showlegend=False,
    ), row=2, col=1)

    try:
        from feature_engine.indicators import TechnicalIndicators as TI
        rsi   = TI.rsi(df["close"], 14)
        upper, _, lower = TI.bollinger_bands(df["close"])
        ema20 = TI.ema(df["close"], 20)
        ema50 = TI.ema(df["close"], 50)

        fig.add_trace(go.Scatter(x=df.index, y=upper,
            line=dict(color="rgba(66,135,245,0.35)", width=1),
            name="BB Upper", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=lower,
            line=dict(color="rgba(66,135,245,0.35)", width=1),
            fill="tonexty", fillcolor="rgba(66,135,245,0.04)",
            name="BB Band", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=ema20,
            line=dict(color="#ff9800", width=1.3), name="EMA 20"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=ema50,
            line=dict(color="#ab47bc", width=1.3), name="EMA 50"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=rsi,
            line=dict(color="#ffa726", width=1.5), name="RSI", showlegend=False), row=3, col=1)
        for y, clr in [(70, "#ef5350"), (30, "#26a69a"), (50, "#555")]:
            fig.add_hline(y=y, line_dash="dash", line_color=clr, line_width=0.8, row=3, col=1)
    except Exception:
        pass

    fig.update_layout(
        height=640, title=f"<b>{symbol}</b>",
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        **PLOTLY_LAYOUT,
    )
    fig.update_yaxes(tickprefix="₹", row=1, col=1)
    return fig


def equity_curve_fig(df: pd.DataFrame, initial_capital: float,
                     title: str = "Equity Curve") -> go.Figure:
    if df.empty or len(df) < 2:
        return go.Figure()

    eq  = df["equity"].values
    ts  = df.index
    dd  = np.minimum.accumulate(eq / np.maximum.accumulate(eq)) - 1

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.70, 0.30], vertical_spacing=0.04)

    fig.add_hline(y=initial_capital, line_dash="dot",
                  line_color="rgba(255,255,255,0.2)", row=1, col=1)

    color = "#26a69a" if eq[-1] >= initial_capital else "#ef5350"
    fig.add_trace(go.Scatter(
        x=ts, y=eq, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=f"rgba(38,166,154,0.07)" if color == "#26a69a" else "rgba(239,83,80,0.07)",
        name="Equity",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=ts, y=dd * 100, mode="lines",
        fill="tozeroy", fillcolor="rgba(239,83,80,0.10)",
        line=dict(color="#ef5350", width=1.2),
        name="Drawdown %",
    ), row=2, col=1)

    fig.update_layout(height=400, title=title, showlegend=False, **PLOTLY_LAYOUT)
    fig.update_yaxes(tickprefix="₹", row=1, col=1)
    fig.update_yaxes(ticksuffix="%", row=2, col=1)
    return fig


def pnl_bar_fig(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["realised"]]
    fig = go.Figure(go.Bar(
        x=df["date"], y=df["realised"],
        marker_color=colors, name="Daily P&L",
    ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_width=1)
    fig.update_layout(height=280, title="Daily Realised P&L",
                      xaxis_title="Date", yaxis_tickprefix="₹",
                      **PLOTLY_LAYOUT)
    return fig


def trade_dist_fig(trades: pd.DataFrame) -> go.Figure:
    if trades.empty or "pnl" not in trades.columns:
        return go.Figure()
    pnl = trades["pnl"].dropna().values
    colors = ["#26a69a" if v >= 0 else "#ef5350" for v in pnl]
    fig = go.Figure(go.Histogram(
        x=pnl, nbinsx=30,
        marker_color="#26a69a", opacity=0.8, name="P&L",
    ))
    fig.add_vline(x=0, line_color="rgba(255,255,255,0.4)", line_width=1)
    fig.update_layout(height=260, title="Trade P&L Distribution",
                      xaxis_tickprefix="₹", **PLOTLY_LAYOUT)
    return fig


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📈 Loony Trading")

    # Market status
    if is_market_open():
        mins = minutes_to_close()
        st.success(f"🟢 NSE OPEN  •  {mins} min left")
    else:
        nxt = next_market_open()
        st.error(f"🔴 NSE CLOSED")
        st.caption(f"Next open: **{nxt.strftime('%a %d %b • %H:%M IST')}**")

    # Token status
    token, token_age = get_upstox_token()
    if not token:
        st.warning("⚠️ No Upstox token — charts will be empty")
    elif token_age > 20:
        st.warning(f"⚠️ Token is {token_age:.0f}h old — expires soon")
    else:
        st.success(f"🔑 Token valid  ({token_age:.0f}h old)")

    st.markdown("---")

    # Bot status
    _live_state = load_live_state()
    _bot_running = _live_state is not None
    if _bot_running:
        n_pos = len(_live_state.get("positions", []))
        st.success(f"🤖 Bot running  •  {n_pos} open position(s)")
    else:
        st.info("⚪ Bot not running")
        st.caption("Start: `python scripts/paper_trade.py`")

    st.markdown("---")

    symbols = st.multiselect(
        "Watchlist",
        list(IKEYS.keys()),
        default=["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "NIFTY50"],
    )

    st.markdown("---")
    refresh_rate = st.slider("Auto-refresh (sec)", 15, 120, 30)
    auto_refresh  = st.checkbox("Auto refresh", value=True)
    st.caption(f"Last updated: {now_ist().strftime('%H:%M:%S IST')}")


# ── Load shared data ───────────────────────────────────────────────────────────

_equity_df     = load_equity_curve()
_cfg           = load_config_weights()
_initial_cap   = _cfg["capital"]

# ── Header KPIs ───────────────────────────────────────────────────────────────

st.markdown(f"### 📈 Loony Trading  <span style='font-size:0.8rem;color:#888'>{now_ist().strftime('%d %b %Y  %H:%M IST')}</span>", unsafe_allow_html=True)

# Compute real KPIs
if not _equity_df.empty:
    eq_arr  = _equity_df["equity"].values
    _eq_src = "live"
else:
    eq_arr  = np.array([_initial_cap])
    _eq_src = "no data"

_total_ret = (eq_arr[-1] - eq_arr[0]) / eq_arr[0] * 100 if len(eq_arr) > 1 else 0.0
_dd_val    = max_drawdown(eq_arr) * 100 if len(eq_arr) > 1 else 0.0

# Win rate and today PnL from actual trades
_trade_df  = load_trade_log(live=False)
_n_trades  = len(_trade_df)
_wins      = int((_trade_df["pnl"] > 0).sum()) if not _trade_df.empty else 0
_win_rate  = _wins / _n_trades * 100 if _n_trades > 0 else 0.0

_open_pos  = len(_live_state.get("positions", [])) if _live_state else 0
if _live_state:
    _total_val = _live_state.get("cash", _initial_cap) + sum(
        p.get("unrealised_pnl", 0) + p.get("entry_price", 0) * abs(p.get("size", 0))
        for p in _live_state.get("positions", [])
    )
    _today_pnl = _total_val - _initial_cap
else:
    _today_pnl = None

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Portfolio",
          f"₹{eq_arr[-1]:,.0f}" if _eq_src == "live" else "—",
          f"{_total_ret:+.2f}%" if _eq_src == "live" else "no data")
k2.metric("Today P&L",
          f"₹{_today_pnl:+,.0f}" if _today_pnl is not None else "—",
          delta_color="normal" if (_today_pnl or 0) >= 0 else "inverse")
k3.metric("Max Drawdown", f"{_dd_val:.2f}%" if _eq_src == "live" else "—")
k4.metric("Win Rate",
          f"{_win_rate:.1f}%" if _n_trades > 0 else "—",
          f"{_wins}W / {_n_trades - _wins}L" if _n_trades > 0 else "no trades")
k5.metric("Open Positions", str(_open_pos))
k6.metric("Total Trades", str(_n_trades) if _n_trades > 0 else "—")

if not _equity_df.empty:
    st.plotly_chart(
        equity_curve_fig(_equity_df, _initial_cap, "Portfolio Equity"),
        use_container_width=True,
    )
else:
    st.info("No equity curve data yet — start a paper trade session to populate this.")

# ── Tabs ───────────────────────────────────────────────────────────────────────

tab_chart, tab_positions, tab_trades, tab_daily, tab_strategy, tab_backtest = st.tabs([
    "📊 Chart",
    "💼 Positions",
    "📜 Trades",
    "📅 Daily P&L",
    "🎯 Strategies",
    "🔁 Backtest",
])


# ── Tab: Chart ─────────────────────────────────────────────────────────────────

with tab_chart:
    c1, c2 = st.columns([2, 1])
    chart_sym = c1.selectbox(
        "Symbol",
        [s for s in symbols if s in IKEYS] or list(IKEYS.keys())[:5],
        key="chart_sym",
    )
    tf_choice = c2.radio("Timeframe", ["1d", "1h", "15m"], horizontal=True, key="tf")

    ikey     = IKEYS.get(chart_sym, "")
    interval, days = TF_INTERVAL[tf_choice]

    with st.spinner(f"Loading {chart_sym} {tf_choice} data…"):
        df_chart = fetch_ohlcv(ikey, interval, days) if ikey else pd.DataFrame()

    if df_chart.empty:
        if not token:
            st.warning("No Upstox token — run `python scripts/upstox_login.py` first.")
        elif not is_market_open() and interval != "day":
            st.info(f"Intraday data only available during market hours.  "
                    f"Next open: {next_market_open().strftime('%a %d %b %H:%M IST')}")
        else:
            st.warning(f"No data returned for {chart_sym} ({tf_choice}).")
    else:
        st.plotly_chart(candlestick_fig(df_chart, chart_sym), use_container_width=True)

        last = df_chart.iloc[-1]
        prev = df_chart.iloc[-2] if len(df_chart) > 1 else last
        chg  = (last["close"] - prev["close"]) / prev["close"] * 100

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("LTP",    f"₹{last['close']:,.2f}", f"{chg:+.2f}%",
                  delta_color="normal" if chg >= 0 else "inverse")
        m2.metric("Open",   f"₹{last['open']:,.2f}")
        m3.metric("High",   f"₹{last['high']:,.2f}")
        m4.metric("Low",    f"₹{last['low']:,.2f}")
        m5.metric("Volume", f"{last['volume']:,.0f}")


# ── Tab: Positions ─────────────────────────────────────────────────────────────

with tab_positions:
    col_pos, col_sig = st.columns([1, 1])

    with col_pos:
        st.markdown("#### Open Positions")
        if _live_state and _live_state.get("positions"):
            rows = []
            for p in _live_state["positions"]:
                entry   = p.get("entry_price", 0)
                cur     = p.get("current_price", entry)
                pnl     = p.get("unrealised_pnl", 0.0)
                pnl_pct = pnl / (entry * abs(p.get("size", 1))) * 100 if entry else 0
                rows.append({
                    "Symbol":   p.get("symbol", "?"),
                    "Side":     "LONG" if p.get("direction", 1) == 1 else "SHORT",
                    "Qty":      int(p.get("size", 0)),
                    "Entry ₹":  round(entry, 2),
                    "CMP ₹":    round(cur, 2),
                    "P&L ₹":    round(pnl, 2),
                    "P&L %":    round(pnl_pct, 2),
                    "SL ₹":     round(p.get("stop_loss", 0), 2),
                    "TP ₹":     round(p.get("take_profit", 0), 2),
                    "Strategy": p.get("strategy", "—"),
                })
            pos_df = pd.DataFrame(rows)
            st.dataframe(
                pos_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "P&L ₹": st.column_config.NumberColumn("P&L ₹", format="%.0f"),
                    "P&L %": st.column_config.NumberColumn("P&L %", format="%.2f%%"),
                },
            )
            total_unreal = sum(p.get("unrealised_pnl", 0) for p in _live_state["positions"])
            st.caption(f"Total unrealised: **₹{total_unreal:+,.0f}**")
        elif _bot_running:
            st.info("No open positions right now.")
        else:
            st.info("Bot not running — no position data available.")

    with col_sig:
        st.markdown("#### Recent Signals")
        sig_log = []
        if _live_state:
            sig_log = _live_state.get("signal_log", [])[-20:]
        if sig_log:
            sig_df = pd.DataFrame(sig_log[::-1])
            display = [c for c in ["time", "type", "symbol", "strategy",
                                    "price", "size", "pnl", "confidence"]
                       if c in sig_df.columns]
            st.dataframe(sig_df[display], use_container_width=True, hide_index=True)
        else:
            st.info("No signals logged yet.")

    # Live LTP ticker for watchlist
    st.markdown("#### Watchlist LTPs")
    watch_keys = tuple(IKEYS[s] for s in symbols if s in IKEYS)
    if watch_keys and token:
        with st.spinner("Fetching LTPs…"):
            ltps = fetch_ltp(watch_keys)
        if ltps:
            ltp_rows = []
            for sym in symbols:
                ikey = IKEYS.get(sym, "")
                ltp = ltps.get(ikey, 0)
                if ltp:
                    ltp_rows.append({"Symbol": sym, "LTP ₹": ltp})
            if ltp_rows:
                ltp_df = pd.DataFrame(ltp_rows)
                cols = st.columns(min(len(ltp_rows), 6))
                for col, row in zip(cols, ltp_rows):
                    col.metric(row["Symbol"], f"₹{row['LTP ₹']:,.2f}")
    else:
        st.caption("Token required for live LTPs.")


# ── Tab: Trades ────────────────────────────────────────────────────────────────

with tab_trades:
    src_col, _ = st.columns([1, 3])
    source = src_col.radio("Source", ["Paper", "Live"], horizontal=True, key="trade_src")
    trades = load_trade_log(live=(source == "Live"))

    if not trades.empty:
        display_cols = [c for c in
                        ["ts", "symbol", "strategy", "direction",
                         "entry_price", "exit_price", "size", "pnl", "reason"]
                        if c in trades.columns]
        show = trades[display_cols].copy()
        if "ts" in show.columns:
            show = show.sort_values("ts", ascending=False)
        if "direction" in show.columns:
            show["direction"] = show["direction"].map({1: "LONG", -1: "SHORT"}).fillna(show["direction"])
        if "pnl" in show.columns:
            show["pnl"] = show["pnl"].round(2)

        st.dataframe(
            show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "pnl": st.column_config.NumberColumn("P&L ₹", format="%.2f"),
                "entry_price": st.column_config.NumberColumn("Entry ₹", format="%.2f"),
                "exit_price":  st.column_config.NumberColumn("Exit ₹",  format="%.2f"),
            },
        )

        # Summary strip
        total_pnl   = trades["pnl"].sum() if "pnl" in trades.columns else 0
        wins        = int((trades["pnl"] > 0).sum()) if "pnl" in trades.columns else 0
        losses      = len(trades) - wins
        avg_win     = trades.loc[trades["pnl"] > 0, "pnl"].mean() if wins else 0
        avg_loss    = trades.loc[trades["pnl"] <= 0, "pnl"].mean() if losses else 0
        expectancy  = (wins / max(len(trades), 1)) * avg_win + (losses / max(len(trades), 1)) * avg_loss

        sm1, sm2, sm3, sm4, sm5 = st.columns(5)
        sm1.metric("Total P&L",  f"₹{total_pnl:+,.0f}")
        sm2.metric("Win Rate",   f"{wins / max(len(trades), 1) * 100:.1f}%",
                   f"{wins}W / {losses}L")
        sm3.metric("Avg Win",    f"₹{avg_win:+,.0f}")
        sm4.metric("Avg Loss",   f"₹{avg_loss:+,.0f}")
        sm5.metric("Expectancy", f"₹{expectancy:+,.0f}")

        st.plotly_chart(trade_dist_fig(trades), use_container_width=True)

    else:
        st.info(f"No {source.lower()} trades yet.")
        st.caption("Start paper trading: `python scripts/paper_trade.py`")


# ── Tab: Daily P&L ────────────────────────────────────────────────────────────

with tab_daily:
    daily_df = load_daily_pnl()

    if daily_df.empty:
        st.info("No daily P&L data yet — data populates after the first trading session ends at 3:35 PM IST.")
    else:
        # Summary KPIs
        total_realised  = daily_df["realised"].sum()
        avg_daily       = daily_df["realised"].mean()
        best_idx        = daily_df["realised"].idxmax()
        worst_idx       = daily_df["realised"].idxmin()
        best_day        = daily_df.loc[best_idx]
        worst_day       = daily_df.loc[worst_idx]
        total_trades    = daily_df["trades"].sum() if "trades" in daily_df.columns else 0
        total_wins      = daily_df["wins"].sum() if "wins" in daily_df.columns else 0
        overall_wr      = total_wins / max(total_trades, 1) * 100

        # Annualised Sharpe
        daily_pnls   = daily_df["realised"].values
        daily_rets   = daily_pnls / _initial_cap
        sharpe_ann   = (daily_rets.mean() / (daily_rets.std() + 1e-9)) * (252 ** 0.5) if len(daily_rets) > 1 else 0

        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Total Realised",  f"₹{total_realised:+,.0f}")
        d2.metric("Avg Daily P&L",   f"₹{avg_daily:+,.0f}")
        d3.metric("Win Rate",        f"{overall_wr:.1f}%")
        d4.metric("Sharpe (ann.)",   f"{sharpe_ann:.2f}")
        d5.metric("Trading Days",    str(len(daily_df)))

        st.plotly_chart(pnl_bar_fig(daily_df), use_container_width=True)

        # Day-by-day table
        st.markdown("#### Day-by-Day Breakdown")
        show_daily = daily_df.copy()
        show_daily["date"] = show_daily["date"].dt.strftime("%Y-%m-%d")
        if "win_rate" in show_daily.columns:
            show_daily["win_rate"] = show_daily["win_rate"].round(1)
        display_d = [c for c in ["date", "realised", "trades", "wins", "losses",
                                   "win_rate", "max_drawdown_pct", "top_symbol"]
                     if c in show_daily.columns]
        st.dataframe(
            show_daily[display_d].sort_values("date", ascending=False),
            use_container_width=True, hide_index=True,
            column_config={
                "realised": st.column_config.NumberColumn("Realised ₹", format="%.0f"),
                "win_rate": st.column_config.NumberColumn("Win %", format="%.1f"),
                "max_drawdown_pct": st.column_config.NumberColumn("Max DD %", format="%.2f"),
            },
        )

        be1, be2 = st.columns(2)
        be1.metric("Best Day",  f"{best_day['date'].strftime('%d %b') if hasattr(best_day['date'], 'strftime') else best_day['date']}  ₹{best_day['realised']:+,.0f}")
        be2.metric("Worst Day", f"{worst_day['date'].strftime('%d %b') if hasattr(worst_day['date'], 'strftime') else worst_day['date']}  ₹{worst_day['realised']:+,.0f}")


# ── Tab: Strategy Performance ─────────────────────────────────────────────────

with tab_strategy:
    # Strategy weights from settings.yaml
    weights  = _cfg["weights"]
    enabled  = set(_cfg["enabled"])

    st.markdown("#### Strategy Weights  (from `config/settings.yaml`)")
    st.caption("Run `python scripts/tune_weights.py` to auto-tune weights from backtest Sharpe.")

    if weights:
        w_rows = []
        for name, w in sorted(weights.items(), key=lambda x: -x[1]):
            w_rows.append({
                "Strategy": name,
                "Weight":   w,
                "Enabled":  name in enabled,
            })
        w_df = pd.DataFrame(w_rows)
        st.dataframe(
            w_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Weight": st.column_config.ProgressColumn(
                    "Weight", format="%.2f", min_value=0, max_value=2),
                "Enabled": st.column_config.CheckboxColumn("Enabled"),
            },
        )
    else:
        st.info("No weights found in settings.yaml.")

    # Strategy P&L breakdown from trades
    if not _trade_df.empty and "strategy" in _trade_df.columns and "pnl" in _trade_df.columns:
        st.markdown("#### Per-Strategy Performance  (paper trades)")
        grp = (
            _trade_df.groupby("strategy")["pnl"]
            .agg(trades="count", total_pnl="sum", avg_pnl="mean",
                 wins=lambda x: (x > 0).sum())
            .reset_index()
        )
        grp["win_rate"] = grp["wins"] / grp["trades"] * 100
        grp = grp.sort_values("total_pnl", ascending=False)

        fig_strat = go.Figure(go.Bar(
            x=grp["strategy"], y=grp["total_pnl"],
            marker_color=["#26a69a" if v >= 0 else "#ef5350" for v in grp["total_pnl"]],
            text=grp["total_pnl"].apply(lambda v: f"₹{v:+,.0f}"),
            textposition="outside",
        ))
        fig_strat.update_layout(height=320, title="Total P&L by Strategy",
                                 yaxis_tickprefix="₹", **PLOTLY_LAYOUT)
        st.plotly_chart(fig_strat, use_container_width=True)

        st.dataframe(
            grp[["strategy", "trades", "wins", "win_rate", "total_pnl", "avg_pnl"]].rename(
                columns={"total_pnl": "Total P&L ₹", "avg_pnl": "Avg P&L ₹",
                         "win_rate": "Win %"}),
            use_container_width=True, hide_index=True,
            column_config={
                "Total P&L ₹": st.column_config.NumberColumn("Total P&L ₹", format="%.0f"),
                "Avg P&L ₹":   st.column_config.NumberColumn("Avg P&L ₹",   format="%.0f"),
                "Win %":        st.column_config.NumberColumn("Win %",        format="%.1f"),
            },
        )
    else:
        st.info("No trade history yet — strategy P&L breakdown will appear after trading.")


# ── Tab: Backtest ──────────────────────────────────────────────────────────────

with tab_backtest:
    st.markdown("#### Backtest")

    bc1, bc2, bc3, bc4 = st.columns(4)
    bt_sym    = bc1.selectbox("Symbol", list(IKEYS.keys()), key="bt_sym")
    bt_strat  = bc2.selectbox("Strategy", _cfg["enabled"] or ["ema_crossover"], key="bt_strat")
    bt_period = bc3.selectbox("Period", ["3 months", "6 months", "1 year"], key="bt_period")
    bt_cap    = bc4.number_input("Capital ₹", value=int(_initial_cap),
                                  step=50_000, min_value=10_000, key="bt_cap")

    if st.button("▶ Run Backtest", type="primary"):
        period_days = {"3 months": 90, "6 months": 180, "1 year": 365}[bt_period]
        ikey_bt = IKEYS.get(bt_sym, "")
        if not ikey_bt:
            st.error(f"Unknown instrument key for {bt_sym}")
        elif not token:
            st.error("No Upstox token — cannot fetch historical data for backtest.")
        else:
            with st.spinner(f"Fetching {bt_sym} data and running backtest…"):
                df_bt = fetch_ohlcv(ikey_bt, "day", period_days)

            if df_bt.empty:
                st.error(f"Could not fetch {period_days} days of data for {bt_sym}.")
            else:
                with st.spinner("Running backtest…"):
                    try:
                        from feature_engine.feature_builder import FeatureBuilder
                        from backtester.backtester import Backtester
                        from config.loader import Settings

                        cfg_obj = Settings()
                        bt_cfg  = cfg_obj.as_dict()
                        bt_cfg.setdefault("data", {})["warmup_bars"] = 50

                        fb = FeatureBuilder()
                        try:
                            df_bt = fb.build(df_bt)
                        except Exception:
                            pass

                        # Import the specific strategy class
                        _STRAT_MAP = {
                            "ema_crossover":       ("strategies.trend",           "EmaCrossoverStrategy"),
                            "rsi_mean_reversion":  ("strategies.mean_reversion",  "RsiReversionStrategy"),
                            "bollinger_reversion": ("strategies.mean_reversion",  "BollingerReversionStrategy"),
                            "macd_momentum":       ("strategies.momentum",        "MacdMomentumStrategy"),
                            "breakout_atr":        ("strategies.breakout",        "AtrBreakoutStrategy"),
                            "supertrend":          ("strategies.trend",           "SupertrendStrategy"),
                            "ml_classifier":       ("strategies.ml_based",        "MLClassifierStrategy"),
                        }
                        strat_obj = None
                        if bt_strat in _STRAT_MAP:
                            mod_name, cls_name = _STRAT_MAP[bt_strat]
                            import importlib
                            mod = importlib.import_module(mod_name)
                            cls = getattr(mod, cls_name)
                            strat_obj = cls(bt_cfg)

                        bt = Backtester(bt_cfg, initial_capital=float(bt_cap), product="CNC")
                        result = bt.run(df_bt, bt_sym, strategy=strat_obj)
                        m = result.metrics

                        st.success("Backtest complete!")

                        r1, r2, r3, r4, r5, r6 = st.columns(6)
                        r1.metric("Total Return",  f"{m.get('total_return_pct', 0):+.2f}%")
                        r2.metric("Sharpe",        f"{m.get('sharpe', 0):.3f}")
                        r3.metric("Max Drawdown",  f"{m.get('max_drawdown_pct', 0):.2f}%")
                        r4.metric("Trades",        str(m.get('n_trades', 0)))
                        r5.metric("Win Rate",      f"{m.get('win_rate', 0):.1f}%")
                        r6.metric("Profit Factor", f"{m.get('profit_factor', 0):.2f}")

                        # Equity curve
                        ec = result.equity_curve
                        if len(ec) > 1:
                            ec_df = pd.DataFrame({"equity": ec})
                            ec_df.index = df_bt.index[min(50, len(df_bt) - len(ec)):][:len(ec)]
                            st.plotly_chart(
                                equity_curve_fig(ec_df, float(bt_cap),
                                                 f"{bt_sym} — {bt_strat} ({bt_period})"),
                                use_container_width=True,
                            )

                        # Trade distribution
                        if result.trades:
                            bt_trades = pd.DataFrame([
                                {"pnl": t.pnl} for t in result.trades
                            ])
                            st.plotly_chart(trade_dist_fig(bt_trades), use_container_width=True)

                    except Exception as exc:
                        st.error(f"Backtest error: {exc}")
                        import traceback
                        st.code(traceback.format_exc())


# ── Auto-refresh ───────────────────────────────────────────────────────────────

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
