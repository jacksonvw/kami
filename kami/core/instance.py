"""One Kami per desktop session.

Typing `kami notes.md` while Kami is open should add a tab to the open
window, the way Notepad opens files in its existing window, rather than
start a second copy with its own idea of the session. So the first Kami
listens on a Unix socket (`kami.core.listener`), and each later `kami`
hands its request over and exits.

This half is plain Python and runs before PySide6 is imported, so a
forwarded `kami` is done in a few milliseconds. The first Kami holds an
flock on kami.lock for as long as it runs. The kernel drops that lock when
the process dies, so a crash never leaves a stale one behind.

The request is one line of JSON: the files (absolute paths) and, when the
launcher supplied one, the XDG activation token. On Wayland a window can
only bring itself to the front with a token from whatever the user just
clicked or typed in, so the token travels with the request.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import tempfile
from pathlib import Path

# Generous: a request is a list of paths.
MAX_REQUEST_BYTES = 1024 * 1024

_SUN_PATH_MAX = 107
_SHORT_ROOT = Path("/tmp")


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR", "")
    if os.path.isabs(base) and os.path.isdir(base):
        return Path(base)
    # No per-user runtime folder: make a private one in /tmp.
    d = Path(tempfile.gettempdir()) / f"kami-{os.getuid()}"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def socket_path() -> str:
    path = runtime_dir() / "kami.sock"
    # A Unix socket's name must fit in 108 bytes, terminator included. The
    # usual /run/user/1000 is far inside that; a long XDG_RUNTIME_DIR isn't.
    if len(os.fsencode(path)) > _SUN_PATH_MAX:
        short = _SHORT_ROOT / f"kami-{os.getuid()}"
        short.mkdir(mode=0o700, exist_ok=True)
        path = short / "kami.sock"
    return str(path)


def lock_path() -> str:
    return str(runtime_dir() / "kami.lock")


def make_request(files: list[str], token: str | None = None) -> dict:
    return {"files": [os.path.abspath(f) for f in files], "token": token or None}


def encode_request(request: dict) -> bytes:
    return json.dumps(request).encode("utf-8") + b"\n"


def decode_request(data: bytes) -> dict | None:
    """Parse and check one request line; None if it isn't a valid request."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    files = raw.get("files", [])
    token = raw.get("token")
    if not isinstance(files, list) or not all(
        isinstance(f, str) and os.path.isabs(f) for f in files
    ):
        return None
    if token is not None and not isinstance(token, str):
        return None
    return {"files": files, "token": token}


def send_request(request: dict, path: str | None = None, timeout: float = 2.0) -> bool:
    """Hand `request` to a running Kami. False if none is listening."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path or socket_path())
            s.sendall(encode_request(request))
            # Wait for the reply, so this process can't exit before the
            # running Kami has read the whole request.
            return s.recv(16).startswith(b"ok")
    except OSError:
        return False


def try_lock(path: str | None = None) -> int | None:
    """Take the single-instance lock. Returns its fd (keep it open), or None."""
    fd = os.open(path or lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd
