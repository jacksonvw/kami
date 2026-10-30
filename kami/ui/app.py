"""Kami's application object: the windows, tabs moving between them, the
session, and the requests that later `kami` commands hand over.

Every window lives in this one process, so a tab moves to another window by
reparenting its widget, undo history and all.

Closing works the way Windows 11 Notepad's does when it keeps the session:
- Closing the last window, or Exit, closes Kami without a question, and
  every tab comes back next time, unsaved text included.
- Closing one window while others stay open closes its saved files and
  keeps its unsaved tabs for next time, again without a question. Logging
  out of Plasma closes windows one at a time, exactly as if you had, and
  that must neither stop to ask nor lose anything.
- Closing a tab asks about its unsaved changes. Closing a window's last
  tab leaves a blank one, as in Notepad++, rather than closing the window.
With "Reopen tabs" turned off in Preferences, closing a window asks about
each of its unsaved tabs instead.
"""

from __future__ import annotations

import copy
import logging
import os
import re

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from kami.core.config import AppConfig, load_config, save_config
from kami.core.session import SessionStore, TabState, WindowState
from kami.core.textfile import FileTooLarge
from kami.ui.document import UNTITLED, DocumentTab
from kami.ui.markdown import PreviewStyle
from kami.ui.theme import theme_for
from kami.ui.window import MainWindow, setting_bool, settings

log = logging.getLogger(__name__)

# How long after the last keystroke unsaved text is written to the session.
AUTOSAVE_MS = 1000

SAVE_FILTERS = "Text files (*.txt);;Markdown files (*.md);;All files (*)"

# Kanji are shared with Chinese, so Qt's font fallback can't tell they
# belong with the kana beside them and draws them from another font: on
# Fedora, Droid Sans Fallback's light strokes beside Noto Sans CJK JP's.
# Naming one CJK family after the page's font keeps a word in one weight.
# Chinese text then gets the Japanese forms of some characters; a language
# setting in Preferences may choose the family in future.
CJK_MONO = "Noto Sans Mono CJK JP"
CJK_SANS = "Noto Sans CJK JP"


def with_cjk(font: QFont, family: str) -> QFont:
    """`font`, falling back to `family` for Chinese and Japanese, if it's installed."""
    if QFontDatabase.hasFamily(family) and family not in font.families():
        font.setFamilies([*font.families(), family])
    return font


def suggested_file_name(tab: DocumentTab) -> str:
    """What Save As offers: the file's name, or the tab's title plus .txt
    (.md when the text opens with a Markdown heading)."""
    if tab.path:
        return os.path.basename(tab.path)
    name = tab.display_name()
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip(" .…") or UNTITLED
    return name + (".md" if tab.text().lstrip().startswith("#") else ".txt")


def _ask_save(parent, tab: DocumentTab) -> str:
    """Notepad's question. Returns "save", "discard" or "cancel"."""
    answer = QMessageBox.question(
        parent, "Kami", f"Do you want to save changes to {tab.display_name()}?",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save,
    )
    return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(answer, "cancel")


def _ask_save_path(parent, tab: DocumentTab) -> str | None:
    suggested = suggested_file_name(tab)
    chosen_filter = SAVE_FILTERS.split(";;")[1 if suggested.endswith(".md") else 0]
    path, chosen = QFileDialog.getSaveFileName(
        parent, "Save As", os.path.join(parent.dialog_dir(), suggested), SAVE_FILTERS, chosen_filter
    )
    if not path:
        return None
    if not os.path.splitext(path)[1]:
        if chosen.startswith("Markdown"):
            path += ".md"
        elif chosen.startswith("Text"):
            path += ".txt"
    return path


