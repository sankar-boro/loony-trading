from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Data files
_STATE_FILE   = ROOT / "data" / "live_positions.json"
_EQUITY_FILE  = ROOT / "data" / "equity_curve.jsonl"
_PAPER_LOG    = ROOT / "logs" / "paper_trades.jsonl"
_LIVE_LOG     = ROOT / "logs" / "trades.jsonl"
_DAILY_FILE   = ROOT / "data" / "daily_pnl.jsonl"
_TOKEN_FILE   = ROOT / "data" / "upstox_token.json"
_DIST_DIR     = Path(__file__).parent.parent / "frontend" / "dist"

_BOT_STALE    = 300

# Watchlist symbols (shared across routers)
_WATCHLIST_SYMS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BAJFINANCE", "AXISBANK", "KOTAKBANK", "BHARTIARTL",
    "WIPRO", "HCLTECH", "TATAMOTORS", "MARUTI", "ITC",
    "SUNPHARMA", "DRREDDY", "TITAN", "ASIANPAINT", "ULTRACEMCO",
    "LT", "NTPC", "POWERGRID", "ONGC", "JSWSTEEL",
    "HINDUNILVR", "NESTLEIND", "APOLLOHOSP", "ADANIPORTS", "ZOMATO",
]