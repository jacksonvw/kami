"""A Kami window: tabs along the top, Notepad's menu bar under them, the
page, and a status bar.

Appearance works as in Pepper, Quaver and Semibreve (see `kami.ui.theme`):
- The window is created with WA_TranslucentBackground, so the native window
  has an alpha channel from the start.
- paintEvent fills it with the window colour: solid at 100% opacity, or the
  tint at the chosen strength over whatever KWin blurs behind.
- The widgets wear the suite's translucent stylesheet at every opacity, so
  the window's colour shows through all of them alike.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QEvent, QLocale, QSettings, Qt, QTime, QUrl
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QPainter,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kami.core.blur import set_blur_behind
from kami.ui.document import DocumentTab
from kami.ui.editor import local_files
from kami.ui.find_bar import FindBar
from kami.ui.tabbar import GlyphButton, TabBar, tab_id_from
from kami.ui.theme import Theme, stylesheet

if TYPE_CHECKING:
    from kami.ui.app import Kami

log = logging.getLogger(__name__)

OPEN_FILTERS = (
    "Text and Markdown (*.txt *.md *.markdown);;Text files (*.txt);;"
    "Markdown files (*.md *.markdown);;All files (*)"
)


def settings() -> QSettings:
    """Kami's QSettings: window geometry, bar visibility, the last folder."""
    return QSettings("kami", "kami")


def setting_bool(key: str, default: bool) -> bool:
    value = settings().value(key)
    if value is None:
        return default
    return value if isinstance(value, bool) else str(value).lower() == "true"


