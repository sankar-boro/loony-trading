from .status import router as status_router
from .positions import router as positions_router
from .equity import router as equity_router
from .trades import router as trades_router
from .daily import router as daily_router
from .config_router import router as config_router
from .watchlist import router as watchlist_router
from .market import router as market_router
from .universe import router as universe_router
from .signals import router as signals_router
from .telegram import router as telegram_router
from .chart import router as chart_router
from .ltp import router as ltp_router
from .stream import router as stream_router
from .backtest import router as backtest_router
from .news import router as news_router
from .composite_signals import router as composite_signals_router
from .copilot import router as copilot_router
from .watchlists import router as watchlists_router
from .alerts import router as alerts_router
from .portfolio_risk import router as portfolio_risk_router
from .scheduler import router as scheduler_router
from .doc_files import router as doc_files_router

__all__ = [
    "status_router", "positions_router", "equity_router", "trades_router",
    "daily_router", "config_router", "watchlist_router", "market_router",
    "universe_router", "signals_router", "telegram_router", "chart_router",
    "ltp_router", "stream_router", "backtest_router", "news_router",
    "composite_signals_router", "copilot_router", "watchlists_router",
    "alerts_router", "portfolio_risk_router", "scheduler_router",
    "doc_files_router",
]