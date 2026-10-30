from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint
from PySide6.QtWidgets import QTabBar

from kami.ui.tabbar import TAB_MIME, GlyphButton, TabBar, tab_drag_data, tab_id_from


def test_drag_data_round_trip(qapp):
    assert tab_id_from(tab_drag_data("abc123")) == "abc123"


def test_tabs_from_another_process_are_ignored(qapp):
    mime = QMimeData()
    mime.setData(TAB_MIME, b"1:abc123")  # pid 1 is never us
    assert tab_id_from(mime) is None
    assert tab_id_from(QMimeData()) is None


def test_insert_index(qapp):
    bar = TabBar()
    for name in ("one", "two", "three"):
        bar.addTab(name)
    bar.resize(bar.sizeHint())
    first, last = bar.tabRect(0), bar.tabRect(2)
    assert bar.insert_index_at(QPoint(first.left() + 1, 5)) == 0
    assert bar.insert_index_at(QPoint(first.right() - 1, 5)) == 1
    assert bar.insert_index_at(QPoint(last.right() + 50, 5)) == 3
    bar.deleteLater()


def test_each_tab_has_its_own_close_button(qapp):
    bar = TabBar()
    for name in ("a", "b"):
        bar.addTab(name)
    closing = []
    bar.tabCloseRequested.connect(closing.append)
    right = QTabBar.ButtonPosition.RightSide
    assert all(isinstance(bar.tabButton(i, right), GlyphButton) for i in range(2))
    bar.tabButton(1, right).click()
    bar.moveTab(1, 0)  # the button travels with its tab
    bar.tabButton(0, right).click()
    assert closing == [1, 0]
    bar.deleteLater()


def test_the_strip_is_only_as_wide_as_its_tabs(qapp):
    bar = TabBar()
    bar.addTab("a")
    assert bar.minimumSizeHint().width() <= bar.sizeHint().width()
    bar.deleteLater()


def test_tabs_are_quavers(qapp):
    bar = TabBar()
    sheet = bar.styleSheet()
    assert "border-bottom: 2px solid palette(highlight)" in sheet
    assert "radius" not in sheet  # square tabs
    bar.deleteLater()
