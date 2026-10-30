"""Kami — a tabbed notepad for plain text and Markdown.

`kami [FILE…]` opens the files as tabs. If Kami is already running, the
running Kami opens them (or a fresh tab, given no files) and this process
exits straight away; see `kami.core.instance`.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import time
import traceback
from pathlib import Path

from kami.core import instance

log = logging.getLogger("kami")

# How long to keep knocking when another Kami holds the lock but isn't
# listening yet: one that is still starting up.
_STARTUP_WAIT_S = 3.0


def _excepthook(et, ev, tb) -> None:
    traceback.print_exception(et, ev, tb)
    log.error("uncaught exception", exc_info=(et, ev, tb))


def _files_from(args: list[str]) -> list[str]:
    """File arguments, as absolute paths. Options are ignored, except that
    everything after `--` counts as a file."""
    files, rest = [], False
    for arg in args:
        if rest:
            files.append(arg)
        elif arg == "--":
            rest = True
        elif not arg.startswith("-"):
            files.append(arg)
    return [os.path.abspath(f) for f in files]


def main() -> None:
    faulthandler.enable()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(process)d %(name)s: %(message)s",
    )
    sys.excepthook = _excepthook

    files = _files_from(sys.argv[1:])
    request = instance.make_request(files, os.environ.get("XDG_ACTIVATION_TOKEN"))

    lock_fd = None
    deadline = time.monotonic() + _STARTUP_WAIT_S
    while True:
        if instance.send_request(request):
            log.info("handed %d file(s) to the running Kami", len(files))
            return
        lock_fd = instance.try_lock()
        if lock_fd is not None:
            break
        if time.monotonic() > deadline:
            log.warning("another Kami holds the lock but isn't answering; starting anyway")
            break
        time.sleep(0.1)

    _run(files, listen=lock_fd is not None)


def _run(files: list[str], listen: bool) -> None:
    log.info("starting; argv=%r; cwd=%s", sys.argv, os.getcwd())

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Kami")
    app.setOrganizationName("kami")
    # The Wayland app_id; it has to match the installed kami.desktop, or
    # in the Flatpak, the desktop entry and icon named for the app ID.
    app_id = os.environ.get("FLATPAK_ID", "kami")
    app.setDesktopFileName(app_id)

    # By theme name, so KWin draws the icon itself from the copy that
    # desktop/install.sh puts in hicolor (see Pepper's main.py for why).
    # The bundled file is the fallback when not installed.
    icon_path = Path(__file__).parent / "resources" / "kami.svg"
    app.setWindowIcon(QIcon.fromTheme(app_id, QIcon(str(icon_path))))

    # Imported here so logging is configured before any UI module loads.
    from kami.core.listener import InstanceListener
    from kami.ui.app import Kami

    kami = Kami(use_session=listen)
    if listen:
        listener = InstanceListener(instance.socket_path(), app)
        listener.request_received.connect(kami.handle_request)
    else:
        log.warning("running without the session, which the other Kami owns")
    kami.start(files)

    ret = app.exec()
    os._exit(ret)


if __name__ == "__main__":
    main()
