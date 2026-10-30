from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QFont

from kami.core.session import TabState
from kami.tests.conftest import type_into
from kami.ui.document import UNTITLED, DocumentTab
from kami.ui.markdown import PreviewStyle


@pytest.fixture
def tab(qapp):
    t = DocumentTab()
    style = PreviewStyle(
        QFont(), QFont("Monospace"), QColor("white"), QColor("gray"), QColor("gray"),
        QColor(1, 2, 3), QColor("blue"), True,
    )
    t.apply_style(QFont("Monospace"), style, True)
    yield t
    t.deleteLater()


@pytest.mark.parametrize("text, title", [
    ("", UNTITLED),
    ("\n\n   \n", UNTITLED),
    ("\n\n# API keys for staging\nsk-live-123", "API keys for staging"),
    ("- [ ] Buy milk\n", "Buy milk"),
    ("> quoted   words  here", "quoted words here"),
    ("A very long first line that goes on and on", "A very long first line that g…"),
])
def test_untitled_tabs_are_named_by_their_first_line(tab, text, title):
    tab.editor.setPlainText(text)
    assert tab.display_name() == title


def test_needs_saving(tab):
    assert not tab.needs_saving() and tab.is_pristine()
    type_into(tab, "scratch")
    assert tab.needs_saving() and not tab.is_pristine()
    assert tab.tab_text().endswith("•")
    tab.editor.selectAll()
    tab.editor.textCursor().removeSelectedText()
    # An emptied untitled tab has nothing worth asking about.
    assert not tab.needs_saving()


def test_load_and_save_keep_windows_line_endings(tab, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"a\r\nb\r\n")
    tab.load(str(p))
    assert tab.display_name() == "notes.txt" and not tab.needs_saving()
    type_into(tab, "x")
    assert tab.needs_saving()
    tab.save_as(str(p))
    assert p.read_bytes() == b"xa\r\nb\r\n"
    assert not tab.needs_saving()


def test_unsaved_text_survives_a_session(tab):
    type_into(tab, "keys and notes")
    tab.set_zoom(130)
    state = tab.state()
    assert state.modified and state.path is None and state.zoom == 130

    again = DocumentTab(state.id)
    again.restore(state, tab.text())
    assert again.text() == "keys and notes"
    assert again.needs_saving()
    assert again.zoom == 130
    again.deleteLater()


def test_restoring_a_vanished_file_raises(qapp, tmp_path):
    t = DocumentTab()
    with pytest.raises(OSError):
        t.restore(TabState(id=t.id, path=str(tmp_path / "gone.txt")), None)
    t.deleteLater()


def test_zoom_is_bounded(tab):
    tab.set_zoom(1000)
    assert tab.zoom == 500
    tab.step_zoom(-100)
    assert tab.zoom == 10


def test_preview_toggles(tab):
    tab.editor.setPlainText("# Hello\n\nworld")
    tab.toggle_preview()
    assert tab.is_previewing()
    assert "Hello" in tab.currentWidget().toPlainText()
    tab.toggle_preview()
    assert not tab.is_previewing()
    assert tab.currentWidget() is tab.editor


def test_status_figures(tab):
    tab.editor.setPlainText("ab\ncd")
    assert tab.char_count() == 5
    cur = tab.editor.textCursor()
    cur.setPosition(4)
    tab.editor.setTextCursor(cur)
    assert tab.cursor_position() == (2, 2)