class MainWindow(QMainWindow):
    def __init__(self, app: Kami) -> None:
        super().__init__()
        self._app = app
        self.setObjectName("kami")
        # Set before the native window exists: toggled later, KWin keeps
        # the opaque visual it started with and the alpha is discarded.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAcceptDrops(True)
        self.setWindowTitle("Kami")
        self.setMinimumSize(360, 240)

        self._theme: Theme | None = None
        self._want_blur = False
        self._tabs: dict[str, DocumentTab] = {}

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_status_bar()

    # -- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("central")
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # Tabs first, then the menu bar, as in Windows 11 Notepad. The +
        # sits right after the last tab, so the strip is laid out by hand
        # rather than with QTabWidget, whose corner widget sits at the far
        # end.
        strip = QWidget(central)
        strip.setObjectName("tabStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(4)
        self.tab_bar = TabBar(strip)
        self._new_tab_button = GlyphButton(GlyphButton.PLUS, self.tab_bar.tab_height(), strip)
        self._new_tab_button.setToolTip("New Tab (Ctrl+N)")
        self._new_tab_button.clicked.connect(self.new_tab)
        row.addWidget(self.tab_bar)
        row.addWidget(self._new_tab_button, 0, Qt.AlignVCenter)
        row.addStretch(1)
        column.addWidget(strip)

        self.menu_bar = QMenuBar(central)
        self.menu_bar.setObjectName("menuBar")
        # Kept in the window even under a global-menu applet: it sits
        # below the tabs, not where a global menu would look for it.
        self.menu_bar.setNativeMenuBar(False)
        column.addWidget(self.menu_bar)

        self.find_bar = FindBar(central)
        self.find_bar.hide()
        self.find_bar.closed.connect(self._focus_current)
        column.addWidget(self.find_bar)

        self.pages = QStackedWidget(central)
        self.pages.setObjectName("pages")
        column.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        bar = self.tab_bar
        bar.currentChanged.connect(self._on_current_changed)
        bar.tabCloseRequested.connect(lambda i: self._app.close_tab(self, self.tab_at(i)))
        bar.tabMoved.connect(lambda *_: self._app.schedule_session_save())
        bar.tab_dropped.connect(lambda tab_id, index: self._app.move_tab(tab_id, self, index))
        bar.detach_requested.connect(self._app.detach_tab)
        bar.drag_finished.connect(self._app.reap_empty_windows)
        bar.new_tab_requested.connect(self.new_tab)
        bar.menu_requested.connect(self._show_tab_menu)

    def _act(self, label: str, shortcut, slot, checkable: bool = False) -> QAction:
        act = QAction(label, self)
        if shortcut is not None:
            shortcuts = shortcut if isinstance(shortcut, list) else [shortcut]
            act.setShortcuts([QKeySequence(s) for s in shortcuts])
        act.setCheckable(checkable)
        act.triggered.connect(slot)
        # On the window too, so the shortcuts work with the menu bar hidden.
        self.addAction(act)
        return act

    def _build_actions(self) -> None:
        a = self._act
        app = self._app
        # File
        self.act_new_tab = a("New Tab", "Ctrl+N", self.new_tab)
        self.act_new_window = a("New Window", "Ctrl+Shift+N", app.open_new_window)
        self.act_open = a("Open…", "Ctrl+O", self.open_dialog)
        self.act_save = a("Save", "Ctrl+S", lambda: self.save_tab(self.current_tab()))
        self.act_save_as = a(
            "Save As…", "Ctrl+Shift+S", lambda: self.save_tab(self.current_tab(), as_new=True)
        )
        self.act_save_all = a("Save All", "Ctrl+Alt+S", self.save_all)
        self.act_close_tab = a("Close Tab", "Ctrl+W", lambda: app.close_tab(self, self.current_tab()))
        self.act_close_window = a("Close Window", "Ctrl+Shift+W", self.close)
        self.act_merge = a("Merge All Windows Here", None, lambda: app.merge_all_into(self))
        self.act_quit = a("Exit", "Ctrl+Q", app.quit_all)
        # Edit
        self.act_undo = a("Undo", "Ctrl+Z", lambda: self._page_call("undo"))
        self.act_redo = a("Redo", ["Ctrl+Y", "Ctrl+Shift+Z"], lambda: self._page_call("redo"))
        self.act_cut = a("Cut", "Ctrl+X", lambda: self._page_call("cut"))
        self.act_copy = a("Copy", "Ctrl+C", lambda: self._page_call("copy"))
        self.act_paste = a("Paste", "Ctrl+V", lambda: self._page_call("paste"))
        self.act_delete = a("Delete", "Del", self._delete)
        self.act_find = a("Find…", "Ctrl+F", lambda: self.find_bar.open(replace=False))
        self.act_find_next = a("Find Next", "F3", lambda: self._find(backward=False))
        self.act_find_prev = a("Find Previous", "Shift+F3", lambda: self._find(backward=True))
        self.act_replace = a("Replace…", "Ctrl+H", lambda: self.find_bar.open(replace=True))
        self.act_goto = a("Go To…", "Ctrl+G", self.go_to_line)
        self.act_select_all = a("Select All", "Ctrl+A", lambda: self._page_call("selectAll"))
        self.act_time_date = a("Time/Date", "F5", self.insert_time_date)
        # View
        self.act_zoom_in = a("Zoom In", ["Ctrl++", "Ctrl+="], lambda: self._zoom(1))
        self.act_zoom_out = a("Zoom Out", "Ctrl+-", lambda: self._zoom(-1))
        self.act_zoom_reset = a("Restore Default Zoom", "Ctrl+0", lambda: self._zoom(0))
        self.act_preview = a("Markdown Preview", "Ctrl+Shift+V", self.toggle_preview, checkable=True)
        self.act_wrap = a("Word Wrap", None, lambda: app.set_word_wrap(self.act_wrap.isChecked()), checkable=True)
        self.act_status_bar = a(
            "Status Bar", None, lambda: app.set_status_bar_visible(self.act_status_bar.isChecked()),
            checkable=True,
        )
        self.act_menu_bar = a(
            "Menu Bar", "Ctrl+M", lambda: app.set_menu_bar_visible(self.act_menu_bar.isChecked()),
            checkable=True,
        )
        self.act_fullscreen = a("Full Screen", "F11", self.toggle_fullscreen, checkable=True)
        self.act_prefs = a("Preferences…", "Ctrl+,", lambda: app.show_preferences(self))
        # In no menu.
        a("Next Tab", ["Ctrl+Tab", "Ctrl+PgDown"], lambda: self._cycle(1))
        a("Previous Tab", ["Ctrl+Shift+Tab", "Ctrl+PgUp"], lambda: self._cycle(-1))
        # Offered by the page's right-click menu while the menu bar is hidden.
        self.act_show_menu_bar = QAction("Show Menu Bar", self)
        self.act_show_menu_bar.triggered.connect(lambda: app.set_menu_bar_visible(True))

    def _build_menus(self) -> None:
        mb = self.menu_bar
        file_menu = mb.addMenu("&File")
        file_menu.addActions([self.act_new_tab, self.act_new_window, self.act_open])
        file_menu.addSeparator()
        file_menu.addActions([self.act_save, self.act_save_as, self.act_save_all])
        file_menu.addSeparator()
        file_menu.addActions([self.act_close_tab, self.act_close_window, self.act_merge])
        file_menu.addSeparator()
        file_menu.addAction(self.act_prefs)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        file_menu.aboutToShow.connect(
            lambda: self.act_merge.setEnabled(len(self._app.windows) > 1)
        )

        edit_menu = mb.addMenu("&Edit")
        edit_menu.addActions([self.act_undo, self.act_redo])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_cut, self.act_copy, self.act_paste, self.act_delete])
        edit_menu.addSeparator()
        edit_menu.addActions([
            self.act_find, self.act_find_next, self.act_find_prev, self.act_replace, self.act_goto,
        ])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_select_all, self.act_time_date])
        edit_menu.aboutToShow.connect(self._sync_edit_actions)
        # Re-enable on close, so a shortcut isn't left disabled by a menu
        # that was opened when nothing was selected.
        edit_menu.aboutToHide.connect(self._enable_edit_actions)

        view_menu = mb.addMenu("&View")
        zoom_menu = view_menu.addMenu("Zoom")
        zoom_menu.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_reset])
        view_menu.addActions([self.act_preview, self.act_wrap])
        view_menu.addSeparator()
        view_menu.addActions([self.act_status_bar, self.act_menu_bar, self.act_fullscreen])

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        sb.setObjectName("status")
        sb.setSizeGripEnabled(False)
        self._pos_label = QLabel()
        self._pos_label.setObjectName("position")
        sb.addWidget(self._pos_label, 1)
        self._chars_label = QLabel()
        self._zoom_label = QLabel()
        self._eol_label = QLabel()
        self._enc_label = QLabel()
        for label in (self._chars_label, self._zoom_label, self._eol_label, self._enc_label):
            sb.addPermanentWidget(label)

    # -- Tabs ------------------------------------------------------------

    def tabs(self) -> list[DocumentTab]:
        return [self._tabs[self.tab_bar.tabData(i)] for i in range(self.tab_bar.count())]

    def count(self) -> int:
        return self.tab_bar.count()

    def has_tab(self, tab_id: str) -> bool:
        return tab_id in self._tabs

    def tab_by_id(self, tab_id: str) -> DocumentTab | None:
        return self._tabs.get(tab_id)

    def tab_at(self, index: int) -> DocumentTab | None:
        return self._tabs.get(self.tab_bar.tabData(index)) if index >= 0 else None

    def current_tab(self) -> DocumentTab | None:
        return self.tab_at(self.tab_bar.currentIndex())

    def index_of(self, tab: DocumentTab) -> int:
        for i in range(self.tab_bar.count()):
            if self.tab_bar.tabData(i) == tab.id:
                return i
        return -1

    def set_current(self, tab: DocumentTab) -> None:
        index = self.index_of(tab)
        if index >= 0:
            self.tab_bar.setCurrentIndex(index)

    def add_tab(self, tab: DocumentTab, index: int = -1, make_current: bool = True) -> None:
        self._tabs[tab.id] = tab
        self.pages.addWidget(tab)
        tab.title_changed.connect(self._on_tab_title_changed)
        tab.status_changed.connect(self._on_tab_status_changed)
        tab.files_dropped.connect(self._on_files_dropped)
        tab.open_file_requested.connect(self._on_open_file_requested)
        tab.editor.extra_context_actions = [self.act_show_menu_bar]
        if index < 0 or index > self.tab_bar.count():
            index = self.tab_bar.count()
        index = self.tab_bar.insertTab(index, tab.tab_text())
        self.tab_bar.setTabData(index, tab.id)
        self._refresh_tab(tab)
        if self.tab_bar.currentIndex() == index:
            # The first tab becomes current inside insertTab, before it has
            # its id, so the currentChanged it fired found no tab.
            self._on_current_changed(index)
        elif make_current:
            self.tab_bar.setCurrentIndex(index)

    def take_tab(self, tab: DocumentTab) -> None:
        """Remove `tab` from this window without deleting it."""
        index = self.index_of(tab)
        if index < 0:
            return
        tab.title_changed.disconnect(self._on_tab_title_changed)
        tab.status_changed.disconnect(self._on_tab_status_changed)
        tab.files_dropped.disconnect(self._on_files_dropped)
        tab.open_file_requested.disconnect(self._on_open_file_requested)
        del self._tabs[tab.id]
        self.tab_bar.removeTab(index)
        self.pages.removeWidget(tab)
        tab.setParent(None)

    def move_tab_within(self, tab: DocumentTab, insert_index: int) -> None:
        """Move `tab` to where a drop at `insert_index` puts it."""
        index = self.index_of(tab)
        if index < 0:
            return
        target = insert_index - 1 if insert_index > index else insert_index
        target = max(0, min(target, self.count() - 1))
        if target != index:
            self.tab_bar.moveTab(index, target)

    def new_tab(self) -> DocumentTab:
        tab = self._app.create_tab()
        self.add_tab(tab)
        self._app.schedule_session_save()
        tab.focus()
        return tab

    def ensure_blank_tab(self) -> DocumentTab:
        """The current tab if it's empty and untitled, else a new one."""
        tab = self.current_tab()
        if tab is not None and tab.is_pristine():
            return tab
        return self.new_tab()

    def _on_current_changed(self, _index: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        self.pages.setCurrentWidget(tab)
        self.find_bar.set_editor(tab.editor)
        self._refresh_title()
        self._refresh_status()
        self._sync_view_actions()
        tab.focus()
        self._app.schedule_session_save()

    def _on_tab_title_changed(self) -> None:
        tab = self.sender()
        if isinstance(tab, DocumentTab):
            self._refresh_tab(tab)

    def _on_tab_status_changed(self) -> None:
        if self.sender() is self.current_tab():
            self._refresh_status()

    def _on_files_dropped(self, paths: list) -> None:
        self._app.open_paths(paths, self)

    def _on_open_file_requested(self, path: str) -> None:
        self._app.open_paths([path], self)

    def _refresh_tab(self, tab: DocumentTab) -> None:
        index = self.index_of(tab)
        if index < 0:
            return
        self.tab_bar.setTabText(index, tab.tab_text())
        self.tab_bar.setTabToolTip(index, tab.path or "")
        if tab is self.current_tab():
            self._refresh_title()

    def _refresh_title(self) -> None:
        tab = self.current_tab()
        self.setWindowTitle(f"Kami — {tab.display_name()}" if tab else "Kami")

    def _refresh_status(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if tab.is_previewing():
            self._pos_label.setText("Markdown preview")
        else:
            line, col = tab.cursor_position()
            self._pos_label.setText(f"Ln {line}, Col {col}")
        total = tab.char_count()
        noun = "character" if total == 1 else "characters"
        selected = tab.selected_count()
        self._chars_label.setText(
            f"{selected:,} of {total:,} {noun}" if selected else f"{total:,} {noun}"
        )
        self._zoom_label.setText(f"{tab.zoom}%")
        self._eol_label.setText(tab.fmt.eol_label)
        self._enc_label.setText(tab.fmt.encoding_label)

    def _focus_current(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.focus()

    def _cycle(self, step: int) -> None:
        count = self.count()
        if count > 1:
            self.tab_bar.setCurrentIndex((self.tab_bar.currentIndex() + step) % count)

    def _show_tab_menu(self, index: int, global_pos) -> None:
        tab = self.tab_at(index)
        app = self._app
        menu = QMenu(self)
        if tab is not None:
            menu.addAction("Close Tab", lambda: app.close_tab(self, tab))
            others = [t for t in self.tabs() if t is not tab]
            menu.addAction(
                "Close Other Tabs", lambda: app.close_tabs(self, others)
            ).setEnabled(bool(others))
            right = self.tabs()[index + 1:]
            menu.addAction(
                "Close Tabs to the Right", lambda: app.close_tabs(self, right)
            ).setEnabled(bool(right))
            menu.addSeparator()
            menu.addAction(
                "Move to New Window", lambda: app.detach_tab(tab.id)
            ).setEnabled(self.count() > 1)
            targets = [w for w in app.windows if w is not self]
            if targets:
                sub = menu.addMenu("Move to Window")
                for w in targets:
                    sub.addAction(w.windowTitle(), lambda w=w: app.move_tab(tab.id, w, activate=True))
            if tab.path:
                menu.addSeparator()
                menu.addAction(
                    "Copy File Path", lambda: QGuiApplication.clipboard().setText(tab.path)
                )
                menu.addAction(
                    "Open Containing Folder",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(tab.path))),
                )
        else:
            menu.addAction(self.act_new_tab)
        if len(app.windows) > 1:
            menu.addSeparator()
            menu.addAction(self.act_merge)
        if not self.menu_bar.isVisible():
            menu.addSeparator()
            menu.addAction(self.act_show_menu_bar)
            menu.addAction(self.act_prefs)
        menu.exec(global_pos)
        menu.deleteLater()

    # -- File ------------------------------------------------------------

    def dialog_dir(self) -> str:
        """Where Open and Save As start: the current file's folder, else the
        last one used, else ~/Documents."""
        tab = self.current_tab()
        if tab is not None and tab.path:
            return os.path.dirname(tab.path)
        last = settings().value("last_dir")
        if isinstance(last, str) and os.path.isdir(last):
            return last
        docs = Path.home() / "Documents"
        return str(docs if docs.is_dir() else Path.home())

    def open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", self.dialog_dir(), OPEN_FILTERS)
        if paths:
            settings().setValue("last_dir", os.path.dirname(paths[0]))
            self._app.open_paths(paths, self)

    def save_tab(self, tab: DocumentTab | None, as_new: bool = False) -> bool:
        """Save `tab`, asking where for an untitled one. True if it was saved."""
        if tab is None:
            return False
        path = tab.path
        if as_new or path is None:
            path = self._app.ask_save_path(self, tab)
            if not path:
                return False
        try:
            tab.save_as(path)
        except OSError as exc:
            log.warning("could not save %s: %s", path, exc)
            self._app.show_error(
                self, "Couldn't save",
                f"Kami couldn't save {os.path.basename(path)}.\n\n{exc.strerror or exc}",
            )
            return False
        settings().setValue("last_dir", os.path.dirname(tab.path))
        self._app.note_saved(tab)
        return True

    def save_all(self) -> None:
        for tab in self.tabs():
            if tab.needs_saving():
                self.set_current(tab)
                if not self.save_tab(tab):
                    return

    # -- Edit ------------------------------------------------------------

    def _page_call(self, name: str) -> None:
        """Call `name` on the current page: the editor, or the preview."""
        tab = self.current_tab()
        if tab is not None:
            getattr(tab.currentWidget(), name)()

    def _delete(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.is_previewing():
            return
        cur = tab.editor.textCursor()
        if cur.hasSelection():
            cur.removeSelectedText()
        else:
            cur.deleteChar()

    def _find(self, backward: bool) -> None:
        if self.find_bar.find_edit.text():
            self.find_bar.find(backward=backward)
        else:
            self.find_bar.open(replace=False)

    def _sync_edit_actions(self) -> None:
        tab = self.current_tab()
        editing = tab is not None and not tab.is_previewing()
        doc = tab.editor.document() if tab is not None else None
        selected = tab is not None and tab.currentWidget().textCursor().hasSelection()
        self.act_undo.setEnabled(editing and doc.isUndoAvailable())
        self.act_redo.setEnabled(editing and doc.isRedoAvailable())
        self.act_cut.setEnabled(editing and selected)
        self.act_copy.setEnabled(selected)
        self.act_paste.setEnabled(editing)
        self.act_delete.setEnabled(editing)
        for act in (self.act_replace, self.act_goto, self.act_time_date):
            act.setEnabled(editing)

    def _enable_edit_actions(self) -> None:
        for act in (
            self.act_undo, self.act_redo, self.act_cut, self.act_copy, self.act_paste,
            self.act_delete, self.act_replace, self.act_goto, self.act_time_date,
        ):
            act.setEnabled(True)

    def go_to_line(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        tab.set_preview(False)
        doc = tab.editor.document()
        line, _ = tab.cursor_position()
        number, ok = QInputDialog.getInt(
            self, "Go To Line", "Line number:", line, 1, doc.blockCount()
        )
        if ok:
            cur = tab.editor.textCursor()
            cur.setPosition(doc.findBlockByNumber(number - 1).position())
            tab.editor.setTextCursor(cur)
            tab.editor.centerCursor()
        tab.focus()

    def insert_time_date(self) -> None:
        """Type the time and date, as Notepad's F5 does."""
        tab = self.current_tab()
        if tab is None or tab.is_previewing():
            return
        locale = QLocale.system()
        tab.editor.insertPlainText(
            f"{locale.toString(QTime.currentTime(), QLocale.ShortFormat)} "
            f"{locale.toString(QDate.currentDate(), QLocale.ShortFormat)}"
        )

    # -- View ------------------------------------------------------------

    def _zoom(self, step: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if step == 0:
            tab.set_zoom(100)
        else:
            tab.step_zoom(step)

    def toggle_preview(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.toggle_preview()
        self._sync_view_actions()
        self._app.schedule_session_save()

    def toggle_fullscreen(self) -> None:
        # Flip only the fullscreen flag, so a maximized window comes back
        # maximized, as Pepper does.
        self.setWindowState(self.windowState() ^ Qt.WindowFullScreen)

    def apply_chrome(self, menu_bar: bool, status_bar: bool, word_wrap: bool) -> None:
        self.menu_bar.setVisible(menu_bar)
        self.statusBar().setVisible(status_bar)
        self.act_show_menu_bar.setVisible(not menu_bar)
        self._sync_view_actions(menu_bar, status_bar, word_wrap)

    def _sync_view_actions(self, menu_bar=None, status_bar=None, word_wrap=None) -> None:
        tab = self.current_tab()
        self.act_preview.setChecked(tab is not None and tab.is_previewing())
        if menu_bar is not None:
            self.act_menu_bar.setChecked(menu_bar)
        if status_bar is not None:
            self.act_status_bar.setChecked(status_bar)
        if word_wrap is not None:
            self.act_wrap.setChecked(word_wrap)
        self.act_fullscreen.setChecked(self.isFullScreen())

    # -- Appearance ------------------------------------------------------

    def apply_theme(self, theme: Theme, blur: bool) -> None:
        self._theme = theme
        self._want_blur = blur and theme.translucent
        self.setStyleSheet(stylesheet(theme))
        self.tab_bar.set_button_colors(theme.glyph, theme.glyph_hot, theme.glyph_fill)
        self._new_tab_button.set_colors(theme.glyph, theme.glyph_hot, theme.glyph_fill)
        set_blur_behind(self, self._want_blur)
        self.update()

    def paintEvent(self, ev) -> None:
        if self._theme is None:
            super().paintEvent(ev)
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._theme.paper)
        painter.end()

    def showEvent(self, ev) -> None:
        # windowHandle() is None until now, so this is the first point at
        # which blur can be applied. Qt can also recreate the native window
        # (fullscreen transitions), which lands here again.
        super().showEvent(ev)
        set_blur_behind(self, self._want_blur)

    # -- Window events ---------------------------------------------------

    def changeEvent(self, ev) -> None:
        if ev.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._app.note_active(self)
        elif ev.type() == QEvent.WindowStateChange:
            self.act_fullscreen.setChecked(self.isFullScreen())
        super().changeEvent(ev)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            if self.find_bar.isVisible():
                self.find_bar.close_bar()
                ev.accept()
                return
            if self.isFullScreen():
                self.toggle_fullscreen()
                ev.accept()
                return
        super().keyPressEvent(ev)

    def closeEvent(self, ev) -> None:
        if self._app.request_close_window(self):
            settings().setValue("geometry", self.saveGeometry())
            ev.accept()
        else:
            ev.ignore()

    # Files dropped on the window open as tabs; a tab dragged from another
    # Kami window joins this one. A tab dragged from this window is left
    # alone, so letting go over its own page gives it a new window.

    def _accepts(self, mime) -> bool:
        if local_files(mime):
            return True
        tab_id = tab_id_from(mime)
        return tab_id is not None and tab_id not in self._tabs

    def dragEnterEvent(self, ev) -> None:
        if self._accepts(ev.mimeData()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:
        self.dragEnterEvent(ev)

    def dropEvent(self, ev) -> None:
        mime = ev.mimeData()
        files = local_files(mime)
        if files:
            ev.acceptProposedAction()
            self._app.open_paths(files, self)
            return
        tab_id = tab_id_from(mime)
        if tab_id is not None and tab_id not in self._tabs:
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
            self._app.move_tab(tab_id, self)
            return
        ev.ignore()
