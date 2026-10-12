"""Dashboard → bot control file (utils/bot_control.py)."""
from __future__ import annotations
import os

import pytest

from utils.bot_control import ControlReader, read_control, write_control


def test_missing_file_reads_empty(tmp_path):
    assert read_control(tmp_path / "none.json") == {}
    assert ControlReader(tmp_path / "none.json").poll() == {}


def test_actions(tmp_path):
    path = tmp_path / "ctl.json"
    assert write_control("pause", path)["paused"] is True
    state = write_control("flatten", path)
    assert state["paused"] is True and len(state["flatten_id"]) == 8
    first_flatten = state["flatten_id"]
    state = write_control("resume", path)
    assert state["paused"] is False and state["resume_id"]
    assert state["flatten_id"] == first_flatten           # untouched
    assert write_control("flatten", path)["flatten_id"] != first_flatten
    assert read_control(path)["paused"] is False
    assert not (tmp_path / "ctl.json.tmp").exists()


def test_unknown_action(tmp_path):
    with pytest.raises(ValueError):
        write_control("explode", tmp_path / "ctl.json")


def test_reader_rereads_only_on_change(tmp_path):
    path = tmp_path / "ctl.json"
    write_control("pause", path)
    reader = ControlReader(path)
    assert reader.poll()["paused"] is True
    path.write_text('{"paused": false}')
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert reader.poll()["paused"] is False
    path.unlink()
    assert reader.poll()["paused"] is False                 # keeps last known state
