"""Broker reconciliation (docs/appendix/status.md §3): the bot's book is checked
against Upstox positions + holdings in live mode."""
from __future__ import annotations
import asyncio
from types import SimpleNamespace

from execution_engine.reconcile import broker_net_quantities, compare_books
from main import UpstoxTradingBot
from risk_manager.risk_manager import RiskManager
from strategies.base import Signal, SignalType

REL = "NSE_EQ|INE002A01018"
TCS = "NSE_EQ|INE467B01029"


# ── Pure comparison rules ────────────────────────────────────────────────────

def test_broker_quantities_split_today_and_total():
    total, today = broker_net_quantities(
        positions=[{"instrument_token": REL, "quantity": 10},
                   {"instrument_token": TCS, "quantity": -5}],
        holdings=[{"instrument_token": REL, "quantity": 20, "t1_quantity": 3}],
    )
    assert today == {REL: 10, TCS: -5}
    assert total == {REL: 33, TCS: -5}


def test_matching_books_have_no_mismatch():
    assert compare_books({REL: 10}, {REL: 10}, {REL: 10}) == []


def test_broker_holding_more_is_not_a_mismatch():
    # e.g. the owner's own long-term shares in the same stock
    assert compare_books({REL: 10}, {REL: 50}, {}) == []


def test_missing_long_is_reported_with_cover():
    [m] = compare_books({REL: 10}, {REL: 4}, {REL: 4})
    assert m.kind == "missing_at_broker" and m.broker_cover == 4


def test_missing_short_is_reported():
    [m] = compare_books({REL: -10}, {}, {})
    assert m.kind == "missing_at_broker" and m.broker_cover == 0


def test_untracked_only_counts_todays_positions():
    assert compare_books({}, {REL: 20}, {}) == []        # holdings only → ignored
    [m] = compare_books({}, {TCS: -5}, {TCS: -5})
    assert m.kind == "untracked_at_broker" and m.broker_qty == -5


# ── Bot behaviour ────────────────────────────────────────────────────────────

class _Executor:
    def __init__(self, broker=None, error=None):
        self.broker = broker or ({}, {})
        self.error = error

    def _resolve_key(self, symbol):
        return {"RELIANCE": REL, "TCS": TCS}.get(symbol)

    async def fetch_broker_quantities(self):
        if self.error:
            raise self.error
        return self.broker


class _Notifier:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


class _FakeBot:
    _reconcile = UpstoxTradingBot._reconcile
    _shrink_to_broker = UpstoxTradingBot._shrink_to_broker

    def __init__(self, executor):
        self.executor = executor
        self.risk_manager = RiskManager({"risk": {}}, 500_000)
        self.notifier = _Notifier()
        self._last_price = {"RELIANCE": 100.0}
        self._recon_strikes = {}
        self._recon_alerted = set()


def _buy(bot, symbol, size):
    sig = Signal(symbol=symbol, signal_type=SignalType.BUY, confidence=0.9, price=100.0,
                 stop_loss=98.0, take_profit=104.0, strategy="test")
    return bot.risk_manager.open_position(sig, size)


def test_startup_drops_position_broker_does_not_have():
    bot = _FakeBot(_Executor(broker=({}, {})))
    _buy(bot, "RELIANCE", 10)

    asyncio.run(bot._reconcile(at_startup=True))

    assert bot.risk_manager.open_count == 0
    assert any("RELIANCE" in m for m in bot.notifier.sent)


def test_in_session_needs_two_checks_before_correcting():
    bot = _FakeBot(_Executor(broker=({}, {})))
    _buy(bot, "RELIANCE", 10)

    asyncio.run(bot._reconcile())
    assert bot.risk_manager.open_count == 1      # first strike: warn only
    asyncio.run(bot._reconcile())
    assert bot.risk_manager.open_count == 0      # still missing: corrected


def test_strike_clears_once_broker_catches_up():
    ex = _Executor(broker=({}, {}))
    bot = _FakeBot(ex)
    _buy(bot, "RELIANCE", 10)

    asyncio.run(bot._reconcile())                # order still filling
    ex.broker = ({REL: 10}, {REL: 10})
    asyncio.run(bot._reconcile())                # filled now
    ex.broker = ({}, {})
    asyncio.run(bot._reconcile())                # a fresh first strike, not a second
    assert bot.risk_manager.open_count == 1


def test_partial_cover_shrinks_newest_position_first():
    bot = _FakeBot(_Executor(broker=({REL: 12}, {REL: 12})))
    first = _buy(bot, "RELIANCE", 10)
    second = _buy(bot, "RELIANCE", 10)

    asyncio.run(bot._reconcile(at_startup=True))

    assert bot.risk_manager.positions["RELIANCE"] == [first, second]
    assert first.size == 10 and second.size == 2


def test_api_error_never_touches_the_book():
    bot = _FakeBot(_Executor(error=RuntimeError("HTTP 503")))
    _buy(bot, "RELIANCE", 10)

    asyncio.run(bot._reconcile(at_startup=True))

    assert bot.risk_manager.open_count == 1
    assert bot.notifier.sent == []


def test_untracked_position_alerted_once_per_day():
    bot = _FakeBot(_Executor(broker=({TCS: 5}, {TCS: 5})))

    asyncio.run(bot._reconcile())
    asyncio.run(bot._reconcile())

    assert len(bot.notifier.sent) == 1
    assert bot.risk_manager.open_count == 0      # alert only, nothing adopted
