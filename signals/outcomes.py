"""
Signal outcomes: did the composite signals work?

For the last daily signal of each stock on each trading day, record the
forward returns 1, 5 and 20 trading days after that day's close, and walk
its trade setup forward to see whether it reached target or stop first.
`performance()` aggregates the results by direction, score band and
component, against the average return of every evaluated signal (the
market's drift over the same days) as the baseline.

Run daily after the close by the scheduler (`signal_outcomes` job) or by
`python scripts/evaluate_signals.py`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Signal, SignalDirection, SignalOutcome, TradeSetup
from utils.logger import get_logger

logger = get_logger("signal_outcomes")

HORIZONS = (1, 5, 20)
SETUP_MAX_BARS = 20
_IST = "Asia/Kolkata"
_SIGN = {SignalDirection.BULLISH: 1, SignalDirection.BEARISH: -1}
COMPONENTS = ("catalyst", "technical", "momentum", "volume", "historical", "regime", "risk")


def _ist_date(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(_IST).date().isoformat()


def _daily_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Daily bars indexed by IST trading date (YYYY-MM-DD)."""
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    out = df.copy()
    out.index = [d.isoformat() for d in idx.tz_convert(_IST).date]
    return out[~out.index.duplicated(keep="last")].sort_index()


def evaluate(direction: SignalDirection, signal_date: str, bars: pd.DataFrame,
             setup: Optional[TradeSetup] = None) -> Optional[dict]:
    """Outcome fields for one signal from daily bars indexed by IST date, or
    None if the signal day's close is not available yet."""
    if signal_date not in bars.index:
        return None
    pos = bars.index.get_loc(signal_date)
    entry = float(bars["close"].iloc[pos])
    after = bars.iloc[pos + 1:]
    out: dict = {"entry_price": entry}
    for k in HORIZONS:
        out[f"ret_{k}d"] = (float(after["close"].iloc[k - 1]) / entry - 1) if len(after) >= k else None

    out["setup_result"], out["setup_bars"] = None, None
    sign = _SIGN.get(direction)
    if setup is not None and sign:
        for n, (_, bar) in enumerate(after.iloc[:SETUP_MAX_BARS].iterrows(), start=1):
            hit_stop = bar["low"] <= setup.stop_loss if sign == 1 else bar["high"] >= setup.stop_loss
            hit_tgt = bar["high"] >= setup.target_1 if sign == 1 else bar["low"] <= setup.target_1
            if hit_stop or hit_tgt:                 # both in one bar: assume the stop came first
                out["setup_result"], out["setup_bars"] = ("stop" if hit_stop else "target"), n
                break
        else:
            if len(after) >= SETUP_MAX_BARS:
                out["setup_result"], out["setup_bars"] = "expired", SETUP_MAX_BARS
    setup_done = setup is None or not sign or out["setup_result"] is not None
    out["complete"] = out[f"ret_{HORIZONS[-1]}d"] is not None and setup_done
    return out


def pending_signals(db: Session, since: datetime, today: str) -> list[Signal]:
    """The last daily signal per stock per completed IST trading day since
    `since` that has no complete outcome yet."""
    done = set(db.scalars(select(SignalOutcome.signal_id).where(SignalOutcome.complete.is_(True))))
    rows = db.scalars(select(Signal).where(Signal.timeframe == "1d", Signal.timestamp >= since)
                      .order_by(Signal.timestamp)).all()
    last: dict[tuple[int, str], Signal] = {}
    for s in rows:
        day = _ist_date(s.timestamp)
        if day < today:
            last[(s.stock_id, day)] = s              # later rows replace earlier ones
    return [s for s in last.values() if s.id not in done]


