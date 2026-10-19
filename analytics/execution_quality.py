"""
Execution quality from logs/executions.jsonl (written by UpstoxExecutor for
every entry and exit order, paper and live).

Slippage is measured against the **decision price** — the price the signal
(or the stop/target check) saw when it decided to trade — in basis points,
positive = cost: a buy filled above, or a sell filled below, that price.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
EXECUTION_LOG = ROOT / "logs" / "executions.jsonl"


def load(path: Path = EXECUTION_LOG) -> list[dict]:
    import json
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _stats(rows: list[dict]) -> dict:
    filled = [r for r in rows if r.get("fill_price")]
    slip = [r["slippage_bps"] for r in filled if r.get("slippage_bps") is not None]
    cost = sum((r["slippage_bps"] or 0) / 1e4 * r["fill_price"] * r["filled_qty"]
               for r in filled if r.get("slippage_bps") is not None)
    return {
        "orders": len(rows),
        "fill_rate_pct": round(len(filled) / len(rows) * 100, 1) if rows else None,
        "avg_slippage_bps": round(float(np.mean(slip)), 2) if slip else None,
        "median_slippage_bps": round(float(np.median(slip)), 2) if slip else None,
        "p90_slippage_bps": round(float(np.percentile(slip, 90)), 2) if slip else None,
        "slippage_cost": round(cost, 2),
        "avg_latency_ms": (round(float(np.mean([r["latency_ms"] for r in rows if "latency_ms" in r])))
                           if rows else None),
    }


def _group(rows: Iterable[dict], key) -> list[dict]:
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[str(key(r))].append(r)
    return [{"key": k, **_stats(v)} for k, v in sorted(groups.items())]


def report(rows: list[dict], days: int = 30, mode: Optional[str] = None,
           now: Optional[datetime] = None) -> dict:
    """Execution-quality summary of the last `days` days (optionally one mode)."""
    now = now or datetime.now().astimezone()
    since = (now - timedelta(days=days)).isoformat()
    sel = [r for r in rows if r.get("ts", "") >= since[:19] and (mode is None or r.get("mode") == mode)]
    outcomes: dict[str, int] = defaultdict(int)
    for r in sel:
        outcomes[r.get("outcome", "unknown")] += 1
    return {
        "days": days, "mode": mode, "overall": _stats(sel), "outcomes": dict(outcomes),
        "by_kind": _group(sel, lambda r: r.get("kind", "?")),
        "by_order_type": _group(sel, lambda r: r.get("order_type", "?")),
        "by_strategy": _group(sel, lambda r: r.get("strategy") or "?"),
        "by_hour": _group(sel, lambda r: r.get("ts", "")[11:13] or "?"),
        "by_chases": _group([r for r in sel if r.get("order_type") == "LIMIT"],
                            lambda r: r.get("chases", 0)),
    }
