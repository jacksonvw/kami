"""Shared pytest fixtures.

`QT_QPA_PLATFORM=offscreen` is set before any Qt import so the suite runs
without a display server. As in Pepper, no pytest-qt: a raw QApplication
fixture is enough.

Every test gets its own config file, session folder, QSettings folder and
runtime folder, so a test run never touches the real ~/.config/kami,
~/.local/share/kami or a running Kami's socket.
"""

from __future__ import annotations

import os

# Must be set BEFORE importing PySide6.QtWidgets.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session", autouse=True)
def isolated_settings(tmp_path_factory):
    """Point QSettings at a scratch folder for the whole run."""
    QSettings.setPath(
        QSettings.NativeFormat, QSettings.UserScope,
        str(tmp_path_factory.mktemp("settings")),
    )


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch) -> Path:
    import kami.core.config as cfgmod
    cfg_path = tmp_path / "isolated-config" / "config.toml"
    monkeypatch.setattr(cfgmod, "_default_path", lambda: cfg_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return tmp_path


def make_kami(store_root: Path):
    """A Kami whose questions are answered from `kami.answers`."""
    from kami.core.config import AppConfig
    from kami.core.session import SessionStore
    from kami.ui.app import Kami

    k = Kami(config=AppConfig(), store=SessionStore(store_root))
    k.answers = {"save": "discard", "path": None}
    k.asked = []
    k.errors = []

    def ask_save(parent, tab):
        k.asked.append(tab.display_name())
        return k.answers["save"]

    k.ask_save = ask_save
    k.ask_save_path = lambda parent, tab: k.answers["path"]
    k.show_error = lambda parent, title, text: k.errors.append(text)
    return k


def dispose(k, qapp) -> None:
    k._quitting = True
    for win in list(k.windows):
        win.close()
    k.windows.clear()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


@pytest.fixture
def kami(qapp, tmp_path):
    k = make_kami(tmp_path / "session")
    yield k
    dispose(k, qapp)


def type_into(tab, text: str) -> None:
    """Type `text` at the cursor, the way a user would (so it counts as an edit)."""
    tab.editor.insertPlainText(text)