def update_outcomes(db: Session, fetch_daily: Callable[[list[str], int], dict],
                    now: Optional[datetime] = None, max_age_days: int = 60) -> dict:
    """Fill or refresh outcomes for pending signals. `fetch_daily(symbols,
    days)` returns {symbol: daily OHLCV}. Also marks trade setups that hit
    their stop or expired as invalidated, and their signals as closed or
    invalidated."""
    now = now or datetime.now(timezone.utc)
    today = _ist_date(now)
    pending = pending_signals(db, now - timedelta(days=max_age_days), today)
    if not pending:
        return {"pending": 0, "updated": 0, "completed": 0}
    by_symbol: dict[str, list[Signal]] = defaultdict(list)
    for s in pending:
        by_symbol[s.stock.symbol].append(s)
    frames = fetch_daily(sorted(by_symbol), max_age_days + 45)
    existing = {o.signal_id: o for o in db.scalars(
        select(SignalOutcome).where(SignalOutcome.signal_id.in_([s.id for s in pending])))}

    updated = completed = 0
    for symbol, sigs in by_symbol.items():
        df = frames.get(symbol)
        if df is None or df.empty:
            continue
        bars = _daily_by_date(df)
        for s in sigs:
            setup = db.scalar(select(TradeSetup).where(TradeSetup.signal_id == s.id))
            day = _ist_date(s.timestamp)
            res = evaluate(s.direction, day, bars, setup)
            if res is None:
                continue
            row = existing.get(s.id) or SignalOutcome(signal_id=s.id, signal_date=day)
            for k, v in res.items():
                setattr(row, k, v)
            row.updated_at = now
            db.add(row)
            updated += 1
            completed += bool(res["complete"])
            if setup is not None and res["setup_result"] and setup.invalidated_at is None:
                if res["setup_result"] in ("stop", "expired"):
                    setup.invalidated_at = now
                s.status = "closed" if res["setup_result"] == "target" else "invalidated"
    db.flush()
    logger.info(f"Signal outcomes: {updated} updated, {completed} complete, {len(pending)} pending")
    return {"pending": len(pending), "updated": updated, "completed": completed}


# ── Reporting ────────────────────────────────────────────────────────────────

def _band(score: float) -> str:
    lo = int(min(max(score, 0), 99.999) // 10 * 10)
    return f"{lo}-{lo + 10}"


def performance(db: Session, days: int = 90, now: Optional[datetime] = None) -> dict:
    """How the signals of the last `days` days did. Returns are in percent;
    for bullish and bearish signals they are direction-adjusted (a bearish
    signal followed by a fall counts as positive). `baseline` is the average
    raw return of every evaluated signal — what simply holding the stocks
    the engine looked at would have done over the same days."""
    now = now or datetime.now(timezone.utc)
    since = _ist_date(now - timedelta(days=days))
    rows = db.execute(select(SignalOutcome, Signal).join(Signal, SignalOutcome.signal_id == Signal.id)
                      .where(SignalOutcome.signal_date >= since)).all()

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(float(np.mean(xs)) * 100, 3) if xs else None

    def hit(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(x > 0 for x in xs) / len(xs) * 100, 1) if xs else None

    baseline = {f"ret_{k}d": mean([getattr(o, f"ret_{k}d") for o, _ in rows]) for k in HORIZONS}

    by_direction = []
    for d in SignalDirection:
        sel = [(o, s) for o, s in rows if s.direction == d]
        sign = _SIGN.get(d, 1)
        stats = {"direction": d.value, "count": len(sel)}
        for k in HORIZONS:
            vals = [None if getattr(o, f"ret_{k}d") is None else sign * getattr(o, f"ret_{k}d")
                    for o, _ in sel]
            stats[f"avg_{k}d"] = mean(vals)
            stats[f"hit_{k}d"] = hit(vals) if d in _SIGN else None
            base = baseline[f"ret_{k}d"]
            stats[f"excess_{k}d"] = (round(stats[f"avg_{k}d"] - sign * base, 3)
                                     if d in _SIGN and stats[f"avg_{k}d"] is not None and base is not None
                                     else None)
        res = [o.setup_result for o, _ in sel if o.setup_result]
        stats["setups"] = {r: res.count(r) for r in ("target", "stop", "expired")}
        by_direction.append(stats)

    actionable = [(o, s) for o, s in rows if s.direction in _SIGN]

    def adj5(o, s):
        return None if o.ret_5d is None else _SIGN[s.direction] * o.ret_5d

    bands: dict[str, list] = defaultdict(list)
    for o, s in actionable:
        bands[_band(s.score)].append(adj5(o, s))
    by_score = [{"band": b, "count": len(v), "avg_5d": mean(v), "hit_5d": hit(v)}
                for b, v in sorted(bands.items())]

    components = []
    pairs = [(s, adj5(o, s)) for o, s in actionable if adj5(o, s) is not None]
    for c in COMPONENTS:
        xs = [getattr(s, f"{c}_score") for s, _ in pairs]
        ys = [r for _, r in pairs]
        corr = (float(np.corrcoef(xs, ys)[0, 1])
                if len(pairs) >= 10 and np.std(xs) > 0 and np.std(ys) > 0 else None)
        components.append({"component": c, "corr_5d": None if corr is None else round(corr, 3)})

    return {"days": days, "evaluated": len(rows),
            "complete": sum(1 for o, _ in rows if o.complete),
            "baseline": baseline, "by_direction": by_direction,
            "by_score": by_score, "components": components}
