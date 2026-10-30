from __future__ import annotations

import json
import stat
import uuid

import pytest

from kami.core.session import SessionStore, TabState, WindowState


def _id() -> str:
    return uuid.uuid4().hex


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_round_trip(tmp_path):
    store = SessionStore(tmp_path / "s")
    windows = [WindowState(
        tabs=[
            TabState(id=_id(), path="/tmp/a.txt"),
            TabState(id=_id(), modified=True, eol="\r\n", zoom=150, preview=True, cursor=4),
        ],
        current=1,
        geometry="AdnQywADAAA=",
    )]
    store.save(windows)
    assert store.load() == windows


def test_everything_is_private(tmp_path):
    store = SessionStore(tmp_path / "s")
    tab_id = _id()
    store.save([])
    store.write_text(tab_id, "sk-live-secret")
    assert _mode(store.root) == 0o700
    assert _mode(store.root / "tabs") == 0o700
    assert _mode(store.root / "session.json") == 0o600
    assert _mode(store.root / "tabs" / f"{tab_id}.txt") == 0o600


def test_unsaved_text(tmp_path):
    store = SessionStore(tmp_path / "s")
    tab_id = _id()
    assert not store.has_text(tab_id)
    store.write_text(tab_id, "keys\n")
    assert store.has_text(tab_id)
    assert store.read_text(tab_id) == "keys\n"
    store.discard_text(tab_id)
    assert store.read_text(tab_id) is None


def test_prune_and_clear(tmp_path):
    store = SessionStore(tmp_path / "s")
    keep, drop = _id(), _id()
    store.write_text(keep, "a")
    store.write_text(drop, "b")
    store.save([WindowState(tabs=[TabState(id=keep, modified=True)])])
    store.prune({keep})
    assert store.has_text(keep) and not store.has_text(drop)
    store.clear()
    assert not store.has_text(keep)
    assert store.load() == []


def test_ids_that_could_escape_the_folder_are_refused(tmp_path):
    store = SessionStore(tmp_path / "s")
    store.save([])
    (store.root / "session.json").write_text(json.dumps({"windows": [{"tabs": [
        {"id": "../../outside", "modified": True},
        {"id": _id(), "path": "relative.txt"},
    ]}]}))
    [window] = store.load()
    assert len(window.tabs) == 1
    assert window.tabs[0].path is None  # relative paths are dropped too
    with pytest.raises(ValueError):
        store.write_text("../escape", "x")


def test_a_corrupt_session_is_ignored(tmp_path):
    store = SessionStore(tmp_path / "s")
    store.save([])
    (store.root / "session.json").write_text("{nope")
    assert store.load() == []
