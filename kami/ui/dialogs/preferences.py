"""Kami preferences — the suite's Window group, plus Editor and Tabs."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kami.core.config import AppConfig, save_config
from kami.core.session import data_dir
from kami.ui.widgets.appearance_group import AppearanceGroup

_OPEN_IN_OPTIONS = [
    ("tab", "A new tab in the last window used"),
    ("window", "A new window"),
]


class PreferencesDialog(QDialog):
    """Emits settings_changed with the new AppConfig after Apply or OK."""

    settings_changed = Signal(object)

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(380)
        self._config = copy.deepcopy(config)
        self._font_family = config.font_family
        self._font_size = config.font_size
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._appearance = AppearanceGroup(self._config.appearance)
        layout.addWidget(self._appearance)

        editor = QGroupBox("Editor")
        editor_form = QFormLayout(editor)
        self._font_btn = QPushButton()
        self._font_btn.clicked.connect(self._pick_font)
        reset = QPushButton("Use system font")
        reset.clicked.connect(self._reset_font)
        font_row = QHBoxLayout()
        font_row.addWidget(self._font_btn, 1)
        font_row.addWidget(reset)
        editor_form.addRow("Font:", font_row)
        self._update_font_btn()
        self._wrap_cb = QCheckBox("Wrap long lines to the window")
        self._wrap_cb.setChecked(self._config.word_wrap)
        editor_form.addRow(self._wrap_cb)
        layout.addWidget(editor)

        tabs = QGroupBox("Tabs")
        tabs_form = QFormLayout(tabs)
        self._restore_cb = QCheckBox("Reopen tabs from last time, unsaved ones included")
        self._restore_cb.setChecked(self._config.restore_session)
        tabs_form.addRow(self._restore_cb)
        note = QLabel(
            f"Unsaved text is kept in {_home_relative(str(data_dir()))}, which only "
            "your account can read. Turning this off deletes it."
        )
        note.setWordWrap(True)
        note.setEnabled(False)  # Drawn in the style's muted colour.
        tabs_form.addRow(note)
        self._open_in_combo = QComboBox()
        for _, label in _OPEN_IN_OPTIONS:
            self._open_in_combo.addItem(label)
        keys = [key for key, _ in _OPEN_IN_OPTIONS]
        self._open_in_combo.setCurrentIndex(keys.index(self._config.open_in))
        tabs_form.addRow("When Kami is already open, kami opens:", self._open_in_combo)
        layout.addWidget(tabs)
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        layout.addWidget(buttons)

    def _current_font(self) -> QFont:
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        if self._font_family:
            font.setFamilies([self._font_family])
        if self._font_size > 0:
            font.setPointSizeF(self._font_size)
        return font

    def _update_font_btn(self) -> None:
        font = self._current_font()
        if self._font_family or self._font_size > 0:
            self._font_btn.setText(f"{font.family()}, {font.pointSizeF():g} pt")
        else:
            self._font_btn.setText(f"System fixed-width ({font.family()}, {font.pointSizeF():g} pt)")
        self._font_btn.setFont(font)

    def _pick_font(self) -> None:
        result = QFontDialog.getFont(self._current_font(), self, "Editor Font")
        # PySide6 has returned both (ok, font) and (font, ok) over the years.
        ok, font = result if isinstance(result[0], bool) else (result[1], result[0])
        if ok:
            self._font_family = font.family()
            self._font_size = font.pointSizeF()
            self._update_font_btn()

    def _reset_font(self) -> None:
        self._font_family = ""
        self._font_size = 0.0
        self._update_font_btn()

    def _apply_to_config(self) -> None:
        self._appearance.apply_to_config()
        self._config.font_family = self._font_family
        self._config.font_size = self._font_size
        self._config.word_wrap = self._wrap_cb.isChecked()
        self._config.restore_session = self._restore_cb.isChecked()
        self._config.open_in = _OPEN_IN_OPTIONS[self._open_in_combo.currentIndex()][0]

    def _on_apply(self) -> None:
        self._apply_to_config()
        save_config(self._config)
        self.settings_changed.emit(copy.deepcopy(self._config))

    def _on_ok(self) -> None:
        self._on_apply()
        self.accept()


def _home_relative(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + "/") else path
