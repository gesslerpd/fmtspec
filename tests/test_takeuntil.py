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


FMT = [types.TakeUntil(typ, b",") for typ in (types.Bytes(), types.Str())]


def test_takeuntil_variants():
    obj = [b"first", "second"]
    data = encode(obj, FMT)
    assert data == b"first,second,"
    result = decode(data, FMT)
    assert result == obj
