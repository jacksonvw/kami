"""One tab: a file or an untitled page, its editor and its preview."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import replace

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QStackedWidget

from kami.core.session import TabState
from kami.core.textfile import TextFormat, read_file, write_file
from kami.ui.editor import Editor
from kami.ui.markdown import PreviewStyle
from kami.ui.preview import Preview

UNTITLED = "Untitled"
TITLE_CHARS = 30
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 10, 500, 10

# Markdown that shouldn't lead a tab's title: heading marks, quote and
# list markers, and task boxes.
_TITLE_NOISE = re.compile(r"^(?:[#>\s]+|[-*+]\s+(?:\[[ xX]\]\s+)?)+")


def untitled_name(doc) -> str:
    """An unsaved tab's title: the start of its first line of text.

    Windows 11 Notepad does the same, so a row of scratch tabs reads as
    "API keys", "Call list", "Draft reply" rather than Untitled 1, 2 and 3.
    """
    block = doc.firstBlock()
    for _ in range(50):
        if not block.isValid():
            break
        line = _TITLE_NOISE.sub("", block.text()).strip()
        if line:
            line = " ".join(line.split())
            if len(line) > TITLE_CHARS:
                line = line[: TITLE_CHARS - 1].rstrip() + "…"
            return line
        block = block.next()
    return UNTITLED


class DocumentTab(QStackedWidget):
    title_changed = Signal()
    status_changed = Signal()
    content_changed = Signal()
    files_dropped = Signal(list)
    open_file_requested = Signal(str)

    def __init__(self, tab_id: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.id = tab_id or uuid.uuid4().hex
        self.path: str | None = None
        self.fmt = TextFormat()
        self.zoom = 100
        self._base_font = QFont()
        self._style: PreviewStyle | None = None
        self._title = UNTITLED
        self._pending_scroll: int | None = None
        self._pending_preview = False

        self.editor = Editor(self)
        self.addWidget(self.editor)
        self._preview: Preview | None = None

        doc = self.editor.document()
        doc.modificationChanged.connect(self.title_changed)
        doc.contentsChanged.connect(self._on_contents_changed)
        self.editor.cursorPositionChanged.connect(self.status_changed)
        self.editor.selectionChanged.connect(self.status_changed)
        self.editor.files_dropped.connect(self.files_dropped)
        self.editor.zoom_step.connect(self.step_zoom)

    # -- Names ---------------------------------------------------------

    def display_name(self) -> str:
        return os.path.basename(self.path) if self.path else self._title

    def tab_text(self) -> str:
        return f"{self.display_name()} •" if self.needs_saving() else self.display_name()

    def is_modified(self) -> bool:
        return self.editor.document().isModified()

    def needs_saving(self) -> bool:
        """True if closing this tab for good would lose something."""
        doc = self.editor.document()
        return doc.isModified() and not (self.path is None and doc.isEmpty())

    def is_pristine(self) -> bool:
        """An empty untitled tab, which a file being opened may replace."""
        return self.path is None and self.editor.document().isEmpty()

    def _on_contents_changed(self) -> None:
        if self.path is None:
            title = untitled_name(self.editor.document())
            if title != self._title:
                self._title = title
                self.title_changed.emit()
        self.content_changed.emit()
        self.status_changed.emit()

    # -- Files ---------------------------------------------------------

    def text(self) -> str:
        return self.editor.toPlainText()

    def load(self, path: str) -> None:
        """Read `path` into this tab. Raises OSError or FileTooLarge."""
        text, fmt = read_file(path)
        self.editor.setPlainText(text)
        self.path = os.path.abspath(path)
        self.fmt = fmt
        self.editor.document().setModified(False)
        self.title_changed.emit()
        self.status_changed.emit()

    def save_as(self, path: str) -> None:
        """Write this tab to `path` and make that its file. Raises OSError."""
        self.fmt = write_file(path, self.text(), self.fmt)
        self.path = os.path.abspath(path)
        self.editor.document().setModified(False)
        self.title_changed.emit()
        self.status_changed.emit()

    def set_new_file(self, path: str) -> None:
        """Make this empty tab stand for `path`, a file not created yet.

        `kami todo.txt` for a todo.txt that doesn't exist opens it this
        way, and the first save creates it.
        """
        self.path = os.path.abspath(path)
        self.title_changed.emit()

    # -- Preview -------------------------------------------------------

    def is_previewing(self) -> bool:
        return self._preview is not None and self.currentWidget() is self._preview

    def set_preview(self, on: bool) -> None:
        if on:
            if self._preview is None:
                self._preview = Preview(self)
                self._preview.open_file_requested.connect(self.open_file_requested)
                self._preview.zoom_step.connect(self.step_zoom)
                self.addWidget(self._preview)
            self.setCurrentWidget(self._preview)
            self._render_preview()
        else:
            self.setCurrentWidget(self.editor)
        self.focus()
        self.status_changed.emit()

    def toggle_preview(self) -> None:
        self.set_preview(not self.is_previewing())

    def focus(self) -> None:
        self.currentWidget().setFocus()

    def _render_preview(self) -> None:
        if self._preview is None or self._style is None:
            return
        scale = self.zoom / 100
        body, code = QFont(self._style.body_font), QFont(self._style.code_font)
        for f in (body, code):
            f.setPointSizeF(max(1.0, (f.pointSizeF() if f.pointSizeF() > 0 else 10.0) * scale))
        style = replace(self._style, body_font=body, code_font=code)
        base_dir = os.path.dirname(self.path) if self.path else None
        self._preview.render(self.text(), style, base_dir)

    # -- Look ----------------------------------------------------------

    def apply_style(self, font: QFont, style: PreviewStyle, word_wrap: bool) -> None:
        self._base_font = QFont(font)
        self._style = style
        self.editor.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if word_wrap else QPlainTextEdit.NoWrap
        )
        self._apply_zoom()
        if self._pending_preview:
            self._pending_preview = False
            self.set_preview(True)
        elif self.is_previewing():
            self._render_preview()

    def set_zoom(self, percent: int) -> None:
        percent = max(ZOOM_MIN, min(ZOOM_MAX, int(percent)))
        if percent != self.zoom:
            self.zoom = percent
            self._apply_zoom()
            if self.is_previewing():
                self._render_preview()
            self.status_changed.emit()

    def step_zoom(self, steps: int) -> None:
        self.set_zoom(self.zoom + ZOOM_STEP * steps)

    def _apply_zoom(self) -> None:
        font = QFont(self._base_font)
        size = self._base_font.pointSizeF()
        font.setPointSizeF(max(1.0, (size if size > 0 else 10.0) * self.zoom / 100))
        self.editor.apply_font(font)

    # -- Status bar ----------------------------------------------------

    def cursor_position(self) -> tuple[int, int]:
        cur = self.editor.textCursor()
        return cur.blockNumber() + 1, cur.positionInBlock() + 1

    def char_count(self) -> int:
        # characterCount() counts each line break as one character, as the
        # saved file (with LF endings) will, plus one final paragraph mark.
        return max(0, self.editor.document().characterCount() - 1)

    def selected_count(self) -> int:
        return len(self.editor.textCursor().selectedText())

    # -- Session -------------------------------------------------------

    def state(self) -> TabState:
        return TabState(
            id=self.id,
            path=self.path,
            modified=self.needs_saving(),
            encoding=self.fmt.encoding,
            bom=self.fmt.bom,
            eol=self.fmt.eol,
            cursor=self.editor.textCursor().position(),
            scroll=self.editor.verticalScrollBar().value(),
            zoom=self.zoom,
            preview=self.is_previewing() or self._pending_preview,
        )

    def restore(self, state: TabState, text: str | None) -> None:
        """Bring back a tab from the session.

        `text` is the unsaved text kept for a modified tab, if any.
        Raises OSError (or FileTooLarge) when a saved file can't be read.
        """
        if state.modified and text is not None:
            self.editor.setPlainText(text)
            self.path = state.path
            self.fmt = TextFormat(encoding=state.encoding, bom=state.bom, eol=state.eol)
            self.editor.document().setModified(True)
        elif state.path:
            self.load(state.path)
        else:
            raise ValueError("an untitled tab with no text")
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, state.zoom))
        cur = self.editor.textCursor()
        cur.setPosition(min(state.cursor, self.char_count()))
        self.editor.setTextCursor(cur)
        # Neither can happen yet: the scroll range only exists once the
        # editor is laid out, and the preview needs the style.
        self._pending_scroll = state.scroll
        self._pending_preview = state.preview
        self.title_changed.emit()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._pending_scroll is not None:
            value, self._pending_scroll = self._pending_scroll, None
            bar = self.editor.verticalScrollBar()
            QTimer.singleShot(0, lambda: bar.setValue(value))
