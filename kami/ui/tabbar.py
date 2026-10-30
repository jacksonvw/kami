"""Kami's tab strip.

Dragging a tab along the strip reorders it, as in any tab bar. Dragging it
well clear of the strip turns into a real drag: let go over another Kami
window and the tab moves there; let go anywhere else (the desktop, or this
window's own page) and it gets a window of its own. Middle-click closes a
tab, and double-clicking the empty strip opens a new one, as in a browser.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QTabBar

TAB_MIME = "application/x-kami-tab"

# Quaver's tabs: square, all one height, with the accent colour under the
# current one rather than a change of size. Set on the bar itself, as Quaver
# does, so it holds at full opacity, where the window has no stylesheet.
# The width cap is Kami's own, for long file names.
TAB_STYLESHEET = """
    QTabBar::tab {
        padding: 6px 12px;
        margin: 0px;
        max-width: 220px;
    }
    QTabBar::tab:selected {
        border-bottom: 2px solid palette(highlight);
    }
    QTabBar::tab:!selected {
        border-bottom: 2px solid transparent;
    }
"""
TAB_PADDING_V = 6
TAB_ACCENT = 2


class GlyphButton(QAbstractButton):
    """A flat + or × in the tabs' text colour, with a square fill only
    while the pointer is on it. Drawn here rather than by the widget style,
    which boxes a tab's close button and colours it red."""

    PLUS = "+"
    CLOSE = "×"

    def __init__(self, glyph: str, side: int, parent=None, inset_right: int = 0) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._ink = QColor(255, 255, 255, 150)
        self._hot_ink = QColor(255, 255, 255, 232)
        self._fill = QColor(255, 255, 255, 30)
        self.setFocusPolicy(Qt.NoFocus)
        # Qt puts a tab's button flush against the tab's right edge; the
        # inset keeps the × as far in from that edge as the title is from
        # the left one.
        self.setContentsMargins(0, 0, inset_right, 0)
        self.setFixedSize(side + inset_right, side)

    def set_colors(self, ink: QColor, hot_ink: QColor, fill: QColor) -> None:
        self._ink, self._hot_ink, self._fill = ink, hot_ink, fill
        self.update()

    def sizeHint(self) -> QSize:
        return self.size()

    def enterEvent(self, ev) -> None:
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, ev) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.contentsRect())
        hot = self.underMouse() or self.isDown()
        if hot:
            painter.fillRect(box, self._fill)
        pen = QPen(self._hot_ink if hot else self._ink, 1.25)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        c = box.center()
        if self._glyph == self.CLOSE:
            r = box.width() * 0.18
            painter.drawLine(QPointF(c.x() - r, c.y() - r), QPointF(c.x() + r, c.y() + r))
            painter.drawLine(QPointF(c.x() - r, c.y() + r), QPointF(c.x() + r, c.y() - r))
        else:
            r = box.width() * 0.16
            painter.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
            painter.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        painter.end()


def tab_drag_data(tab_id: str) -> QMimeData:
    mime = QMimeData()
    # The pid keeps a tab from a different Kami (a Flatpak beside a
    # checkout, say) from being mistaken for one of ours.
    mime.setData(TAB_MIME, f"{os.getpid()}:{tab_id}".encode())
    return mime


def tab_id_from(mime) -> str | None:
    """The tab id in a Kami tab drag from this process, or None."""
    if mime is None or not mime.hasFormat(TAB_MIME):
        return None
    pid, _, tab_id = bytes(mime.data(TAB_MIME).data()).decode(errors="replace").partition(":")
    return tab_id if pid == str(os.getpid()) and tab_id else None


