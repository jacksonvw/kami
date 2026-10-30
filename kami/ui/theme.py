"""Kami's look: the one Quaver, Pepper and Semibreve wear when translucent.

The window paints its colour, solid at full opacity or as a tint over
KWin's blur below it, and the stylesheet is the one the other apps switch to
when translucent: white text and faint white fills over that colour. Kami
keeps it at full opacity too. The others drop to the desktop's own style
there, but in Kami that draws the menu bar as a grey band, the page as a
separate panel and the status bar as boxes, where the rest is one colour.
The tab strip carries Quaver's own tab rules as well (see `kami.ui.tabbar`).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette

from kami.core.config import AppearanceConfig


@dataclass(frozen=True)
class Theme:
    translucent: bool   # the page lets the desktop (and blur) through
    paper: QColor       # what the window paints, alpha included
    text: QColor        # the preview's text
    muted: QColor       # quotes and the smallest headings
    rule: QColor        # rules under headings, table borders, quote bars
    tint: QColor        # code backgrounds
    link: QColor
    dark: bool          # Dark+ code colours rather than Light+
    glyph: QColor       # the tab strip's × and +
    glyph_hot: QColor   # ... under the pointer
    glyph_fill: QColor  # ... and the fill behind them then


def _white(alpha: int) -> QColor:
    return QColor(255, 255, 255, alpha)


def theme_for(appearance: AppearanceConfig, palette: QPalette) -> Theme:
    r, g, b = appearance.bg_color
    translucent = appearance.window_opacity < 1.0
    if translucent:
        # Pepper's and Semibreve's arithmetic, step for step, so the same
        # settings give the same alpha: the tint strength scaled by the opacity.
        tint_alpha = int(appearance.bg_tint_strength * 255 / 100)
        alpha = int(tint_alpha * int(appearance.window_opacity * 255) / 255)
    else:
        alpha = 255
    # The colours of STYLESHEET's text views and tabs.
    return Theme(
        translucent=translucent, paper=QColor(r, g, b, alpha),
        text=_white(190), muted=_white(150), rule=_white(40), tint=_white(18),
        link=palette.color(QPalette.Link), dark=True,
        glyph=_white(180), glyph_hot=_white(255), glyph_fill=_white(12),
    )


# Quaver's transparent stylesheet, with Pepper's menus and status bar and
# Semibreve's drop-down lists, for the widgets Kami has. Like theirs it's
# set on the main window, so it reaches its dialogs too.
STYLESHEET = """
    QMainWindow, QWidget#central, QStackedWidget
    { background: transparent; }

    /* As in Notepad, the menu bar and the status bar are set off from the
       page by a line, and every row starts 12px in, as the tabs' titles do. */
    QMenuBar
    { background: transparent; color: rgba(255, 255, 255, 200);
      border-bottom: 1px solid rgba(255, 255, 255, 20); }
    QMenuBar::item
    { background: transparent; padding: 6px 12px; }
    QMenuBar::item:selected, QMenuBar::item:pressed
    { background: rgba(255, 255, 255, 12); }

    QTabBar
    { background: transparent; }
    QTabBar::tab
    { background: rgba(255, 255, 255, 8); color: rgba(255, 255, 255, 180);
      padding: 6px 12px; border-bottom: 2px solid transparent; }
    QTabBar::tab:selected
    { background: rgba(255, 255, 255, 18);
      border-bottom: 2px solid palette(highlight); color: white; }
    QTabBar::tab:hover:!selected
    { background: rgba(255, 255, 255, 12); }

    QPlainTextEdit, QTextBrowser
    { background: rgba(0, 0, 0, 20); border: none;
      color: rgba(255, 255, 255, 190); }

    QScrollBar:vertical, QScrollBar:horizontal
    { background: transparent; width: 8px; height: 8px; }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal
    { background: rgba(255, 255, 255, 40); border-radius: 4px;
      min-height: 20px; min-width: 20px; }
    QScrollBar::handle:hover
    { background: rgba(255, 255, 255, 60); }
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page
    { background: transparent; height: 0; width: 0; }

    QLabel
    { background: transparent; color: rgba(255, 255, 255, 200); }

    QPushButton
    { background: rgba(255, 255, 255, 12); color: rgba(255, 255, 255, 200);
      border: 1px solid rgba(255, 255, 255, 20); padding: 4px 8px;
      border-radius: 3px; }
    QPushButton:hover
    { background: rgba(255, 255, 255, 25); }
    QPushButton:pressed
    { background: rgba(255, 255, 255, 8); }
    QPushButton:checked
    { background: rgba(255, 255, 255, 30);
      border-color: rgba(255, 255, 255, 40); }
    QPushButton:flat
    { border: none; }

    QCheckBox
    { background: transparent; color: rgba(255, 255, 255, 200);
      spacing: 6px; }
    QCheckBox::indicator
    { width: 16px; height: 16px;
      border: 1px solid rgba(255, 255, 255, 60);
      border-radius: 3px; background: rgba(0, 0, 0, 40); }
    QCheckBox::indicator:checked
    { background: palette(highlight);
      border-color: palette(highlight); }

    QComboBox
    { background: rgba(255, 255, 255, 12); color: rgba(255, 255, 255, 210);
      border: 1px solid rgba(255, 255, 255, 20); padding: 3px 8px;
      border-radius: 3px; }
    QComboBox QAbstractItemView
    { background: rgba(40, 40, 40, 240); color: rgba(255, 255, 255, 220);
      selection-background-color: rgba(255, 255, 255, 30); }

    QStatusBar
    { background: transparent; color: rgba(255, 255, 255, 200);
      border-top: 1px solid rgba(255, 255, 255, 20); }
    QStatusBar::item
    { border: none; }
    QStatusBar QLabel
    { padding: 3px 12px; }
    /* QStatusBar sets its first field 7px in already. */
    QStatusBar QLabel#position
    { padding-left: 5px; }

    QMenu
    { background: rgba(40, 40, 40, 230); color: rgba(255, 255, 255, 220);
      border: 1px solid rgba(255, 255, 255, 30); }
    QMenu::item:selected
    { background: rgba(255, 255, 255, 25); }
"""


def stylesheet(t: Theme) -> str:
    """The main window's stylesheet, the same at every opacity."""
    return STYLESHEET
