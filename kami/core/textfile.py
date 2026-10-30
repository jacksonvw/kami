"""Reading and writing text files the way Notepad does.

A file keeps the encoding and line endings it was opened with, so a
Windows file saved from Kami goes back with its CRLFs and its BOM. Inside
the editor every line ends in a plain "\\n"; `encode` puts the file's own
endings back.

New files are UTF-8 with LF endings. A file that isn't valid UTF-8 and has
no BOM is read as Windows-1252, which is what an old Windows .txt almost
always is. Five bytes are undefined in Windows-1252; a file containing one
falls back to Latin-1, which can decode anything.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

# QPlainTextEdit copes with more, but an unsaved buffer is copied to the
# session folder a second after each edit, and a scratch pad has no
# business holding a database dump.
MAX_BYTES = 32 * 1024 * 1024

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

_ENCODING_LABELS = {
    "utf-8": "UTF-8",
    "utf-16-le": "UTF-16 LE",
    "utf-16-be": "UTF-16 BE",
    "cp1252": "Windows-1252",
    "latin-1": "ISO-8859-1",
}

_EOL_LABELS = {"\n": "Unix (LF)", "\r\n": "Windows (CRLF)", "\r": "Macintosh (CR)"}


class FileTooLarge(Exception):
    """Raised by `read_file` for anything over MAX_BYTES."""


@dataclass
class TextFormat:
    """How a file is stored on disk: its encoding, BOM and line endings."""
    encoding: str = "utf-8"
    bom: bool = False
    eol: str = "\n"

    @property
    def encoding_label(self) -> str:
        if self.bom and self.encoding == "utf-8":
            return "UTF-8 with BOM"
        return _ENCODING_LABELS.get(self.encoding, self.encoding)

    @property
    def eol_label(self) -> str:
        return _EOL_LABELS.get(self.eol, _EOL_LABELS["\n"])


def detect_eol(text: str) -> str:
    """The commonest line ending in `text`; LF when there are none."""
    crlf = text.count("\r\n")
    counts = {
        "\r\n": crlf,
        "\n": text.count("\n") - crlf,
        "\r": text.count("\r") - crlf,
    }
    eol = max(counts, key=counts.get)
    return eol if counts[eol] else "\n"


def decode(data: bytes) -> tuple[str, TextFormat]:
    """Bytes from disk to editor text (LF endings) plus the format to save with."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            text = data[len(bom):].decode(encoding, errors="replace")
            has_bom = True
            break
    else:
        has_bom = False
        for encoding in ("utf-8", "cp1252", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    eol = detect_eol(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, TextFormat(encoding=encoding, bom=has_bom, eol=eol)


def encode(text: str, fmt: TextFormat) -> bytes:
    """Editor text to bytes in `fmt`. Raises UnicodeEncodeError if it can't fit."""
    if fmt.eol != "\n":
        text = text.replace("\n", fmt.eol)
    data = text.encode(fmt.encoding)
    if fmt.bom:
        data = next(bom for bom, enc in _BOMS if enc == fmt.encoding) + data
    return data


def read_file(path: str | os.PathLike) -> tuple[str, TextFormat]:
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise FileTooLarge(f"{p.name} is over {MAX_BYTES // (1024 * 1024)} MB")
    return decode(p.read_bytes())


def write_file(path: str | os.PathLike, text: str, fmt: TextFormat) -> TextFormat:
    """Save `text` to `path` in `fmt`, and return the format actually used.

    That is `fmt` unless the text no longer fits the file's encoding (a
    Windows-1252 file that has gained an emoji): then it is saved as UTF-8,
    which holds anything, and the returned format says so.

    The save is atomic: the bytes go to a temporary file beside the target,
    which is then renamed over it, so a crash mid-save leaves the old file
    whole. The new file takes the old one's permissions, and a symlink is
    followed so the link itself survives. When the folder isn't writable
    (a file you may edit in a folder you may not) it writes in place.
    """
    try:
        data = encode(text, fmt)
    except UnicodeEncodeError:
        fmt = TextFormat(encoding="utf-8", bom=False, eol=fmt.eol)
        data = encode(text, fmt)

    target = Path(os.path.realpath(path))
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = _default_mode()

    try:
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".kami")
    except PermissionError:
        with open(target, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return fmt

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return fmt


def _default_mode() -> int:
    """The permissions a brand-new file gets: 0666 less the umask."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask
