"""The editor's boxes for characters no installed font has."""

from __future__ import annotations

from PySide6.QtGui import QTextCursor

from kami.ui.editor import Editor


def laid_out(text: str, monkeypatch) -> Editor:
    # Treat every font's missing-character glyph as blank, as Noto Sans
    # Mono's is, whichever font the test machine falls back to.
    monkeypatch.setattr(Editor, "_missing_glyph_is_blank", lambda self, raw: True)
    ed = Editor()
    ed.setPlainText(text)
    ed.resize(400, 100)
    ed.grab()  # lays the text out
    return ed


def test_a_character_no_font_has_gets_a_box(qapp, monkeypatch):
    # U+0378 is unassigned, so no font has a glyph for it.
    ed = laid_out("a͸b", monkeypatch)
    [box] = ed.missing_character_boxes(ed.viewport().rect())
    cur = QTextCursor(ed.document())
    cur.setPosition(1)
    left = ed.cursorRect(cur).left()
    cur.setPosition(2)
    right = ed.cursorRect(cur).left()
    assert left <= box.center().x() <= right
    ed.deleteLater()


def test_characters_a_font_has_get_no_box(qapp, monkeypatch):
    ed = laid_out("plain, and accented: déjà vu", monkeypatch)
    assert ed.missing_character_boxes(ed.viewport().rect()) == []
    ed.deleteLater()
