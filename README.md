# Kami

A tabbed notepad for plain text and Markdown on the Linux desktop.

Kami (紙, Japanese for paper) is the Windows 11 Notepad I missed after moving
to Fedora: a scratch pad for notes, keys and drafts that opens instantly and
never makes you save. Close it whenever you like and every tab comes back
next time, unsaved ones included. KWrite does far more, but it's heavier,
and it opens with a welcome screen. Kami is a page, a few tabs and a menu
bar. It is a text editor, not a word processor.

## Features

- Tabs, which you can drag out into a window of their own and drop onto
  another Kami window to bring them back; a tab's menu does the same, and
  File → Merge All Windows Here gathers everything into one window
- Keeps every tab between runs, as Notepad does, with the unsaved text in a
  folder only your account can read; it can be turned off in Preferences
- An unsaved tab is named after its first line, so a row of scratch tabs
  reads "API keys", "Call list", "Draft reply"
- A Markdown preview on Ctrl+Shift+V, styled after VS Code's: headings,
  task lists, tables, quotes, links, images and colour-coded code blocks
- Opens a file in its own encoding and line endings and saves it the same
  way, so Windows files keep their CRLFs (UTF-8, UTF-16 and Windows-1252)
- One Kami at a time: `kami notes.md` in a terminal adds a tab to the open
  window and hands the prompt straight back
- Notepad's menus and keys, Find and Replace, Go To, F5 for the time and date
- The suite's translucent window with KWin's blur behind it, on Wayland and X11

## Status

Working on Fedora 44 with KDE Plasma 6 on Wayland, run from a checkout.
Missing: a Flatpak, and a choice of encoding or line endings when saving.

## Built with

Python 3 and PySide6 (Qt 6), taken from Fedora's RPMs so the window runs on
Plasma's own Qt, as Pepper and Minim do. Qt reads the Markdown and draws the
preview itself, with no web engine, and Pygments colours the code in it.
KWindowSystem, called through ctypes, provides the blur.

| Directory | What it is |
|---|---|
| `kami/core/` | Files, settings, the session and the single-instance socket; no widgets |
| `kami/ui/` | The window, tabs, editor, preview and Preferences |
| `desktop/` | The launcher's desktop entry and the install script |

## Build and run

Tested on Fedora 44 with KDE Plasma 6 on Wayland.

```bash
sudo dnf install -y \
    python3-pyside6 qt6-qtwayland kf6-kwindowsystem \
    python3-pygments python3-pytest

git clone https://github.com/jacksonvw/kami.git
cd kami
bin/kami notes.md
```

Everything runs on the system Python against Fedora RPMs, deliberately with
no venv, which is why the launcher pins `/usr/bin/python3`.

| Package | Provides |
|---|---|
| `qt6-qtwayland` | A native Wayland window rather than XWayland |
| `kf6-kwindowsystem` | KWin blur-behind; without it the blur is skipped |
| `python3-pygments` | Colours in the preview's code blocks; without it they're plain |
| `python3-pytest` | The test suite |

`desktop/install.sh` links `bin/kami` into `~/bin`, installs the desktop
entry and icon, and makes Kami the default for plain text and Markdown. After
that, Ctrl+Alt+T and `kami` opens it, and typing "notepad", "note" or "memo"
into the app launcher finds it. The script needs no root and is safe to
re-run, including after moving the checkout.

| Key | |
|---|---|
| Ctrl+N / Ctrl+Shift+N | New tab / new window |
| Ctrl+O, Ctrl+S, Ctrl+Shift+S | Open, Save, Save As |
| Ctrl+W / Ctrl+Shift+W | Close tab / close window |
| Ctrl+Tab, Ctrl+Shift+Tab | Next and previous tab (Ctrl+PgDown and Ctrl+PgUp too) |
| Ctrl+Shift+V | Markdown preview |
| Ctrl+F, F3, Shift+F3 | Find, next, previous |
| Ctrl+H | Replace |
| Ctrl+G | Go to line |
| F5 | Insert the time and date |
| Ctrl+= / Ctrl+- / Ctrl+0 | Zoom in, out, back to 100% (Ctrl+wheel zooms too) |
| Ctrl+M | Hide or show the menu bar |
| Ctrl+, | Preferences |
| F11 | Full screen |
| Ctrl+Q | Quit, keeping every tab |

Middle-click closes a tab, and double-clicking the empty tab strip opens one.

Settings live in `~/.config/kami/`. The tabs Kami keeps, with their unsaved
text, are in `~/.local/share/kami/`, readable only by you. Logs go to
`/tmp/kami.log`.

The tests run headless, on Qt's offscreen platform:

```bash
/usr/bin/python3 -m pytest
```

---

Jackson Vander Wal · [jacksonv.com](https://jacksonv.com)