def _show_error(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


class Kami(QObject):
    def __init__(
        self,
        config: AppConfig | None = None,
        store: SessionStore | None = None,
        use_session: bool = True,
    ) -> None:
        super().__init__()
        self.config = config or load_config()
        self.store = store or SessionStore()
        # False for a Kami that couldn't take the single-instance lock. Two
        # Kamis sharing the session would each prune the other's unsaved
        # text, so the second runs without one and asks before closing
        # unsaved tabs, as with "Reopen tabs" off.
        self.use_session = use_session
        # Most recently active last.
        self.windows: list[MainWindow] = []
        self._theme = theme_for(self.config.appearance, QGuiApplication.palette())
        # Tracked apart from the config, which a caller may edit in place.
        self._restoring = self.config.restore_session
        self._quitting = False
        # Tabs whose text changed since the session was last written.
        self._dirty: set[str] = set()
        # The unsaved tabs of windows closed while others stayed open,
        # kept for the next start.
        self._parked: list[WindowState] = []
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self.save_session_now)
        # The questions Kami asks, replaceable so the tests can answer them.
        self.ask_save = _ask_save
        self.ask_save_path = _ask_save_path
        self.show_error = _show_error
        # Any other way out (the session manager, a quit from elsewhere)
        # still leaves the session written.
        qt_app = QGuiApplication.instance()
        if qt_app is not None:
            qt_app.aboutToQuit.connect(self._on_about_to_quit)
            qt_app.commitDataRequest.connect(lambda _manager: self._on_about_to_quit())

    # -- Start-up and requests -------------------------------------------

    def start(self, files: list[str]) -> None:
        restored = self.keeps_session() and self._restore_session()
        if files:
            self.activate(self.open_paths(files))
        elif not restored:
            win = self.new_window()
            win.show()

    def handle_request(self, request: dict) -> None:
        """Open what a later `kami` asked for, and bring its window forward."""
        files = request.get("files") or []
        target = None
        if self.config.open_in == "window" or not self.windows:
            target = self.new_window(blank=not files)
        if files:
            win = self.open_paths(files, target)
            if target is not None and target is not win and target.count() == 0:
                # Every file was already open elsewhere.
                self._drop_window(target)
        else:
            win = target or self.last_window()
            win.ensure_blank_tab()
            win.show()
        self.activate(win, request.get("token"))

    def activate(self, win: MainWindow, token: str | None = None) -> None:
        """Bring `win` to the front.

        On Wayland that takes an activation token, which only the launcher
        the user just used can supply: Qt picks it up from the environment.
        Without one, KWin may only highlight the window in the task bar.
        """
        if token:
            os.environ["XDG_ACTIVATION_TOKEN"] = token
        if win.isMinimized():
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
        win.show()
        win.raise_()
        win.activateWindow()
        tab = win.current_tab()
        if tab is not None:
            tab.focus()

    # -- Windows ---------------------------------------------------------

    def new_window(self, blank: bool = True) -> MainWindow:
        win = MainWindow(self)
        win.apply_theme(self._theme, self.config.appearance.blur_behind)
        win.apply_chrome(
            setting_bool("menu_bar_visible", True),
            setting_bool("status_bar_visible", True),
            self.config.word_wrap,
        )
        geometry = settings().value("geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            win.restoreGeometry(geometry)
            if win.isFullScreen():
                win.setWindowState(win.windowState() & ~Qt.WindowFullScreen)
        else:
            self._size_for_first_run(win)
        self.windows.append(win)
        if blank:
            win.add_tab(self.create_tab())
        return win

    def open_new_window(self) -> None:
        win = self.new_window()
        win.show()
        self.activate(win)

    @staticmethod
    def _size_for_first_run(win: MainWindow) -> None:
        screen = win.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            win.resize(900, 640)
            return
        area = screen.availableGeometry()
        win.resize(min(900, int(area.width() * 0.6)), min(640, int(area.height() * 0.7)))

    def last_window(self) -> MainWindow | None:
        return self.windows[-1] if self.windows else None

    def note_active(self, win: MainWindow) -> None:
        if win in self.windows and self.windows[-1] is not win:
            self.windows.remove(win)
            self.windows.append(win)

    def request_close_window(self, win: MainWindow) -> bool:
        """Called from the window's closeEvent. True lets it close."""
        if win not in self.windows:
            return True
        if not self._quitting:
            if len(self.windows) > 1:
                if self.keeps_session():
                    self._park(win)
                elif not self._resolve_unsaved(win, win.tabs()):
                    return False
                self.schedule_session_save()
            elif not self._prepare_quit():
                return False
        # After _prepare_quit, so the session it saves includes this window.
        self.windows.remove(win)
        return True

    def _park(self, win: MainWindow) -> None:
        """Keep a closing window's unsaved tabs, unseen, for the next start."""
        states = []
        for tab in win.tabs():
            if not tab.needs_saving():
                continue
            try:
                self.store.write_text(tab.id, tab.text())
            except OSError as exc:
                log.warning("could not keep tab %s: %s", tab.id, exc)
                continue
            states.append(tab.state())
        if states:
            self._parked.append(WindowState(
                tabs=states, geometry=bytes(win.saveGeometry().toBase64().data()).decode(),
            ))

    def _on_about_to_quit(self) -> None:
        if not self._quitting:
            self.save_session_now()

    def quit_all(self) -> None:
        """File → Exit: close every window, keeping the session."""
        if not self.windows:
            QApplication.quit()
            return
        if self._prepare_quit():
            for win in list(self.windows):
                win.close()

    def _prepare_quit(self) -> bool:
        if self.keeps_session():
            self.save_session_now()
        else:
            for win in reversed(self.windows):
                if not self._resolve_unsaved(win, win.tabs()):
                    return False
            if self.use_session:
                self.store.clear()
        self._quitting = True
        self._autosave.stop()
        return True

    def _drop_window(self, win: MainWindow) -> None:
        """Close a window that has no tabs left."""
        if win in self.windows:
            self.windows.remove(win)
        win.hide()
        win.close()

    def reap_empty_windows(self) -> None:
        """Close windows emptied by moving their tabs away.

        Deferred while a tab dragged out of one is still in the air: the
        drag runs inside the window's own tab bar, which must outlive it.
        """
        for win in list(self.windows):
            if win.count() == 0 and not win.tab_bar.dragging:
                self._drop_window(win)

    # -- Tabs ------------------------------------------------------------

    def create_tab(
        self, tab_id: str | None = None, state: TabState | None = None, text: str | None = None
    ) -> DocumentTab:
        """A new tab, or one restored from `state`. Raises if the restore fails."""
        tab = DocumentTab(tab_id)
        if state is not None:
            try:
                tab.restore(state, text)
            except BaseException:
                tab.deleteLater()
                raise
        tab.apply_style(self.editor_font(), self.preview_style(), self.config.word_wrap)
        tab.content_changed.connect(self._on_tab_content_changed)
        return tab

    def find_tab(self, tab_id: str) -> tuple[MainWindow, DocumentTab] | None:
        for win in self.windows:
            tab = win.tab_by_id(tab_id)
            if tab is not None:
                return win, tab
        return None

    def find_tab_by_path(self, path: str) -> tuple[MainWindow, DocumentTab] | None:
        wanted = os.path.realpath(path)
        for win in self.windows:
            for tab in win.tabs():
                if tab.path and os.path.realpath(tab.path) == wanted:
                    return win, tab
        return None

    def open_paths(self, paths: list[str], window: MainWindow | None = None) -> MainWindow:
        """Open each path as a tab and return the window holding the last.

        A file already open anywhere is shown rather than opened twice, and
        a path that doesn't exist opens as a new file that the first save
        creates. An empty untitled tab in front gives way to the first file.
        """
        win = window if window in self.windows else self.last_window()
        if win is None:
            win = self.new_window(blank=False)
        problems = []
        last = win
        for raw in paths:
            path = os.path.abspath(raw)
            found = self.find_tab_by_path(path)
            if found is not None:
                last, tab = found
                last.set_current(tab)
                continue
            if os.path.isdir(path):
                problems.append(f"{path} is a folder.")
                continue
            tab = self.create_tab()
            try:
                if os.path.exists(path):
                    tab.load(path)
                else:
                    tab.set_new_file(path)
            except FileTooLarge as exc:
                problems.append(str(exc))
                tab.deleteLater()
                continue
            except (OSError, UnicodeError) as exc:
                problems.append(f"{os.path.basename(path)}: {getattr(exc, 'strerror', None) or exc}")
                tab.deleteLater()
                continue
            current = win.current_tab()
            if current is not None and current.is_pristine():
                win.add_tab(tab, win.index_of(current) + 1)
                self._discard_tab(win, current)
            else:
                win.add_tab(tab)
            last = win
        if win.count() == 0:
            win.add_tab(self.create_tab())
        if not win.isVisible():
            win.show()
        if problems:
            self.show_error(last, "Couldn't open", "\n".join(problems))
        self.schedule_session_save()
        return last

    def move_tab(
        self, tab_id: str, target: MainWindow, index: int = -1, activate: bool = False
    ) -> None:
        found = self.find_tab(tab_id)
        if found is None:
            return
        source, tab = found
        if source is target:
            if index >= 0:
                target.move_tab_within(tab, index)
            return
        source.take_tab(tab)
        target.add_tab(tab, index)
        if source.count() == 0:
            source.hide()
            if not source.tab_bar.dragging:
                self._drop_window(source)
        if activate:
            self.activate(target)
        self.schedule_session_save()

    def detach_tab(self, tab_id: str) -> None:
        """Give a tab a window of its own."""
        found = self.find_tab(tab_id)
        if found is None:
            return
        source, tab = found
        if source.count() < 2:
            return
        win = self.new_window(blank=False)
        win.resize(source.size())
        source.take_tab(tab)
        win.add_tab(tab)
        win.show()
        self.activate(win)
        self.schedule_session_save()

    def merge_all_into(self, target: MainWindow) -> None:
        for win in [w for w in self.windows if w is not target]:
            for tab in win.tabs():
                win.take_tab(tab)
                target.add_tab(tab, make_current=False)
            self._drop_window(win)
        self.activate(target)
        self.schedule_session_save()

    def close_tab(self, win: MainWindow, tab: DocumentTab | None) -> bool:
        """Close `tab`, asking about unsaved changes. A window's last tab
        gives way to a blank one; Close Window closes the window."""
        if tab is None or win.index_of(tab) < 0:
            return False
        if win.count() == 1 and tab.is_pristine():
            return True  # already a blank page
        if not self._resolve_unsaved(win, [tab]):
            return False
        if win.count() == 1:
            win.new_tab()
        self._discard_tab(win, tab)
        self.schedule_session_save()
        return True

    def close_tabs(self, win: MainWindow, tabs: list[DocumentTab]) -> None:
        for tab in list(tabs):
            if not self.close_tab(win, tab):
                return

    def _discard_tab(self, win: MainWindow, tab: DocumentTab) -> None:
        win.take_tab(tab)
        self.store.discard_text(tab.id)
        self._dirty.discard(tab.id)
        tab.deleteLater()

    def _resolve_unsaved(self, win: MainWindow, tabs: list[DocumentTab]) -> bool:
        """Ask about each unsaved tab. False if the user cancelled."""
        for tab in tabs:
            if not tab.needs_saving():
                continue
            win.set_current(tab)
            answer = self.ask_save(win, tab)
            if answer == "cancel":
                return False
            if answer == "save" and not win.save_tab(tab):
                return False
        return True

    def note_saved(self, tab: DocumentTab) -> None:
        self._dirty.add(tab.id)
        self.schedule_session_save()

    def _on_tab_content_changed(self) -> None:
        tab = self.sender()
        if isinstance(tab, DocumentTab):
            self._dirty.add(tab.id)
            self.schedule_session_save()

    # -- Session ---------------------------------------------------------

    def keeps_session(self) -> bool:
        return self.use_session and self.config.restore_session

    def schedule_session_save(self) -> None:
        if self.keeps_session() and not self._quitting:
            self._autosave.start()

    def save_session_now(self) -> None:
        """Write the session: every window and tab, and each unsaved text."""
        self._autosave.stop()
        if not self.keeps_session():
            return
        # Parked windows first, so the open ones come back on top of them.
        windows = list(self._parked)
        keep = {t.id for w in self._parked for t in w.tabs}
        try:
            for win in self.windows:
                states = []
                current = win.current_tab()
                current_index = 0
                for tab in win.tabs():
                    state = tab.state()
                    if state.path is None and not state.modified:
                        continue  # An empty untitled tab isn't worth keeping.
                    if state.modified:
                        if tab.id in self._dirty or not self.store.has_text(tab.id):
                            self.store.write_text(tab.id, tab.text())
                        keep.add(tab.id)
                    if tab is current:
                        current_index = len(states)
                    states.append(state)
                if states:
                    windows.append(WindowState(
                        tabs=states,
                        current=current_index,
                        geometry=bytes(win.saveGeometry().toBase64().data()).decode(),
                    ))
            self.store.save(windows)
            self.store.prune(keep)
            self._dirty.clear()
        except OSError as exc:
            log.warning("could not save the session: %s", exc)

    def _restore_session(self) -> bool:
        missing = []
        for saved in self.store.load():
            win = self.new_window(blank=False)
            for state in saved.tabs:
                text = self.store.read_text(state.id) if state.modified else None
                try:
                    tab = self.create_tab(state.id, state, text)
                except (OSError, ValueError, UnicodeError, FileTooLarge) as exc:
                    log.info("not reopening tab %s (%s): %s", state.id, state.path, exc)
                    if state.path:
                        missing.append(os.path.basename(state.path))
                    continue
                win.add_tab(tab, make_current=False)
            if win.count() == 0:
                self.windows.remove(win)
                win.deleteLater()
                continue
            win.tab_bar.setCurrentIndex(min(saved.current, win.count() - 1))
            if saved.geometry:
                win.restoreGeometry(QByteArray.fromBase64(saved.geometry.encode()))
                if win.isFullScreen():
                    win.setWindowState(win.windowState() & ~Qt.WindowFullScreen)
            win.show()
        if missing and self.windows:
            names = ", ".join(missing)
            self.windows[-1].statusBar().showMessage(f"Couldn't reopen {names}", 15000)
        return bool(self.windows)

    # -- Settings --------------------------------------------------------

    def editor_font(self) -> QFont:
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        if self.config.font_family:
            font.setFamilies([self.config.font_family])
        if self.config.font_size > 0:
            font.setPointSizeF(self.config.font_size)
        return with_cjk(font, CJK_MONO)

    def preview_style(self) -> PreviewStyle:
        t = self._theme
        body = with_cjk(QFontDatabase.systemFont(QFontDatabase.GeneralFont), CJK_SANS)
        # VS Code's preview runs a little larger than its editor.
        size = body.pointSizeF() if body.pointSizeF() > 0 else 10.0
        body.setPointSizeF(size * 1.1)
        return PreviewStyle(
            body_font=body, code_font=self.editor_font(), text=t.text, muted=t.muted,
            rule=t.rule, code_bg=t.tint, link=t.link, dark=t.dark,
        )

    def apply_config(self, config: AppConfig) -> None:
        was_restoring = self._restoring
        self._restoring = config.restore_session
        self.config = config
        self._theme = theme_for(config.appearance, QGuiApplication.palette())
        font, style = self.editor_font(), self.preview_style()
        for win in self.windows:
            win.apply_theme(self._theme, config.appearance.blur_behind)
            win.apply_chrome(
                setting_bool("menu_bar_visible", True),
                setting_bool("status_bar_visible", True),
                config.word_wrap,
            )
            for tab in win.tabs():
                tab.apply_style(font, style, config.word_wrap)
        if not self.use_session:
            return
        if was_restoring and not config.restore_session:
            self._autosave.stop()
            self._parked.clear()
            self.store.clear()
        elif config.restore_session and not was_restoring:
            self.save_session_now()

    def set_word_wrap(self, on: bool) -> None:
        config = copy.deepcopy(self.config)
        config.word_wrap = on
        save_config(config)
        self.apply_config(config)

    def set_menu_bar_visible(self, visible: bool) -> None:
        settings().setValue("menu_bar_visible", visible)
        self._apply_chrome()

    def set_status_bar_visible(self, visible: bool) -> None:
        settings().setValue("status_bar_visible", visible)
        self._apply_chrome()

    def _apply_chrome(self) -> None:
        for win in self.windows:
            win.apply_chrome(
                setting_bool("menu_bar_visible", True),
                setting_bool("status_bar_visible", True),
                self.config.word_wrap,
            )

    def show_preferences(self, parent: MainWindow) -> None:
        from kami.ui.dialogs.preferences import PreferencesDialog
        dlg = PreferencesDialog(self.config, parent)
        dlg.settings_changed.connect(self.apply_config)
        dlg.exec()
