from __future__ import annotations

import os
import threading
import time

import pytest

from kami.core.instance import (
    decode_request,
    encode_request,
    make_request,
    send_request,
    socket_path,
    try_lock,
)
from kami.main import _files_from


def test_request_round_trip():
    request = make_request(["notes.md"], "token-1")
    assert decode_request(encode_request(request).rstrip(b"\n")) == {
        "files": [os.path.abspath("notes.md")], "token": "token-1",
    }


@pytest.mark.parametrize("raw", [
    b"not json",
    b"[]",
    b'{"files": "a.txt"}',
    b'{"files": ["relative.txt"]}',
    b'{"files": [], "token": 5}',
    b"\xff\xfe",
])
def test_bad_requests_are_refused(raw):
    assert decode_request(raw) is None


def test_the_lock_is_exclusive(tmp_path):
    path = str(tmp_path / "kami.lock")
    fd = try_lock(path)
    assert fd is not None
    assert try_lock(path) is None
    os.close(fd)
    again = try_lock(path)
    assert again is not None
    os.close(again)


def test_socket_lives_in_the_runtime_dir(isolated_paths):
    assert socket_path() == str(isolated_paths / "runtime" / "kami.sock")


def test_a_long_runtime_dir_falls_back_to_tmp(tmp_path, monkeypatch):
    import kami.core.instance as inst

    deep = tmp_path / ("d" * 60) / ("e" * 60)
    deep.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(deep))
    monkeypatch.setattr(inst, "_SHORT_ROOT", tmp_path)  # stands in for /tmp
    assert socket_path() == str(tmp_path / f"kami-{os.getuid()}" / "kami.sock")


def test_nothing_listening(tmp_path):
    assert send_request(make_request([]), str(tmp_path / "none.sock"), timeout=0.2) is False


def _send_while_pumping(qapp, path, request) -> bool:
    """send_request blocks until the listener answers, and the listener
    needs Qt's event loop, so send from a thread and pump events here."""
    result = {}
    sender = threading.Thread(target=lambda: result.update(ok=send_request(request, path)))
    sender.start()
    deadline = time.monotonic() + 5
    while sender.is_alive() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    sender.join(1)
    for _ in range(5):
        qapp.processEvents()
    return result.get("ok", False)


def test_the_running_kami_receives_requests(qapp, tmp_path):
    from kami.core.listener import InstanceListener

    path = str(tmp_path / "k.sock")
    listener = InstanceListener(path)
    assert listener.is_listening()
    received = []
    listener.request_received.connect(received.append)

    assert _send_while_pumping(qapp, path, make_request(["/tmp/x.md"], "t"))
    assert received == [{"files": ["/tmp/x.md"], "token": "t"}]


def test_a_stale_socket_file_is_replaced(qapp, tmp_path):
    from kami.core.listener import InstanceListener

    path = tmp_path / "k.sock"
    path.write_text("left behind by a crash")
    listener = InstanceListener(str(path))
    assert listener.is_listening()


def test_file_arguments():
    assert _files_from(["a.txt", "-x", "--", "-dash.txt"]) == [
        os.path.abspath("a.txt"), os.path.abspath("-dash.txt"),
    ]
