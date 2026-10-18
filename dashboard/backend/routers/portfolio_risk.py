"""Portfolio risk dashboard (MarketPulse AI Phase 9 — spec §46/§47).

Reads the same paper-trading state as /api/positions and layers risk
analysis on top: exposure, sector concentration, pairwise correlation
between open positions, and threshold-based warnings. Correlation goes
through UpstoxDataEngine.fetch_ohlcv, so it works in demo mode too
(Phase 8's synthetic-data fallback applies transparently).
"""
from __future__ import annotations
import json

from fastapi import APIRouter

from config.instruments import STOCK_UNIVERSE
from ..config import _STATE_FILE, _DAILY_FILE
from ..utils import read_jsonl

router = APIRouter()

_SECTOR_WARN_PCT = 35.0
_CORRELATION_WARN = 0.7


def _load_state() -> dict:
    if not _STATE_FILE.exists():
        return {"positions": [], "cash": 0.0, "initial_capital": 500_000.0}
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {"positions": [], "cash": 0.0, "initial_capital": 500_000.0}


def _risk_config() -> dict:
    try:
        from config.loader import Settings
        return Settings().as_dict().get("risk", {})
    except Exception:
        return {}


def _correlation_matrix(symbols: list[str]) -> dict[str, dict[str, float]]:
    """Pairwise correlation of daily returns over the last 90 sessions.
    Best-effort: any fetch failure just drops that symbol rather than
    failing the whole risk dashboard."""
    unique = sorted(set(symbols))
    if len(unique) < 2:
        return {}
    try:
        import pandas as pd
        from config.loader import Settings
        from data_engine.upstox import InstrumentRegistry, UpstoxAuth, UpstoxDataEngine

        cfg = Settings().as_dict()
        up_cfg = cfg.get("exchanges", {}).get("upstox", {})
        auth = UpstoxAuth(
            api_key=up_cfg.get("api_key", ""), api_secret=up_cfg.get("api_secret", ""),
            redirect_uri=up_cfg.get("redirect_uri", "http://localhost:3561/callback"),
        )
        auth.load_token()
        registry = InstrumentRegistry()
        registry.load()
        engine = UpstoxDataEngine(auth, registry)

        closes = {}
        for sym in unique:
            try:
                df = engine.fetch_ohlcv(sym, "1d", lookback_days=90)
            except Exception:
                continue
            if not df.empty:
                closes[sym] = df["close"]

        if len(closes) < 2:
            return {}
        price_df = pd.DataFrame(closes).dropna()
        if len(price_df) < 5:
            return {}
        returns = price_df.pct_change().dropna()
        corr = returns.corr()
        return {a: {b: (None if pd.isna(v) else round(float(v), 3))
                    for b, v in row.items()} for a, row in corr.to_dict().items()}
    except Exception:
        return {}


@router.get("/portfolio/risk")
def get_portfolio_risk() -> dict:
    state = _load_state()
    positions: list[dict] = state.get("positions", [])
    cash = float(state.get("cash", 0.0))
    capital = float(state.get("initial_capital", 500_000.0)) or 500_000.0

    market_value = sum(p.get("size", 0) * p.get("current_price", 0) for p in positions)
    unrealized_pnl = sum(p.get("unrealised_pnl", 0) for p in positions)
    max_loss = sum(
        abs(p.get("entry_price", 0) - p.get("stop_loss", p.get("entry_price", 0))) * p.get("size", 0)
        for p in positions
    )

    daily_records = read_jsonl(_DAILY_FILE)
    today_realised = daily_records[-1].get("realised", 0.0) if daily_records else 0.0
    daily_pnl = today_realised + unrealized_pnl

    sector_exposure: dict[str, float] = {}
    for p in positions:
        info = STOCK_UNIVERSE.get(p.get("symbol", ""), {})
        sector = info.get("sector", "Other")
        value = p.get("size", 0) * p.get("current_price", 0)
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + value

    sector_exposure_pct = {
        sector: round(value / capital * 100, 2)
        for sector, value in sector_exposure.items()
    }

    symbols = [p["symbol"] for p in positions if p.get("symbol")]
    correlation = _correlation_matrix(symbols)

    risk_cfg = _risk_config()
    max_daily_drawdown = risk_cfg.get("max_daily_drawdown", 0.05)
    max_portfolio_risk = risk_cfg.get("max_portfolio_risk", 0.20)

    warnings: list[dict] = []

    for sector, pct in sorted(sector_exposure_pct.items(), key=lambda kv: -kv[1]):
        if pct > _SECTOR_WARN_PCT:
            warnings.append({
                "type": "sector_concentration", "severity": "warning",
                "message": f"{sector} concentration is high: {pct:.1f}% of capital",
            })

    seen_pairs = set()
    for a, row in correlation.items():
        for b, v in row.items():
            if a >= b or v is None or (a, b) in seen_pairs:
                continue
            seen_pairs.add((a, b))
            if v >= _CORRELATION_WARN:
                warnings.append({
                    "type": "high_correlation", "severity": "warning",
                    "message": f"{a} and {b} are highly correlated ({v:.2f}) — limited diversification benefit",
                })

    if capital and market_value / capital > max_portfolio_risk:
        warnings.append({
            "type": "total_exposure", "severity": "warning",
            "message": f"Total exposure {market_value / capital * 100:.1f}% exceeds the "
                       f"{max_portfolio_risk * 100:.0f}% portfolio risk limit",
        })

    if daily_pnl < -capital * max_daily_drawdown:
        warnings.append({
            "type": "daily_loss_limit", "severity": "critical",
            "message": f"Daily loss limit reached: {daily_pnl:,.0f} exceeds the "
                       f"{max_daily_drawdown * 100:.0f}% max daily drawdown",
        })

    return {
        "capital": capital,
        "cash": cash,
        "market_value": round(market_value, 2),
        "open_positions": len(positions),
        "daily_pnl": round(daily_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "exposure_pct": round(market_value / capital * 100, 2) if capital else 0.0,
        "max_loss": round(max_loss, 2),
        "sector_exposure_pct": sector_exposure_pct,
        "correlation": correlation,
        "warnings": warnings,
    }


@router.get("/portfolio/analytics")
def get_portfolio_analytics() -> dict:
    """Beta and hedge, factor exposures and crisis stress tests for the
    current holdings (analytics/portfolio_analytics.py). Slower than
    /portfolio/risk: it fetches a year of daily bars (cached)."""
    from analytics.portfolio_analytics import analyse
    from data_engine.history import fetch_daily
    state = _load_state()
    capital = float(state.get("initial_capital", 500_000.0)) or 500_000.0
    return analyse(state.get("positions", []), capital, fetch_daily)
