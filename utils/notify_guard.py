"""
One guard for every notification the process sends (Notifier, used by the
bot, and TelegramAlerter, used by the dashboard and scheduler):

- **dedupe** — the same text is sent at most once per `dedupe_minutes`;
- **keys** — callers can name an event (`"scan:TCS:BUY:2026-10-19"`) and
  give it its own cooldown, e.g. once a day per scanner signal;
- **rate limit** — at most `rate_limit_per_minute` messages a minute;
  CRITICAL messages are never rate-limited (but still de-duplicated).

Settings: `notifications.dedupe_minutes` (10) and
`notifications.rate_limit_per_minute` (20).
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from typing import Optional

from utils.logger import get_logger

logger = get_logger("notify_guard")


class NotificationGuard:
    def __init__(self, dedupe_minutes: float = 10, rate_limit_per_minute: int = 20,
                 clock=time.monotonic):
        self.dedupe_sec = dedupe_minutes * 60
        self.rate_limit = rate_limit_per_minute
        self._clock = clock
        self._last: dict[str, float] = {}
        self._sent: deque = deque()
        self._lock = threading.Lock()
        self.suppressed = 0

    def allow(self, text: str, level: str = "INFO", key: Optional[str] = None,
              cooldown_sec: Optional[float] = None) -> bool:
        now = self._clock()
        ident = key or "msg:" + hashlib.sha1(text.encode()).hexdigest()
        window = self.dedupe_sec if cooldown_sec is None else cooldown_sec
        with self._lock:
            last = self._last.get(ident)
            if last is not None and now - last < window:
                self.suppressed += 1
                return False
            while self._sent and now - self._sent[0] >= 60:
                self._sent.popleft()
            if level != "CRITICAL" and self.rate_limit and len(self._sent) >= self.rate_limit:
                self.suppressed += 1
                logger.warning(f"Notification rate limit ({self.rate_limit}/min) — dropped: {text[:80]}")
                return False
            self._last[ident] = now
            self._sent.append(now)
            if len(self._last) > 5000:                      # keep memory bounded
                cutoff = now - max(self.dedupe_sec, 86400)
                self._last = {k: t for k, t in self._last.items() if t >= cutoff}
            return True


_guard: Optional[NotificationGuard] = None


def get_guard() -> NotificationGuard:
    """The process-wide guard, configured from settings.yaml on first use."""
    global _guard
    if _guard is None:
        try:
            from config.loader import Settings
            nc = Settings().as_dict().get("notifications", {}) or {}
        except Exception:
            nc = {}
        _guard = NotificationGuard(float(nc.get("dedupe_minutes", 10)),
                                   int(nc.get("rate_limit_per_minute", 20)))
    return _guard
