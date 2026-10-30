"""The application object: opening, closing, moving tabs, the session."""

from __future__ import annotations

import stat

import pytest

from kami.tests.conftest import dispose, make_kami, type_into
from kami.ui.app import CJK_MONO


def test_first_start_opens_a_blank_window(kami):
    kami.start([])
    assert len(kami.windows) == 1
    assert kami.windows[0].count() == 1
    assert kami.windows[0].current_tab().is_pristine()


def test_a_file_replaces_the_empty_tab(kami, tmp_path):
    kami.start([])
    p = tmp_path / "a.txt"
    p.write_text("hello")
    win = kami.open_paths([str(p)])
    assert win.count() == 1
    assert win.current_tab().path == str(p)
    assert win.windowTitle() == "Kami — a.txt"


def test_an_open_file_is_shown_not_reopened(kami, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a")
    b.write_text("b")
    kami.start([str(a), str(b)])
    win = kami.open_paths([str(a)])
    assert win.count() == 2
    assert win.current_tab().path == str(a)


def test_a_missing_path_opens_as_a_new_file(kami, tmp_path):
    p = tmp_path / "todo.txt"
    kami.start([str(p)])
    win = kami.windows[0]
    tab = win.current_tab()
    assert tab.path == str(p) and not p.exists()
    type_into(tab, "first")
    assert win.save_tab(tab)
    assert p.read_text() == "first"


def test_a_folder_is_refused(kami, tmp_path):
    kami.start([])
    kami.open_paths([str(tmp_path)])
    assert any("is a folder" in e for e in kami.errors)


def test_closing_an_unsaved_tab_asks(kami):
    kami.start([])
    win = kami.windows[0]
    first = win.current_tab()
    type_into(first, "keep me")
    second = win.new_tab()
    type_into(second, "scratch")

    kami.answers["save"] = "cancel"
    assert not kami.close_tab(win, second)
    assert win.count() == 2

    kami.answers["save"] = "discard"
    assert kami.close_tab(win, second)
    assert win.count() == 1
    assert kami.asked == ["scratch", "scratch"]


def test_saving_on_close(kami, tmp_path):
    kami.start([])
    win = kami.windows[0]
    tab = win.current_tab()
    type_into(tab, "# Plan\n")
    win.new_tab()
    kami.answers.update(save="save", path=str(tmp_path / "plan.md"))
    assert kami.close_tab(win, tab)
    assert (tmp_path / "plan.md").read_text() == "# Plan\n"


def test_closing_the_last_tab_leaves_a_blank_one(kami):
    kami.start([])
    win = kami.windows[0]
    blank = win.current_tab()
    assert kami.close_tab(win, blank)
    assert win.tabs() == [blank]  # a blank page stays as it is

    type_into(blank, "scratch")
    kami.answers["save"] = "discard"
    assert kami.close_tab(win, blank)
    assert win in kami.windows and win.count() == 1
    assert win.current_tab() is not blank and win.current_tab().is_pristine()


def test_moving_tabs_between_windows(kami):
    kami.start([])
    one = kami.windows[0]
    keep = one.current_tab()
    moving = one.new_tab()
    two = kami.new_window(blank=False)
    two.show()

    kami.move_tab(moving.id, two)
    assert one.tabs() == [keep] and two.tabs() == [moving]

    # Moving a window's last tab away closes that window.
    kami.move_tab(keep.id, two, 0)
    assert one not in kami.windows
    assert two.tabs() == [keep, moving]


def test_reordering_within_a_window(kami):
    kami.start([])
    win = kami.windows[0]
    a = win.current_tab()
    b, c = win.new_tab(), win.new_tab()
    kami.move_tab(a.id, win, 3)  # dropped after the last tab
    assert win.tabs() == [b, c, a]
    kami.move_tab(a.id, win, 0)
    assert win.tabs() == [a, b, c]


def test_detaching_a_tab(kami):
    kami.start([])
    win = kami.windows[0]
    only = win.current_tab()
    kami.detach_tab(only.id)
    assert len(kami.windows) == 1  # a lone tab already has its own window

    second = win.new_tab()
    kami.detach_tab(second.id)
    assert len(kami.windows) == 2
    assert kami.windows[-1].tabs() == [second]
    assert win.tabs() == [only]


def test_merging_every_window(kami):
    kami.start([])
    first = kami.windows[0]
    others = [kami.new_window() for _ in range(2)]
    for w in others:
        w.show()
    kami.merge_all_into(first)
    assert kami.windows == [first]
    assert first.count() == 3


def test_unsaved_tabs_come_back(qapp, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("on disk")
    store = tmp_path / "session"

    first = make_kami(store)
    first.start([str(p)])
    win = first.windows[0]
    scratch = win.new_tab()
    type_into(scratch, "sk-live-123 for staging")
    type_into(win.tabs()[0], "edited ")
    first.save_session_now()
    dispose(first, qapp)

    second = make_kami(store)
    second.start([])
    [restored] = second.windows
    texts = {t.display_name(): (t.text(), t.needs_saving()) for t in restored.tabs()}
    assert texts == {
        "notes.txt": ("edited on disk", True),
        "sk-live-123 for staging": ("sk-live-123 for staging", True),
    }
    assert restored.current_tab().display_name() == "sk-live-123 for staging"
    dispose(second, qapp)


def test_a_vanished_file_is_dropped_on_restore(qapp, tmp_path):
    p = tmp_path / "gone.txt"
    p.write_text("x")
    store = tmp_path / "session"
    first = make_kami(store)
    first.start([str(p)])
    type_into(first.windows[0].new_tab(), "still here")
    first.save_session_now()
    dispose(first, qapp)
    p.unlink()

    second = make_kami(store)
    second.start([])
    [win] = second.windows
    assert [t.display_name() for t in win.tabs()] == ["still here"]
    assert "gone.txt" in win.statusBar().currentMessage()
    dispose(second, qapp)


def test_session_files_are_private(kami):
    kami.start([])
    type_into(kami.windows[0].current_tab(), "secret")
    kami.save_session_now()
    root = kami.store.root
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for f in [root / "session.json", *(root / "tabs").iterdir()]:
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_closing_the_last_window_keeps_everything_without_asking(kami):
    kami.start([])
    win = kami.windows[0]
    type_into(win.current_tab(), "unsaved")
    assert win.close()
    assert kami.asked == []
    [saved] = kami.store.load()
    assert kami.store.read_text(saved.tabs[0].id) == "unsaved"


def test_closing_one_of_two_windows_keeps_its_unsaved_tabs(qapp, tmp_path):
    saved = tmp_path / "saved.txt"
    saved.write_text("on disk")
    store = tmp_path / "session"
    first = make_kami(store)
    first.start([])
    other = first.new_window(blank=False)
    first.open_paths([str(saved)], other)
    type_into(other.new_tab(), "draft reply")
    other.show()

    # As when Plasma logs out: windows close one at a time, and none may ask.
    assert other.close()
    assert first.asked == []
    assert other not in first.windows
    assert first.windows[0].close()
    dispose(first, qapp)

    second = make_kami(store)
    second.start([])
    names = sorted(t.display_name() for w in second.windows for t in w.tabs())
    assert names == ["draft reply"]  # the saved file isn't reopened
    dispose(second, qapp)


def test_without_reopen_closing_one_of_two_windows_asks(kami):
    kami.config.restore_session = False
    kami.start([])
    other = kami.new_window()
    other.show()
    type_into(other.current_tab(), "draft")
    kami.answers["save"] = "cancel"
    assert not other.close()
    assert other in kami.windows
    kami.answers["save"] = "discard"
    assert other.close()
    assert other not in kami.windows


def test_without_reopen_quitting_asks_and_forgets(kami):
    kami.start([])
    type_into(kami.windows[0].current_tab(), "old session text")
    kami.save_session_now()
    assert kami.store.load()

    config = kami.config
    config.restore_session = False
    kami.apply_config(config)
    assert kami.store.load() == []  # switching it off deletes what was kept

    kami.quit_all()
    assert kami.asked == ["old session text"]
    assert kami.windows == []


def test_a_second_kami_leaves_the_session_alone(qapp, tmp_path):
    store = tmp_path / "session"
    first = make_kami(store)
    first.start([])
    type_into(first.windows[0].current_tab(), "the first Kami's note")
    first.save_session_now()
    kept = first.store.load()

    second = make_kami(store)
    second.use_session = False  # as main() makes it without the lock
    second.start([])
    assert second.windows[0].current_tab().is_pristine()  # nothing restored
    type_into(second.windows[0].current_tab(), "second")
    second.quit_all()
    assert second.asked == ["second"]
    assert first.store.load() == kept
    assert first.store.has_text(kept[0].tabs[0].id)
    dispose(second, qapp)
    dispose(first, qapp)


def test_a_later_kami_command(kami, tmp_path):
    kami.start([])
    win = kami.windows[0]
    p = tmp_path / "a.txt"
    p.write_text("a")

    kami.handle_request({"files": [str(p)], "token": None})
    assert win.current_tab().path == str(p)

    kami.handle_request({"files": [], "token": None})
    blank = win.current_tab()
    assert blank.is_pristine() and win.count() == 2
    kami.handle_request({"files": [], "token": None})
    assert win.current_tab() is blank and win.count() == 2


def test_a_later_kami_command_can_open_a_window(kami):
    kami.start([])
    kami.config.open_in = "window"
    kami.handle_request({"files": [], "token": None})
    assert len(kami.windows) == 2


def test_notepad_keys_reach_the_window_from_the_editor(kami, qapp):
    """The editor claims some key combinations for itself; none of these."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    kami.start([])
    win = kami.windows[0]
    win.activateWindow()
    qapp.processEvents()

    def press(key, mod=Qt.NoModifier):
        QTest.keyClick(win.current_tab().currentWidget(), key, mod)
        qapp.processEvents()

    ctrl, shift = Qt.ControlModifier, Qt.ShiftModifier
    QTest.keyClicks(win.current_tab().editor, "# hello")
    press(Qt.Key_V, ctrl | shift)
    assert win.current_tab().is_previewing()
    press(Qt.Key_V, ctrl | shift)
    assert not win.current_tab().is_previewing()
    press(Qt.Key_N, ctrl)
    assert win.count() == 2
    press(Qt.Key_Tab, ctrl)
    assert win.tab_bar.currentIndex() == 0
    press(Qt.Key_Equal, ctrl)
    assert win.current_tab().zoom == 110
    press(Qt.Key_0, ctrl)
    assert win.current_tab().zoom == 100
    press(Qt.Key_M, ctrl)
    assert win.menu_bar.isHidden()
    press(Qt.Key_M, ctrl)
    assert win.menu_bar.isVisible()
    press(Qt.Key_H, ctrl)
    assert win.find_bar.isVisible() and win.find_bar.replace_edit.isVisible()
    QTest.keyClick(win.find_bar.find_edit, Qt.Key_Escape)
    assert win.find_bar.isHidden()
    press(Qt.Key_Tab)
    assert "\t" in win.current_tab().text()
    press(Qt.Key_W, ctrl)
    assert kami.asked and win.count() == 1


def test_preferences_is_in_the_file_menu(kami):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    kami.start([])
    win = kami.windows[0]
    file_menu = next(m for m in win.menu_bar.findChildren(QMenu) if m.title() == "&File")
    assert win.act_prefs in file_menu.actions()
    assert win.menu_bar.cornerWidget(Qt.TopRightCorner) is None


def test_find_and_replace(kami):
    kami.start([])
    win = kami.windows[0]
    tab = win.current_tab()
    type_into(tab, "cat Cat dog")
    bar = win.find_bar
    bar.open(replace=True)
    bar.find_edit.setText("cat")
    bar.replace_edit.setText("fox")
    assert bar.replace_all() == 2
    assert tab.text() == "fox fox dog"
    tab.editor.undo()
    assert tab.text() == "cat Cat dog"
    bar.find_edit.setText("dog")
    assert bar.find()
    assert tab.editor.textCursor().selectedText() == "dog"


def test_kanji_and_kana_come_from_one_font(kami):
    from PySide6.QtGui import QFontDatabase, QTextLayout

    if not QFontDatabase.hasFamily(CJK_MONO):
        pytest.skip(f"{CJK_MONO} isn't installed")
    text = "新宿駅の南口"
    layout = QTextLayout(text, kami.editor_font())
    layout.beginLayout()
    layout.createLine().setLineWidth(1000)
    layout.endLayout()
    assert {run.rawFont().familyName() for run in layout.glyphRuns(0, len(text))} == {CJK_MONO}
