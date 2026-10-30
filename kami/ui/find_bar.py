"""Find and Replace, in a bar above the page.

Ctrl+F opens it to find and Ctrl+H to replace, as in Notepad. Enter finds
the next match and Shift+Enter the previous one; the search wraps around
the end of the text. Esc closes the bar.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)


class FindBar(QWidget):
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("findBar")
        self._editor = None

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setClearButtonEnabled(True)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace with")

        self._prev_btn = self._button("↑", "Previous match (Shift+F3)", lambda: self.find(backward=True))
        self._next_btn = self._button("↓", "Next match (F3)", self.find)
        self._case_btn = self._button("Aa", "Match case", None)
        self._case_btn.setCheckable(True)
        self._close_btn = self._button("✕", "Close (Esc)", self.close_bar)
        self._replace_btn = self._button("Replace", "Replace this match", self.replace)
        self._replace_all_btn = self._button("Replace all", "Replace every match", self.replace_all)
        self._status = QLabel("")

        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        grid.addWidget(self.find_edit, 0, 0)
        row0 = QHBoxLayout()
        for w in (self._prev_btn, self._next_btn, self._case_btn, self._status):
            row0.addWidget(w)
        row0.addStretch(1)
        row0.addWidget(self._close_btn)
        grid.addLayout(row0, 0, 1)
        grid.addWidget(self.replace_edit, 1, 0)
        row1 = QHBoxLayout()
        row1.addWidget(self._replace_btn)
        row1.addWidget(self._replace_all_btn)
        row1.addStretch(1)
        grid.addLayout(row1, 1, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)

        # Shift+Enter is caught before QLineEdit sees it, since QLineEdit
        # emits returnPressed for it too and the bar would search both ways.
        self.find_edit.installEventFilter(self)
        self.find_edit.returnPressed.connect(self.find)
        self.replace_edit.returnPressed.connect(self.replace)
        self.find_edit.textEdited.connect(self._find_as_you_type)
        self._case_btn.toggled.connect(lambda _: self._status.setText(""))

    def _button(self, text: str, tip: str, slot) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        if slot is not None:
            btn.clicked.connect(slot)
        return btn

    def _set_replace_visible(self, visible: bool) -> None:
        for w in (self.replace_edit, self._replace_btn, self._replace_all_btn):
            w.setVisible(visible)

    def set_editor(self, editor) -> None:
        self._editor = editor
        self._status.setText("")

    def open(self, replace: bool = False) -> None:
        self._set_replace_visible(replace)
        if self._editor is not None:
            selected = self._editor.textCursor().selectedText()
            # A selection on one line seeds the search, as in Notepad.
            if selected and " " not in selected:
                self.find_edit.setText(selected)
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_bar(self) -> None:
        self.hide()
        self.closed.emit()

    def _flags(self, backward: bool = False) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self._case_btn.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def find(self, backward: bool = False) -> bool:
        """Select the next (or previous) match, wrapping around the ends."""
        needle = self.find_edit.text()
        editor = self._editor
        if not needle or editor is None:
            return False
        flags = self._flags(backward)
        found = editor.find(needle, flags)
        if not found:
            cur = editor.textCursor()
            cur.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            editor.setTextCursor(cur)
            found = editor.find(needle, flags)
        self._status.setText("" if found else "No results")
        return found

    def _find_as_you_type(self, _text: str) -> None:
        # Search again from the start of the current match, so typing
        # more of a word keeps the same match selected while it fits.
        if self._editor is not None:
            cur = self._editor.textCursor()
            cur.setPosition(cur.selectionStart())
            self._editor.setTextCursor(cur)
        if self.find_edit.text():
            self.find()
        else:
            self._status.setText("")

    def _selection_matches(self) -> bool:
        selected = self._editor.textCursor().selectedText()
        needle = self.find_edit.text()
        if self._case_btn.isChecked():
            return selected == needle
        return selected.casefold() == needle.casefold()

    def replace(self) -> None:
        """Replace the selected match, if it is one, and select the next."""
        if self._editor is None or not self.find_edit.text():
            return
        if self._selection_matches():
            self._editor.textCursor().insertText(self.replace_edit.text())
        self.find()

    def replace_all(self) -> int:
        """Replace every match as one undo step. Returns how many."""
        needle = self.find_edit.text()
        if self._editor is None or not needle:
            return 0
        doc = self._editor.document()
        flags = self._flags()
        replacement = self.replace_edit.text()
        count = 0
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        found = doc.find(needle, 0, flags)
        while not found.isNull():
            found.insertText(replacement)
            count += 1
            found = doc.find(needle, found, flags)
        edit.endEditBlock()
        self._status.setText(f"Replaced {count}" if count else "No results")
        return count

    def eventFilter(self, obj, ev) -> bool:
        if (
            obj is self.find_edit
            and ev.type() == QEvent.KeyPress
            and ev.key() in (Qt.Key_Return, Qt.Key_Enter)
            and ev.modifiers() & Qt.ShiftModifier
        ):
            self.find(backward=True)
            return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self.close_bar()
            ev.accept()
            return
        super().keyPressEvent(ev)
