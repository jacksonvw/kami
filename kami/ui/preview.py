"""The Markdown preview a tab flips to with Ctrl+Shift+V.

A read-only QTextBrowser showing the document `kami.ui.markdown` renders.
Links to web pages open in the browser, and links to other text or
Markdown files open as Kami tabs.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPalette
from PySide6.QtWidgets import QFrame, QTextBrowser

from kami.ui.markdown import PreviewStyle, render_markdown

TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".text")


class Preview(QTextBrowser):
    open_file_requested = Signal(str)
    zoom_step = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("preview")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor)
        self._quotes: list = []
        self._bar = QColor()

    def render(self, text: str, style: PreviewStyle, base_dir: str | None) -> None:
        scroll = self.verticalScrollBar().value()
        # QTextDocument draws rules (---, and under h1 and h2) in the
        # palette's Dark colour.
        pal = self.palette()
        pal.setColor(QPalette.Dark, style.rule)
        self.setPalette(pal)
        self._bar = style.rule
        self._quotes = render_markdown(
            self.document(), text, style, base_dir,
            max_image_width=max(0, self.viewport().width() - 48),
        )
        self.verticalScrollBar().setValue(scroll)

    def wheelEvent(self, ev) -> None:
        # The tab's zoom, not QTextBrowser's own, so the status bar's
        # percentage and the editor stay in step with the preview.
        if ev.modifiers() & Qt.ControlModifier:
            delta = ev.angleDelta().y()
            if delta:
                self.zoom_step.emit(1 if delta > 0 else -1)
            ev.accept()
            return
        super().wheelEvent(ev)

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        if not self._quotes:
            return
        # QTextDocument can't draw a border down one side of a paragraph,
        # so the bars beside quotes are painted here, in the margin the
        # renderer left for them.
        layout = self.document().documentLayout()
        dx = -self.horizontalScrollBar().value()
        dy = -self.verticalScrollBar().value()
        painter = QPainter(self.viewport())
        for block, level in self._quotes:
            if not block.isValid():
                continue
            rect = layout.blockBoundingRect(block).translated(dx, dy)
            step = block.blockFormat().leftMargin() / level
            for i in range(level):
                x = rect.left() + i * step + step * 0.25
                painter.fillRect(QRectF(x, rect.top(), 3, rect.height()), self._bar)
        painter.end()

    def _on_anchor(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if not url.path() and url.hasFragment():
            self.scrollToAnchor(url.fragment())
            return
        resolved = self.document().baseUrl().resolved(url)
        if not resolved.isLocalFile():
            QDesktopServices.openUrl(resolved)
            return
        path = os.path.normpath(resolved.toLocalFile())
        if path.lower().endswith(TEXT_SUFFIXES) and os.path.isfile(path):
            self.open_file_requested.emit(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
