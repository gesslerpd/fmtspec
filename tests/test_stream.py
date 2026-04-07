import socket
import threading
from io import BytesIO
from pathlib import Path

import pytest

from fmtspec import decode_stream, encode_stream, types
from fmtspec.stream import peek, read_exactly, seek_to, write_all


def test_roundtrip():
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    stream = BytesIO()
    encode_stream(stream, obj, fmt)
    data = stream.getvalue()

    assert data == b"value\0\x2a\x00\x00\x00"

    stream = BytesIO(data)
    result = decode_stream(stream, fmt)
    assert result == obj


def test_encode_to_file(tmp_path: Path):
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    file_path = tmp_path / "test_data.bin"

    with open(file_path, "wb") as f:
        encode_stream(f, obj, fmt)

    # Verify the file contents
    with open(file_path, "rb") as f:
        data = f.read()

    assert data == b"value\0\x2a\x00\x00\x00"


def test_decode_from_file(tmp_path: Path):
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    file_path = tmp_path / "test_data.bin"

    # Write test data to file
    with open(file_path, "wb") as f:
        f.write(b"value\0\x2a\x00\x00\x00")

    # Decode from file
    with open(file_path, "rb") as f:
        result = decode_stream(f, fmt)

    assert result == {"key": "value", "number": 42}


def test_file_roundtrip(tmp_path: Path):
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    file_path = tmp_path / "test_roundtrip.bin"

    # Encode to file
    with open(file_path, "wb") as f:
        encode_stream(f, obj, fmt)

    # Decode from file
    with open(file_path, "rb") as f:
        result = decode_stream(f, fmt)

    assert result == obj


def test_socket_roundtrip_with_encode_decode_stream():
    fmt = {
        "key": types.TakeUntil(types.str_, b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }
    result = {}

    def sender(sock, n) -> None:
        with sock:
            with sock.makefile("wb") as stream:
                for i in range(n):
                    obj = {"key": f"value_{i}", "number": i}
                    encode_stream(stream, obj, fmt)
                    stream.flush()

    def receiver(sock, n) -> None:
        with sock:
            with sock.makefile("rb") as recv_stream:
                for _ in range(n):
                    result.update(decode_stream(recv_stream, fmt))

    n = 10000
    sock_send, sock_recv = socket.socketpair()

    send_thread = threading.Thread(target=sender, args=(sock_send, n))
    recv_thread = threading.Thread(target=receiver, args=(sock_recv, n))

    send_thread.start()
    recv_thread.start()
    send_thread.join()
    recv_thread.join()

    assert result == {"key": f"value_{n - 1}", "number": n - 1}


def test_read_exactly_bytesio_success():
    stream = BytesIO(b"abcdef")
    stream.seek(1)

    data = read_exactly(stream, 3)

    assert data == bytearray(b"bcd")
    assert stream.tell() == 4


def test_read_exactly_readinto_success():
    class ReadIntoStream:
        def __init__(self, data: bytes) -> None:
            self._buf = bytearray(data)
            self._pos = 0

        def readinto(self, target) -> int:
            if self._pos >= len(self._buf):
                return 0
            n = min(len(target), len(self._buf) - self._pos)
            target[:n] = self._buf[self._pos : self._pos + n]
            self._pos += n
            return n

    stream = ReadIntoStream(b"xyz123")

    assert read_exactly(stream, 6) == bytearray(b"xyz123")


def test_read_exactly_read_fallback_success():
    class ReadOnlyStream:
        def __init__(self, data: bytes) -> None:
            self._buf = data
            self._pos = 0

        def read(self, size: int = -1) -> bytes:
            if self._pos >= len(self._buf):
                return b""
            if size < 0:
                size = len(self._buf) - self._pos
            end = min(self._pos + size, len(self._buf))
            chunk = self._buf[self._pos : end]
            self._pos = end
            return chunk

    stream = ReadOnlyStream(b"hello")

    assert read_exactly(stream, 5) == bytearray(b"hello")


def test_read_exactly_raises_eoferror_when_short():
    stream = BytesIO(b"ab")

    with pytest.raises(EOFError, match=r"Expected 4 bytes, got 2"):
        read_exactly(stream, 4)


def test_peek_does_not_advance_stream_position():
    stream = BytesIO(b"abcdef")
    stream.seek(2)

    data = peek(stream, 3)

    assert data == bytearray(b"cde")
    assert stream.tell() == 2
    assert stream.read(2) == b"cd"


def test_seek_to_restores_stream_position() -> None:
    stream = BytesIO(b"abcdef")
    stream.seek(1)

    with seek_to(stream, 4):
        assert stream.tell() == 4
        assert stream.read(1) == b"e"

    assert stream.tell() == 1
    assert stream.read(2) == b"bc"


def test_seek_to_restores_stream_position_on_error() -> None:
    stream = BytesIO(b"abcdef")
    stream.seek(2)

    with pytest.raises(RuntimeError, match="boom"):
        with seek_to(stream, 5):
            raise RuntimeError("boom")

    assert stream.tell() == 2


def test_write_all_writes_partial_stream_until_complete():
    class PartialWriteStream:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data) -> int:
            b = bytes(data)
            if not b:
                return 0
            n = min(len(b), 1)
            self.writes.append(b[:n])
            return n

    stream = PartialWriteStream()
    payload = b"abcd"

    write_all(stream, payload)

    assert b"".join(stream.writes) == payload


def test_write_all_raises_when_initial_write_returns_none():
    class NoneWriteStream:
        def write(self, _data):
            return None

    stream = NoneWriteStream()

    with pytest.raises(TypeError):
        write_all(stream, b"abc")


def test_read_exactly_zero_bytes_returns_empty_and_keeps_position():
    stream = BytesIO(b"abcdef")
    stream.seek(3)

    data = read_exactly(stream, 0)

    assert data == bytearray()
    assert stream.tell() == 3


def test_read_exactly_readinto_raises_eoferror_when_short():
    class ShortReadIntoStream:
        def __init__(self, data: bytes) -> None:
            self._buf = bytearray(data)
            self._pos = 0

        def readinto(self, target) -> int:
            if self._pos >= len(self._buf):
                return 0
            n = min(2, len(target), len(self._buf) - self._pos)
            target[:n] = self._buf[self._pos : self._pos + n]
            self._pos += n
            return n

    stream = ShortReadIntoStream(b"abc")

    with pytest.raises(EOFError, match=r"Expected 5 bytes, got 3"):
        read_exactly(stream, 5)


def test_read_exactly_read_fallback_raises_eoferror_when_short():
    class ShortReadOnlyStream:
        def __init__(self, data: bytes) -> None:
            self._buf = data
            self._pos = 0

        def read(self, size: int = -1) -> bytes:
            if self._pos >= len(self._buf):
                return b""
            if size < 0:
                size = len(self._buf) - self._pos
            end = min(self._pos + size, len(self._buf))
            chunk = self._buf[self._pos : end]
            self._pos = end
            return chunk

    stream = ShortReadOnlyStream(b"xy")

    with pytest.raises(EOFError, match=r"Expected 4 bytes, got 2"):
        read_exactly(stream, 4)


def test_write_all_accepts_memoryview_input():
    class CapturingStream:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data) -> int:
            chunk = bytes(data)
            if not chunk:
                return 0
            n = min(2, len(chunk))
            self.writes.append(chunk[:n])
            return n

    stream = CapturingStream()
    payload = memoryview(b"abcdef")

    write_all(stream, payload)

    assert b"".join(stream.writes) == b"abcdef"
