"""Notification guard (dedupe, named cooldowns, rate limit), severity
routing, and alert cooldowns."""
from __future__ import annotations
import asyncio

from utils.notify_guard import NotificationGuard
from utils.notifier import Notifier


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_dedupe_same_text_within_window():
    clock = _Clock()
    g = NotificationGuard(dedupe_minutes=10, rate_limit_per_minute=0, clock=clock)
    assert g.allow("kill switch") and not g.allow("kill switch") and g.allow("other")
    clock.t += 601
    assert g.allow("kill switch")
    assert g.suppressed == 1


def test_named_key_cooldown():
    clock = _Clock()
    g = NotificationGuard(clock=clock)
    assert g.allow("x", key="scan:TCS:BUY", cooldown_sec=86400)
    clock.t += 3600
    assert not g.allow("different text", key="scan:TCS:BUY", cooldown_sec=86400)
    assert g.allow("x", key="scan:INFY:BUY", cooldown_sec=86400)


def test_rate_limit_spares_critical():
    clock = _Clock()
    g = NotificationGuard(dedupe_minutes=0, rate_limit_per_minute=3, clock=clock)
    assert all(g.allow(f"m{i}") for i in range(3))
    assert not g.allow("m3")
    assert g.allow("halt!", level="CRITICAL")
    clock.t += 61
    assert g.allow("m4")


class _Recording(Notifier):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.sent = []

    async def _send_telegram(self, text):
        self.sent.append(("telegram", text))

    async def _send_email(self, subject, body):
        self.sent.append(("email", subject))


def test_notifier_routes_by_level_and_dedupes():
    n = _Recording({"telegram": {"enabled": True}, "email": {"enabled": True}})
    asyncio.run(n.send("entry TCS"))                                       # INFO: Telegram only
    asyncio.run(n.send("kill switch", level="CRITICAL"))                   # both
    asyncio.run(n.send("kill switch", level="CRITICAL"))                   # duplicate: dropped
    assert n.sent == [("telegram", "entry TCS"), ("telegram", "kill switch"),
                      ("email", "[CRITICAL] Trading Alert")]


def test_notifier_disabled_channels_send_nothing():
    n = _Recording({"telegram": {"enabled": False}, "email": {"enabled": True, "min_level": "CRITICAL"}})
    asyncio.run(n.send("warning", level="WARNING"))
    assert n.sent == []


def test_alert_cooldown(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from db.base import Base
    from db import models as m
    from signals.alerts import evaluate_alerts
    from tests.test_watchlists_and_alerts import _signal

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    stock = m.Stock(symbol="TCS", company_name="TCS")
    db.add(stock)
    db.flush()
    db.add(_signal(stock_id=stock.id, score=85.0))
    db.add(m.Alert(name="High score", condition={"score__gt": 80}, is_active=True))
    db.commit()

    class Rec:
        enabled = True
        def __init__(self): self.n = 0
        def send(self, text): self.n += 1

    rec = Rec()
    assert len(evaluate_alerts(db, notifier=rec, cooldown_minutes=240).triggers) == 1
    assert len(evaluate_alerts(db, notifier=rec, cooldown_minutes=240).triggers) == 0   # cooling down
    assert rec.n == 1
    assert len(evaluate_alerts(db, notifier=rec, cooldown_minutes=0).triggers) == 1     # cooldown off
