# In-memory state for backtest jobs and price stream cache
_bt_jobs: dict[str, dict] = {}
_price_cache: dict[str, dict] = {}

def get_backtest_jobs():
    return _bt_jobs

def get_price_cache():
    return _price_cache