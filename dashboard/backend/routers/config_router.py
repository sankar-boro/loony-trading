from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/config")
def get_config() -> dict:
    try:
        from config.loader import Settings
        s = Settings()
        return {
            "weights":       s.get("strategies.weights") or {},
            "enabled":       s.get("strategies.enabled") or [],
            "capital":       s.get("portfolio.initial_capital") or 500_000,
            "all_strategies": [
                "ema_crossover", "rsi_mean_reversion", "bollinger_reversion",
                "macd_momentum", "breakout_atr", "supertrend", "donchian_breakout",
                "zscore_reversion", "vwap_reversion", "sr_breakout", "range_breakout",
                "rsi_momentum", "volume_momentum", "candlestick_pattern",
                "order_book_imbalance", "pair_trading", "ml_classifier",
            ],
        }
    except Exception as e:
        raise HTTPException(500, str(e))