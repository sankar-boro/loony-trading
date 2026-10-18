from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/config")
def get_config() -> dict:
    try:
        from config.loader import Settings
        from strategies.meta_engine import registered_strategy_names, strategy_params
        s = Settings()
        return {
            "weights":       s.get("strategies.weights") or {},
            "enabled":       s.get("strategies.enabled") or [],
            "capital":       s.get("portfolio.initial_capital") or 500_000,
            "all_strategies": registered_strategy_names(),
            "params":        strategy_params(s._data),
        }
    except Exception as e:
        raise HTTPException(500, str(e))