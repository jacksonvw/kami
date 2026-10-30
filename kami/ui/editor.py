"""The text area: a plain-text editor that zooms with Ctrl+wheel, opens
files dropped on it, and draws its text on whatever page the window
paints behind it.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QFont, QFontMetricsF, QPainter, QPalette, QPen, QRawFont
from PySide6.QtWidgets import QFrame, QPlainTextEdit

TAB_STOP_SPACES = 4


def local_files(mime) -> list[str]:
    """The local file paths in a drag's or clipboard's MIME data."""
    if mime is None or not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]


class Editor(QPlainTextEdit):
    files_dropped = Signal(list)
    zoom_step = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("editor")
        self.setFrameShape(QFrame.NoFrame)
        # A view, as Quaver's lists are: the window's stylesheet gives it a
        # faint shade over the window's colour.
        # Notepad's room between the menu bar and the text, and the 12px the
        # tabs' titles and the menu bar's names start at.
        self.document().setDocumentMargin(12)
        # Window actions offered below Cut, Copy and Paste, such as Show
        # Menu Bar for when the menu bar is hidden.
        self.extra_context_actions: list[QAction] = []
        self._blank_fonts: dict[tuple[str, str], bool] = {}

    def apply_font(self, font: QFont) -> None:
        self.setFont(font)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * TAB_STOP_SPACES)

    # A character no installed font has is drawn with the editor font's
    # "missing character" glyph. Most fonts make that a box, but Noto Sans
    # Mono, Fedora KDE's fixed-width font, leaves it blank, so the text took
    # up room and showed nothing. Kami draws the box itself for such fonts.

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        boxes = self.missing_character_boxes(ev.rect())
        if boxes:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(self.palette().color(QPalette.Text), 1))
            for box in boxes:
                painter.drawRect(box.toRect())
            painter.end()

    def missing_character_boxes(self, area: QRect) -> list[QRectF]:
        """Boxes for the characters in `area` that would otherwise be blank."""
        boxes = []
        offset = self.contentOffset()
        block = self.firstVisibleBlock()
        while block.isValid():
            origin = self.blockBoundingGeometry(block).translated(offset).topLeft()
            if origin.y() > area.bottom():
                break
            if block.isVisible() and not block.text().isascii():
                # An explicit range: without one, the editor's layouts,
                # which don't keep their glyphs cached, return no runs.
                for run in block.layout().glyphRuns(0, block.length() - 1):
                    raw = run.rawFont()
                    if not self._missing_glyph_is_blank(raw):
                        continue
                    advance = raw.advancesForGlyphIndexes([0])[0].x()
                    height = raw.capHeight() or raw.ascent() * 0.7
                    if advance < 1:
                        continue
                    for glyph, pos in zip(run.glyphIndexes(), run.positions()):
                        if glyph == 0:
                            left = origin.x() + pos.x() + advance * 0.15
                            boxes.append(QRectF(left, origin.y() + pos.y() - height, advance * 0.7, height))
            block = block.next()
        return boxes

    def _missing_glyph_is_blank(self, raw: QRawFont) -> bool:
        key = (raw.familyName(), raw.styleName())
        if key not in self._blank_fonts:
            self._blank_fonts[key] = raw.pathForGlyph(0).isEmpty()
        return self._blank_fonts[key]

    def wheelEvent(self, ev) -> None:
        if ev.modifiers() & Qt.ControlModifier:
            delta = ev.angleDelta().y()
            if delta:
                self.zoom_step.emit(1 if delta > 0 else -1)
            ev.accept()
            return
        super().wheelEvent(ev)

    # Dropped files open as tabs rather than pasting their paths in. Paste
    # is left alone, so a file copied in Dolphin still pastes as its path.

    def dragEnterEvent(self, ev) -> None:
        if local_files(ev.mimeData()):
            ev.acceptProposedAction()
            return
        super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev) -> None:
        if local_files(ev.mimeData()):
            ev.acceptProposedAction()
            return
        super().dragMoveEvent(ev)

    def dropEvent(self, ev) -> None:
        files = local_files(ev.mimeData())
        if files:
            ev.acceptProposedAction()
            self.files_dropped.emit(files)
            return
        super().dropEvent(ev)

    def contextMenuEvent(self, ev) -> None:
        menu = self.createStandardContextMenu(ev.pos())
        extras = [a for a in self.extra_context_actions if a.isVisible()]
        if extras:
            menu.addSeparator()
            menu.addActions(extras)
        menu.exec(ev.globalPos())
        menu.deleteLater()