class TabBar(QTabBar):
    tab_dropped = Signal(str, int)    # a tab let go on this strip: id, insert index
    detach_requested = Signal(str)    # a tab let go away from every Kami window
    drag_finished = Signal()
    new_tab_requested = Signal()
    menu_requested = Signal(int, QPoint)  # tab index (-1 for none), global position

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tabs")
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setStyleSheet(TAB_STYLESHEET)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setElideMode(Qt.ElideRight)
        self.setUsesScrollButtons(True)
        self.setAcceptDrops(True)
        self._press_index = -1
        self._button_colors: tuple | None = None
        # True while a tab dragged from this strip is in the air. The
        # window it came from mustn't be deleted until the drag returns.
        self.dragging = False

    def minimumSizeHint(self) -> QSize:
        # With scroll buttons on, Qt asks for room for both of them plus
        # 75px even when one short tab is open, which left a gap between
        # the last tab and the + after it.
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.sizeHint().width()), hint.height())

    def glyph_side(self, scale: float) -> int:
        """A button's side, in proportion to the tabs' text."""
        return round(self.fontMetrics().height() * scale)

    def tab_height(self) -> int:
        """A tab's height under TAB_STYLESHEET: its text or its ×, the
        padding above and below, and the accent line."""
        content = max(self.fontMetrics().height(), self.glyph_side(1.1))
        return content + 2 * TAB_PADDING_V + TAB_ACCENT

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        button = GlyphButton(GlyphButton.CLOSE, self.glyph_side(1.1), self, inset_right=6)
        button.setToolTip("Close Tab (Ctrl+W)")
        if self._button_colors is not None:
            button.set_colors(*self._button_colors)
        button.clicked.connect(self._on_close_clicked)
        self.setTabButton(index, QTabBar.RightSide, button)

    def _on_close_clicked(self) -> None:
        button = self.sender()
        for i in range(self.count()):
            if self.tabButton(i, QTabBar.RightSide) is button:
                self.tabCloseRequested.emit(i)
                return

    def set_button_colors(self, ink: QColor, hot_ink: QColor, fill: QColor) -> None:
        self._button_colors = (ink, hot_ink, fill)
        for i in range(self.count()):
            button = self.tabButton(i, QTabBar.RightSide)
            if isinstance(button, GlyphButton):
                button.set_colors(ink, hot_ink, fill)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._press_index = self.tabAt(ev.position().toPoint())
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._press_index >= 0 and ev.buttons() & Qt.LeftButton:
            y = ev.position().y()
            if y < -self.height() or y > 2 * self.height():
                index, self._press_index = self._press_index, -1
                # End QTabBar's own reorder first. Left running, it keeps
                # the tab lifted and drops it wherever the cursor comes
                # back in.
                release = QMouseEvent(
                    QEvent.MouseButtonRelease, ev.position(), ev.globalPosition(),
                    Qt.LeftButton, Qt.NoButton, ev.modifiers(),
                )
                super().mouseReleaseEvent(release)
                self._drag_out(index)
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MiddleButton:
            index = self.tabAt(ev.position().toPoint())
            if index >= 0:
                self.tabCloseRequested.emit(index)
                return
        self._press_index = -1
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        if self.tabAt(ev.position().toPoint()) < 0:
            self.new_tab_requested.emit()
            return
        super().mouseDoubleClickEvent(ev)

    def contextMenuEvent(self, ev) -> None:
        self.menu_requested.emit(self.tabAt(ev.pos()), ev.globalPos())

    def _drag_out(self, index: int) -> None:
        tab_id = self.tabData(index)
        drag = QDrag(self)
        drag.setMimeData(tab_drag_data(tab_id))
        pixmap = self.grab(self.tabRect(index))
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        self.dragging = True
        try:
            result = drag.exec(Qt.MoveAction)
        finally:
            self.dragging = False
        if result == Qt.IgnoreAction:
            self.detach_requested.emit(tab_id)
        self.drag_finished.emit()

    # -- Tabs dragged in -------------------------------------------------

    def dragEnterEvent(self, ev) -> None:
        if tab_id_from(ev.mimeData()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:
        self.dragEnterEvent(ev)

    def dropEvent(self, ev) -> None:
        tab_id = tab_id_from(ev.mimeData())
        if not tab_id:
            ev.ignore()
            return
        ev.setDropAction(Qt.MoveAction)
        ev.accept()
        self.tab_dropped.emit(tab_id, self.insert_index_at(ev.position().toPoint()))

    def insert_index_at(self, pos: QPoint) -> int:
        """Where a tab let go at `pos` goes: before the tab whose middle it's left of."""
        for i in range(self.count()):
            if pos.x() < self.tabRect(i).center().x():
                return i
        return self.count()
