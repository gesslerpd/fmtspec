from io import BytesIO
from pathlib import Path

import pytest

from fmtspec import decode_stream, encode_stream, types
from fmtspec._stream import peek, read_exactly, write_all


def test_roundtrip():
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    stream = BytesIO()
    encode_stream(obj, stream, fmt)
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
        encode_stream(obj, f, fmt)

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
        encode_stream(obj, f, fmt)

    # Decode from file
    with open(file_path, "rb") as f:
        result = decode_stream(f, fmt)

    assert result == obj


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
        def write(self, data):
            return None

    stream = NoneWriteStream()

    with pytest.raises(TypeError):
        write_all(stream, b"abc")
