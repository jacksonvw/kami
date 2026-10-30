from __future__ import annotations

import os
import stat

import pytest

import kami.core.textfile as textfile
from kami.core.textfile import (
    FileTooLarge,
    TextFormat,
    decode,
    detect_eol,
    encode,
    read_file,
    write_file,
)


def test_utf8_round_trip(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("héllo\nworld\n".encode())
    text, fmt = read_file(p)
    assert text == "héllo\nworld\n"
    assert fmt == TextFormat("utf-8", False, "\n")
    write_file(p, text + "more", fmt)
    assert p.read_bytes() == "héllo\nworld\nmore".encode()


def test_windows_line_endings_survive_a_save():
    data = b"one\r\ntwo\r\n"
    text, fmt = decode(data)
    assert text == "one\ntwo\n"
    assert fmt.eol == "\r\n"
    assert fmt.eol_label == "Windows (CRLF)"
    assert encode(text, fmt) == data


@pytest.mark.parametrize("bom, encoding, label", [
    (b"\xef\xbb\xbf", "utf-8", "UTF-8 with BOM"),
    (b"\xff\xfe", "utf-16-le", "UTF-16 LE"),
    (b"\xfe\xff", "utf-16-be", "UTF-16 BE"),
])
def test_bom_is_kept(bom, encoding, label):
    data = bom + "hi\r\n".encode(encoding)
    text, fmt = decode(data)
    assert text == "hi\n"
    assert fmt.bom and fmt.encoding == encoding
    assert fmt.encoding_label == label
    assert encode(text, fmt) == data


def test_old_windows_text_reads_as_windows_1252():
    data = "café – naïve".encode("cp1252")
    text, fmt = decode(data)
    assert text == "café – naïve"
    assert fmt.encoding_label == "Windows-1252"


def test_latin1_is_the_last_resort():
    # 0x81 and 0x8d are undefined in Windows-1252.
    text, fmt = decode(b"\x81\x8d")
    assert fmt.encoding == "latin-1"
    assert text == "\x81\x8d"


def test_detect_eol():
    assert detect_eol("") == "\n"
    assert detect_eol("no endings") == "\n"
    assert detect_eol("a\rb\r") == "\r"
    assert detect_eol("a\r\nb\nc\r\n") == "\r\n"


def test_unencodable_text_is_saved_as_utf8(tmp_path):
    p = tmp_path / "w.txt"
    used = write_file(p, "emoji 😀\n", TextFormat("cp1252", False, "\r\n"))
    assert used == TextFormat("utf-8", False, "\r\n")
    assert p.read_bytes() == "emoji 😀\r\n".encode()


def test_save_keeps_permissions_and_symlinks(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("old")
    os.chmod(real, 0o640)
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    write_file(link, "new", TextFormat())

    assert link.is_symlink()
    assert real.read_text() == "new"
    assert stat.S_IMODE(real.stat().st_mode) == 0o640
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".kami")]


def test_new_file_gets_the_usual_permissions(tmp_path):
    p = tmp_path / "n.txt"
    write_file(p, "x", TextFormat())
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE(p.stat().st_mode) == 0o666 & ~mask


def test_huge_files_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(textfile, "MAX_BYTES", 10)
    p = tmp_path / "big.txt"
    p.write_bytes(b"x" * 11)
    with pytest.raises(FileTooLarge):
        read_file(p)
