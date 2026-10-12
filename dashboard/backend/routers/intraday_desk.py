"""
Intraday Desk — one call with everything the live-session page needs, plus
the operator controls (pause / resume / flatten).

Read-only aggregation of files the bot writes:
  data/live_positions.json   positions, intraday guard state, events, heartbeat
  data/intraday_pnl.jsonl    one P&L point a minute
  logs/trades.jsonl          closed trades
Controls go to data/bot_control.json (utils/bot_control.py), which the bot
polls on every tick.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, time as dtime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.bot_control import CONTROL_FILE, read_control, write_control
from ..config import ROOT, _LIVE_LOG, _STATE_FILE
from ..utils import read_jsonl

router = APIRouter()

_PNL_FILE = ROOT / "data" / "intraday_pnl.jsonl"
_CONTROL_FILE = CONTROL_FILE
_SETTINGS = ROOT / "config" / "settings.yaml"
_BOT_LIVE_SEC = 30          # the bot rewrites its state at least every 5 s
_FEED_STALE_SEC = 120       # no tick for this long during market hours → stale

_OPEN, _SQUAREOFF, _CLOSE = dtime(9, 15), dtime(15, 14), dtime(15, 30)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _guard_defaults() -> dict:
    """Entry window and limits from settings.yaml, for when the bot is not
    running (its state file carries the live values)."""
    try:
        import yaml
        from risk_manager.intraday_guard import IntradayGuard
        cfg = yaml.safe_load(_SETTINGS.read_text()) or {}
        return IntradayGuard.from_config(cfg).to_state()
    except Exception:
        return {}


def _session(now: datetime, entry_start: str, entry_end: str) -> dict:
    """Where the trading day stands: phase, and minutes to the next boundaries."""
    from utils.timeutils import _is_holiday
    trading_day = now.weekday() < 5 and not _is_holiday(now.date())
    t = now.time()
    es = datetime.strptime(entry_start, "%H:%M").time()
    ee = datetime.strptime(entry_end, "%H:%M").time()

    def mins_to(target: dtime) -> int:
        delta = datetime.combine(now.date(), target, now.tzinfo) - now
        return max(0, int(delta.total_seconds() // 60))

    if not trading_day:
        phase = "holiday" if now.weekday() < 5 else "weekend"
    elif t < _OPEN:
        phase = "pre_open"
    elif t < es:
        phase = "opening"            # market open, entries not yet allowed
    elif t <= ee:
        phase = "entry_window"
    elif t < _SQUAREOFF:
        phase = "manage_only"        # no new MIS entries; exits still managed
    elif t <= _CLOSE:
        phase = "squareoff"
    else:
        phase = "closed"
    return {
        "now": now.isoformat(timespec="seconds"),
        "phase": phase,
        "trading_day": trading_day,
        "market_open": "09:15", "squareoff": "15:14", "market_close": "15:30",
        "entry_start": entry_start, "entry_end": entry_end,
        "mins_to_entry_end": mins_to(ee) if trading_day else 0,
        "mins_to_squareoff": mins_to(_SQUAREOFF) if trading_day else 0,
        "mins_to_close": mins_to(_CLOSE) if trading_day else 0,
    }


def _ist_date(ts: str) -> str:
    from utils.timeutils import IST
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        return dt.date().isoformat()
    return dt.astimezone(IST).date().isoformat()


@router.get("/intraday/desk")
def get_desk() -> dict:
    from utils.timeutils import now_ist

    now = now_ist()
    today = now.date().isoformat()
    state = _read_json(_STATE_FILE)
    is_main = state.get("source") == "main"
    saved_at = float(state.get("saved_at", 0) or 0)
    running = is_main and time.time() - saved_at < _BOT_LIVE_SEC

    guard = state.get("intraday") if is_main else None
    if not guard or guard.get("session_date") not in (None, today):
        guard = {**_guard_defaults(), "session_date": today}
    session = _session(now, guard.get("entry_start", "09:30"), guard.get("entry_end", "14:45"))

    positions = state.get("positions", []) if is_main else []
    unrealised = sum(float(p.get("unrealised_pnl", 0) or 0) for p in positions)

    trades = [r for r in read_jsonl(_LIVE_LOG)
              if r.get("type") == "close" and _ist_date(r.get("ts", "")) == today]
    realised = sum(float(t.get("pnl", 0) or 0) for t in trades)
    by_strategy: dict[str, dict] = {}
    for t in trades:
        s = by_strategy.setdefault(t.get("strategy") or "unknown",
                                   {"strategy": t.get("strategy") or "unknown",
                                    "trades": 0, "wins": 0, "pnl": 0.0})
        s["trades"] += 1
        s["wins"] += float(t.get("pnl", 0) or 0) > 0
        s["pnl"] += float(t.get("pnl", 0) or 0)

    curve = [r for r in read_jsonl(_PNL_FILE) if _ist_date(r.get("ts", "")) == today]

    capital = float(state.get("initial_capital", 0) or 0) or 500_000.0
    loss_limit = float(guard.get("max_daily_loss_pct", 0.05) or 0) * capital
    day_pnl = realised + unrealised
    last_tick_at = float(state.get("last_tick_at", 0) or 0)
    feed_age = time.time() - last_tick_at if last_tick_at else None
    events = [e for e in (state.get("events", []) if is_main else [])
              if _ist_date(e.get("ts", "")) == today]

    return {
        "session": session,
        "bot": {
            "running": running,
            "mode": state.get("mode") if is_main else None,
            "saved_at": saved_at,
            "last_tick_at": last_tick_at,
            "feed_age_sec": round(feed_age, 1) if feed_age is not None else None,
            "feed_stale": bool(running and session["phase"] not in ("pre_open", "closed", "weekend", "holiday")
                               and (feed_age is None or feed_age > _FEED_STALE_SEC)),
            "exchange_stops": bool(state.get("exchange_stops", False)) if is_main else False,
        },
        "guard": guard,
        "control": read_control(_CONTROL_FILE),
        "pnl": {
            "realised": round(realised, 2),
            "unrealised": round(unrealised, 2),
            "day": round(day_pnl, 2),
            "capital": capital,
            "loss_limit": round(loss_limit, 2),
            "loss_used_pct": round(max(0.0, -day_pnl) / loss_limit * 100, 1) if loss_limit else 0.0,
            "profit_lock": round(float(guard.get("profit_lock_pct", 0) or 0) * capital, 2),
        },
        "positions": positions,
        "trades": trades,
        "by_strategy": sorted(by_strategy.values(), key=lambda s: s["pnl"], reverse=True),
        "curve": curve,
        "events": list(reversed(events)),
    }


class ControlRequest(BaseModel):
    action: str


@router.post("/intraday/control")
def post_control(req: ControlRequest) -> dict:
    if req.action not in ("pause", "resume", "flatten"):
        raise HTTPException(400, "action must be pause, resume or flatten")
    return {"ok": True, "action": req.action, "control": write_control(req.action, _CONTROL_FILE)}
