import json
import os
import time
from pathlib import Path

from .config import _TOKEN_FILE, ROOT

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records

def get_token() -> tuple[str, float]:
    env = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if _TOKEN_FILE.exists():
        try:
            d = json.loads(_TOKEN_FILE.read_text())
            file_tok = d.get("access_token", "")
            age_h = (time.time() - d.get("obtained_at", 0)) / 3600
            return (env or file_tok), age_h
        except Exception:
            pass
    return env, -1.0

def load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v

load_env()   # run once at module import

def empty_stats():
    return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
            "avg_win": 0, "avg_loss": 0, "expectancy": 0, "profit_factor": 0}

def empty_daily_summary():
    return {"total_realised": 0, "avg_daily": 0, "best_day": None,
            "worst_day": None, "sharpe_ann": 0, "total_trades": 0, "overall_win_rate": 0}