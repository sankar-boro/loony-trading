"""
Operator control channel between the dashboard and the trading bot.

The dashboard and the bot are separate processes, so commands travel through a
small JSON file, data/bot_control.json:

    {"paused": false, "flatten_id": "a1b2c3", "resume_id": "", "updated_at": 1791545520.0}

- paused      — the bot takes no new entries while true
- flatten_id  — a new value asks the bot to close every open position once
- resume_id   — a new value clears a kill-switch / profit-lock halt

The bot polls the file (cheaply, by modification time) and records the ids it
has acted on in its state file, so each request is executed exactly once.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

CONTROL_FILE = Path(__file__).resolve().parent.parent / "data" / "bot_control.json"


def read_control(path: Path = CONTROL_FILE) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_control(action: str, path: Path = CONTROL_FILE) -> dict:
    """Apply an operator action ("pause", "resume", "flatten") and return the
    new control state. Written atomically."""
    state = read_control(path)
    if action == "pause":
        state["paused"] = True
    elif action == "resume":
        state["paused"] = False
        state["resume_id"] = uuid.uuid4().hex[:8]
    elif action == "flatten":
        state["flatten_id"] = uuid.uuid4().hex[:8]
    else:
        raise ValueError(f"unknown action: {action}")
    state["updated_at"] = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)
    return state


class ControlReader:
    """Bot side: re-reads the file only when it changes."""

    def __init__(self, path: Path = CONTROL_FILE):
        self.path = path
        self._mtime = None
        self._state: dict = {}

    def poll(self) -> dict:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return self._state
        if mtime != self._mtime:
            self._mtime = mtime
            self._state = read_control(self.path)
        return self._state
