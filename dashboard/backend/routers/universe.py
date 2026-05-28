from fastapi import APIRouter
from config.instruments import get_sector_map, SECTOR_COLORS, STOCK_UNIVERSE
from ..config import _WATCHLIST_SYMS

router = APIRouter()

@router.get("/universe")
def get_universe() -> dict:
    sectors = []
    for sector_name, symbols in get_sector_map().items():
        stocks = []
        for sym in symbols:
            info = STOCK_UNIVERSE.get(sym, {})
            stocks.append({
                "symbol":     sym,
                "name":       info.get("name", sym),
                "industry":   info.get("industry", ""),
                "market_cap": info.get("market_cap", ""),
                "fno":        info.get("fno", False),
                "nifty50":    info.get("nifty50", False),
            })
        sectors.append({
            "sector": sector_name,
            "color":  SECTOR_COLORS.get(sector_name, "#64748b"),
            "stocks": stocks,
        })
    return {
        "sectors":       sectors,
        "total_stocks":  sum(len(s["stocks"]) for s in sectors),
        "watchlist":     _WATCHLIST_SYMS,
    }