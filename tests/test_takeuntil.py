# from io import BytesIO

# import pytest

from fmtspec import decode, encode, types


def test_roundtrip():
    obj = {"key": b"value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Bytes(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, fmt)
    assert result == obj
