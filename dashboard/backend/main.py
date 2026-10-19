from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
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
    composite_signals_router, copilot_router, watchlists_router, alerts_router,
    portfolio_risk_router, scheduler_router, doc_files_router, intraday_desk_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from config.loader import Settings
    from scheduler import start_scheduler, stop_scheduler
    start_scheduler(Settings().as_dict())
    yield
    stop_scheduler()


app = FastAPI(title="Loony Trading API", docs_url="/api/docs", lifespan=lifespan)

# Login (dashboard/backend/auth.py): with DASHBOARD_PASSWORD set every API
# route needs a session; without one the API only answers this machine.
from . import auth  # noqa: E402
app.middleware("http")(auth.middleware)
app.include_router(auth.router, prefix="/api", tags=["auth"])

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5163", "http://localhost:5174",
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
app.include_router(portfolio_risk_router, prefix="/api", tags=["portfolio"])
app.include_router(scheduler_router, prefix="/api", tags=["scheduler"])
app.include_router(doc_files_router, prefix="/api", tags=["docs"])
app.include_router(intraday_desk_router, prefix="/api", tags=["intraday"])

# Static files for React (production)
if _DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = _DIST_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(404)