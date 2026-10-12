"""
Intraday trading guard — the session-level rules the live bot applies on top
of per-trade risk checks:

  • entry window          no new intraday (MIS) entries outside entry_start–entry_end
  • trade caps            max entries per day and per symbol
  • cooldown              no re-entry into a symbol for N minutes after a stop-out
  • kill switch           day P&L (realised + unrealised) below −max_daily_drawdown
                          × capital → flatten everything and halt entries for the day
  • profit lock           day P&L above profit_lock_pct × capital → halt new entries
  • pause                 entries paused by the operator (dashboard / control file)

Pure logic with no I/O, so every rule is unit-testable; main.py owns the
side effects (closing positions, notifications, persistence).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta


def _parse_hhmm(value: str, default: time) -> time:
    try:
        h, m = str(value).split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return default


@dataclass
class IntradayGuard:
    entry_start: time = time(9, 30)
    entry_end: time = time(14, 45)
    max_trades_per_day: int = 20
    max_trades_per_symbol: int = 3
    cooldown_minutes: int = 30
    max_daily_loss_pct: float = 0.05
    flatten_on_daily_loss: bool = True
    profit_lock_pct: float = 0.0          # 0 = off

    # Session state
    session_date: date | None = None
    trades_today: int = 0
    trades_by_symbol: dict[str, int] = field(default_factory=dict)
    cooldown_until: dict[str, datetime] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str = ""
    paused: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> "IntradayGuard":
        ic = cfg.get("intraday", {}) or {}
        risk = cfg.get("risk", {}) or {}
        ks = ic.get("kill_switch", {}) or {}
        return cls(
            entry_start=_parse_hhmm(ic.get("entry_start", "09:30"), time(9, 30)),
            entry_end=_parse_hhmm(ic.get("entry_end", "14:45"), time(14, 45)),
            max_trades_per_day=int(ic.get("max_trades_per_day", 20)),
            max_trades_per_symbol=int(ic.get("max_trades_per_symbol", 3)),
            cooldown_minutes=int(ic.get("cooldown_minutes_after_stop", 30)),
            max_daily_loss_pct=float(risk.get("max_daily_drawdown", 0.05)),
            flatten_on_daily_loss=bool(ks.get("flatten_on_daily_loss", True)),
            profit_lock_pct=float(ic.get("profit_lock_pct", 0.0) or 0.0),
        )

    # ── Session ──────────────────────────────────────────────────────────────

    def new_day(self, day: date) -> bool:
        """Reset the per-day state when the trading day changes. Returns True
        on a reset. A pause set by the operator survives into the next day."""
        if self.session_date == day:
            return False
        self.session_date = day
        self.trades_today = 0
        self.trades_by_symbol.clear()
        self.cooldown_until.clear()
        self.halted = False
        self.halt_reason = ""
        return True

    def in_entry_window(self, now: datetime) -> bool:
        return self.entry_start <= now.time() <= self.entry_end

    # ── Entry decisions ──────────────────────────────────────────────────────

    def can_enter(self, symbol: str, now: datetime, intraday_product: bool) -> tuple[bool, str]:
        """(allowed, reason). The reason names the first rule that blocks."""
        if self.paused:
            return False, "entries paused"
        if self.halted:
            return False, f"halted: {self.halt_reason}"
        if intraday_product and not self.in_entry_window(now):
            return False, (f"outside entry window {self.entry_start:%H:%M}–"
                           f"{self.entry_end:%H:%M}")
        if self.max_trades_per_day and self.trades_today >= self.max_trades_per_day:
            return False, f"daily trade cap {self.max_trades_per_day} reached"
        if self.max_trades_per_symbol and \
                self.trades_by_symbol.get(symbol, 0) >= self.max_trades_per_symbol:
            return False, f"{symbol} trade cap {self.max_trades_per_symbol} reached"
        until = self.cooldown_until.get(symbol)
        if until and now < until:
            return False, f"{symbol} cooling down until {until:%H:%M}"
        return True, ""

    def record_entry(self, symbol: str) -> None:
        self.trades_today += 1
        self.trades_by_symbol[symbol] = self.trades_by_symbol.get(symbol, 0) + 1

    def record_exit(self, symbol: str, reason: str, now: datetime) -> None:
        if reason == "stop_loss" and self.cooldown_minutes > 0:
            self.cooldown_until[symbol] = now + timedelta(minutes=self.cooldown_minutes)

    # ── Day P&L limits ───────────────────────────────────────────────────────

    def check_day_pnl(self, day_pnl: float, capital: float) -> str | None:
        """Evaluate the day's P&L (realised + unrealised). Returns "kill" when
        the loss limit is newly breached (caller flattens if
        flatten_on_daily_loss), "lock" when the profit lock newly triggers,
        else None. Either halts new entries for the rest of the day."""
        if self.halted or capital <= 0:
            return None
        if self.max_daily_loss_pct > 0 and day_pnl <= -self.max_daily_loss_pct * capital:
            self.halted = True
            self.halt_reason = (f"daily loss ₹{-day_pnl:,.0f} hit the "
                                f"{self.max_daily_loss_pct:.1%} limit")
            return "kill"
        if self.profit_lock_pct > 0 and day_pnl >= self.profit_lock_pct * capital:
            self.halted = True
            self.halt_reason = (f"profit lock: day P&L ₹{day_pnl:,.0f} reached "
                                f"{self.profit_lock_pct:.1%}")
            return "lock"
        return None

    def resume(self) -> None:
        """Operator override: clear a halt (and a pause)."""
        self.halted = False
        self.halt_reason = ""
        self.paused = False

    # ── Reporting / persistence ──────────────────────────────────────────────

    def to_state(self, now: datetime | None = None) -> dict:
        return {
            "session_date": self.session_date.isoformat() if self.session_date else None,
            "entry_start": f"{self.entry_start:%H:%M}",
            "entry_end": f"{self.entry_end:%H:%M}",
            "in_entry_window": self.in_entry_window(now) if now else None,
            "max_trades_per_day": self.max_trades_per_day,
            "max_trades_per_symbol": self.max_trades_per_symbol,
            "trades_today": self.trades_today,
            "trades_by_symbol": dict(self.trades_by_symbol),
            "cooldowns": {s: t.isoformat() for s, t in self.cooldown_until.items()
                          if now is None or t > now},
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "profit_lock_pct": self.profit_lock_pct,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "paused": self.paused,
        }

    def restore(self, state: dict, today: date) -> None:
        """Reload today's counters after a restart (ignored for another day)."""
        if not state or state.get("session_date") != today.isoformat():
            return
        self.session_date = today
        self.trades_today = int(state.get("trades_today", 0))
        self.trades_by_symbol = {k: int(v) for k, v in (state.get("trades_by_symbol") or {}).items()}
        self.cooldown_until = {k: datetime.fromisoformat(v)
                               for k, v in (state.get("cooldowns") or {}).items()}
        self.halted = bool(state.get("halted", False))
        self.halt_reason = state.get("halt_reason", "")
        self.paused = bool(state.get("paused", False))
