"""main.py's bot saves open positions to data/live_positions.json and
restores them after a crash (docs/appendix/status.md §3). Runs the real
UpstoxTradingBot methods against a lightweight stand-in, like
test_bot_position_safety.py."""
from __future__ import annotations
import json
from datetime import datetime
from types import SimpleNamespace

import utils.timeutils as timeutils
from main import UpstoxTradingBot
from risk_manager.risk_manager import RiskManager
from strategies.base import Signal, SignalType


class _FakeBot:
    _save_state = UpstoxTradingBot._save_state
    _restore_state = UpstoxTradingBot._restore_state
    _init_intraday = UpstoxTradingBot._init_intraday

    def __init__(self, state_file, mode: str = "live", product: str = "CNC"):
        self.mode = mode
        self.risk_manager = RiskManager({"risk": {}}, 500_000)
        self.executor = SimpleNamespace(_default_product=SimpleNamespace(value=product))
        self._last_price = {}
        self._state_file = state_file
        self._state_saved_version = -1
        self._state_saved_at = 0.0
        self._init_intraday({}, mode, data_dir=state_file.parent)


def _buy(symbol: str, price: float = 100.0) -> Signal:
    return Signal(symbol=symbol, signal_type=SignalType.BUY, confidence=0.9, price=price,
                  stop_loss=price - 2, take_profit=price + 4, strategy="test")


def _on_day(monkeypatch, day: int):
    monkeypatch.setattr(timeutils, "now_ist",
                        lambda: datetime(2026, 10, day, 11, 0, tzinfo=timeutils.IST))


def test_save_writes_dashboard_compatible_file(tmp_path, monkeypatch):
    _on_day(monkeypatch, 9)
    bot = _FakeBot(tmp_path / "state.json")
    bot.risk_manager.open_position(_buy("RELIANCE"), 10)
    bot._last_price["RELIANCE"] = 105.0

    bot._save_state()

    state = json.loads((tmp_path / "state.json").read_text())
    assert state["source"] == "main" and state["mode"] == "live"
    [pos] = state["positions"]
    assert pos["symbol"] == "RELIANCE" and pos["size"] == 10
    assert pos["current_price"] == 105.0 and pos["unrealised_pnl"] == 50.0
    assert pos["product"] == "CNC"
    assert "saved_at" in state and "cash" in state


def test_save_is_skipped_when_nothing_changed(tmp_path, monkeypatch):
    _on_day(monkeypatch, 9)
    bot = _FakeBot(tmp_path / "state.json")
    bot._save_state()
    first = bot._state_saved_at
    bot._save_state()                      # no change, heartbeat not due
    assert bot._state_saved_at == first
    bot.risk_manager.open_position(_buy("TCS"), 5)
    bot._save_state()                      # position opened → written
    assert len(json.loads((tmp_path / "state.json").read_text())["positions"]) == 1


def test_restore_after_crash(tmp_path, monkeypatch):
    _on_day(monkeypatch, 9)
    before = _FakeBot(tmp_path / "state.json")
    pos = before.risk_manager.open_position(_buy("RELIANCE"), 10)
    pos.stop_loss = 99.5                   # trailing stop moved before the crash
    before.risk_manager.daily_pnl = -1200.0
    before._save_state()

    after = _FakeBot(tmp_path / "state.json")
    assert after._restore_state() == 1

    [restored] = after.risk_manager.positions["RELIANCE"]
    assert restored.size == 10 and restored.stop_loss == 99.5
    assert after.risk_manager.daily_pnl == -1200.0   # same session keeps the day's P&L


def test_previous_day_intraday_positions_are_dropped(tmp_path, monkeypatch):
    _on_day(monkeypatch, 8)
    before = _FakeBot(tmp_path / "state.json", product="MIS")
    before.risk_manager.open_position(_buy("RELIANCE"), 10)
    before.risk_manager.daily_pnl = -500.0
    before._save_state()

    _on_day(monkeypatch, 9)
    after = _FakeBot(tmp_path / "state.json", product="MIS")
    assert after._restore_state() == 0
    assert after.risk_manager.daily_pnl == 0.0       # new session starts fresh


def test_previous_day_delivery_positions_are_kept(tmp_path, monkeypatch):
    _on_day(monkeypatch, 8)
    before = _FakeBot(tmp_path / "state.json", product="CNC")
    before.risk_manager.open_position(_buy("RELIANCE"), 10)
    before._save_state()

    _on_day(monkeypatch, 9)
    after = _FakeBot(tmp_path / "state.json", product="CNC")
    assert after._restore_state() == 1


def test_paper_state_never_restored_into_live(tmp_path, monkeypatch):
    _on_day(monkeypatch, 9)
    paper = _FakeBot(tmp_path / "state.json", mode="paper")
    paper.risk_manager.open_position(_buy("RELIANCE"), 10)
    paper._save_state()

    live = _FakeBot(tmp_path / "state.json", mode="live")
    assert live._restore_state() == 0
    assert live.risk_manager.open_count == 0


def test_paper_trade_script_file_is_ignored(tmp_path, monkeypatch):
    _on_day(monkeypatch, 9)
    (tmp_path / "state.json").write_text(json.dumps({
        "saved_at": 0, "initial_capital": 500000, "cash": 1,
        "positions": [{"symbol": "RELIANCE", "direction": 1, "size": 1}],
    }))
    bot = _FakeBot(tmp_path / "state.json")
    assert bot._restore_state() == 0
