"""Kami's memory of its windows and tabs, unsaved text included.

Windows 11 Notepad keeps every tab when it closes, saved or not, and brings
them all back next time, so it works as a scratch pad that never needs
saving. Kami does the same, from one owner-only folder:

    $XDG_DATA_HOME/kami/        (~/.local/share/kami, mode 0700)
        session.json            the windows, their tabs and geometry
        tabs/<id>.txt           the text of each tab with unsaved changes

The text is stored as plain UTF-8, as Notepad stores its own. Turning off
"Reopen tabs" in Preferences empties the folder.

Every write goes to a temporary file that is renamed into place, so a crash
or a power cut leaves the previous copy rather than half of one.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = 1

# Tab ids name files in tabs/, so anything read back from session.json has
# to look like one before it goes near a path.
_TAB_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class TabState:
    id: str
    path: str | None = None
    # True when tabs/<id>.txt holds text the file on disk doesn't.
    modified: bool = False
    encoding: str = "utf-8"
    bom: bool = False
    eol: str = "\n"
    cursor: int = 0
    scroll: int = 0
    zoom: int = 100
    preview: bool = False


@dataclass
class WindowState:
    tabs: list[TabState] = field(default_factory=list)
    current: int = 0
    # QWidget.saveGeometry(), base64-encoded.
    geometry: str = ""


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME", "")
    root = Path(base) if os.path.isabs(base) else Path.home() / ".local" / "share"
    return root / "kami"


def _atomic_write(path: Path, data: bytes) -> None:
    # mkstemp creates the file 0600, which is what the session wants.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _tab_from_dict(raw) -> TabState | None:
    if not isinstance(raw, dict) or not _TAB_ID.match(str(raw.get("id", ""))):
        return None
    path = raw.get("path")
    eol = raw.get("eol", "\n")
    try:
        return TabState(
            id=raw["id"],
            path=path if isinstance(path, str) and os.path.isabs(path) else None,
            modified=bool(raw.get("modified", False)),
            encoding=str(raw.get("encoding", "utf-8")),
            bom=bool(raw.get("bom", False)),
            eol=eol if eol in ("\n", "\r\n", "\r") else "\n",
            cursor=max(0, int(raw.get("cursor", 0))),
            scroll=max(0, int(raw.get("scroll", 0))),
            zoom=max(10, min(500, int(raw.get("zoom", 100)))),
            preview=bool(raw.get("preview", False)),
        )
    except (TypeError, ValueError):
        return None


class SessionStore:
    """Reads and writes the session folder. Owns no Qt objects."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()

    @property
    def _tabs_dir(self) -> Path:
        return self.root / "tabs"

    def _text_path(self, tab_id: str) -> Path:
        if not _TAB_ID.match(tab_id):
            raise ValueError(f"not a tab id: {tab_id!r}")
        return self._tabs_dir / f"{tab_id}.txt"

    def _ensure_dirs(self) -> None:
        for d in (self.root, self._tabs_dir):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
            # mkdir's mode is ignored for a folder that already exists,
            # and is masked by the umask for one that doesn't.
            os.chmod(d, 0o700)

    # -- Windows and tabs ----------------------------------------------

    def load(self) -> list[WindowState]:
        """The saved windows; empty if there are none or the file is unreadable."""
        try:
            raw = json.loads((self.root / "session.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable session.json: %s", exc)
            return []
        if not isinstance(raw, dict) or not isinstance(raw.get("windows"), list):
            return []

        windows = []
        for w in raw["windows"]:
            if not isinstance(w, dict) or not isinstance(w.get("tabs"), list):
                continue
            tabs = [t for t in (_tab_from_dict(t) for t in w["tabs"]) if t is not None]
            if not tabs:
                continue
            try:
                current = int(w.get("current", 0))
            except (TypeError, ValueError):
                current = 0
            geometry = w.get("geometry", "")
            windows.append(WindowState(
                tabs=tabs,
                current=max(0, min(current, len(tabs) - 1)),
                geometry=geometry if isinstance(geometry, str) else "",
            ))
        return windows

    def save(self, windows: list[WindowState]) -> None:
        self._ensure_dirs()
        body = {"schema": SCHEMA, "windows": [asdict(w) for w in windows]}
        _atomic_write(self.root / "session.json", json.dumps(body, indent=1).encode("utf-8"))

    # -- Unsaved text --------------------------------------------------

    def write_text(self, tab_id: str, text: str) -> None:
        self._ensure_dirs()
        _atomic_write(self._text_path(tab_id), text.encode("utf-8"))

    def has_text(self, tab_id: str) -> bool:
        try:
            return self._text_path(tab_id).is_file()
        except ValueError:
            return False

    def read_text(self, tab_id: str) -> str | None:
        try:
            return self._text_path(tab_id).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None

    def discard_text(self, tab_id: str) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._text_path(tab_id).unlink()

    def prune(self, keep: set[str]) -> None:
        """Delete the stored text of every tab not in `keep`."""
        if not self._tabs_dir.is_dir():
            return
        for f in self._tabs_dir.glob("*.txt"):
            if f.stem not in keep:
                with contextlib.suppress(OSError):
                    f.unlink()

    def clear(self) -> None:
        """Forget everything: the session and every stored text."""
        self.prune(set())
        with contextlib.suppress(OSError):
            (self.root / "session.json").unlink()
