"""The running Kami's end of the single-instance socket.

See `kami.core.instance` for the protocol and the client side.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from kami.core.instance import MAX_REQUEST_BYTES, decode_request

log = logging.getLogger(__name__)


class InstanceListener(QObject):
    """Listens on the socket and emits each request it receives."""

    request_received = Signal(dict)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        # A socket file left by a Kami that crashed. Safe to remove: the
        # caller holds the lock, so no live Kami can be listening on it.
        QLocalServer.removeServer(path)
        if not self._server.listen(path):
            log.warning("can't listen on %s: %s", path, self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)
        self._buffers: dict[QLocalSocket, bytearray] = {}

    def is_listening(self) -> bool:
        return self._server.isListening()

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._forget(s))

    def _on_ready_read(self, sock: QLocalSocket) -> None:
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf += bytes(sock.readAll().data())
        if b"\n" not in buf:
            if len(buf) > MAX_REQUEST_BYTES:
                sock.abort()
            return
        line = bytes(buf).split(b"\n", 1)[0]
        request = decode_request(line)
        sock.write(b"ok\n" if request is not None else b"bad\n")
        sock.flush()
        sock.disconnectFromServer()
        if request is None:
            log.warning("ignoring a malformed request")
            return
        self.request_received.emit(request)

    def _forget(self, sock: QLocalSocket) -> None:
        self._buffers.pop(sock, None)
        sock.deleteLater()
