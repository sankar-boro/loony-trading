from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from .config import _DIST_DIR
from .routers import (
    status_router, positions_router, equity_router, trades_router,
    daily_router, config_router, watchlist_router, market_router,
    universe_router, signals_router, telegram_router, chart_router,
    ltp_router, stream_router, backtest_router, news_router,
    composite_signals_router, copilot_router, watchlists_router, alerts_router
)

app = FastAPI(title="Loony Trading API", docs_url="/api/docs")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174",
        "http://localhost:5175", "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(status_router, prefix="/api", tags=["status"])
app.include_router(positions_router, prefix="/api", tags=["positions"])
app.include_router(equity_router, prefix="/api", tags=["equity"])
app.include_router(trades_router, prefix="/api", tags=["trades"])
app.include_router(daily_router, prefix="/api", tags=["daily"])
app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(watchlist_router, prefix="/api", tags=["watchlist"])
app.include_router(market_router, prefix="/api", tags=["market"])
app.include_router(universe_router, prefix="/api", tags=["universe"])
app.include_router(signals_router, prefix="/api", tags=["signals"])
app.include_router(telegram_router, prefix="/api", tags=["telegram"])
app.include_router(chart_router, prefix="/api", tags=["chart"])
app.include_router(ltp_router, prefix="/api", tags=["ltp"])
app.include_router(stream_router, prefix="/api", tags=["stream"])
app.include_router(backtest_router, prefix="/api", tags=["backtest"])
app.include_router(news_router, prefix="/api", tags=["news"])
app.include_router(composite_signals_router, prefix="/api", tags=["signals"])
app.include_router(copilot_router, prefix="/api", tags=["copilot"])
app.include_router(watchlists_router, prefix="/api", tags=["watchlists"])
app.include_router(alerts_router, prefix="/api", tags=["alerts"])

# Static files for React (production)
if _DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = _DIST_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(404)