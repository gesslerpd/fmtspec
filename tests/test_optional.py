from fmtspec import decode, encode, types


def test_roundtrip():
    obj = {"other": 1, "number": 42}
    fmt = {
        "number": types.Int(byteorder="little", signed=False, size=4),
        "other": types.Optional(types.Int(byteorder="little", signed=False, size=4)),
    }

    data = encode(obj, fmt)

    assert data == b"\x2a\x00\x00\x00\x01\x00\x00\x00"

    result = decode(data, fmt)
    assert result == obj


def test_none_roundtrip():
    obj = {"other": None, "number": 42}
    fmt = {
        "number": types.Int(byteorder="little", signed=False, size=4),
        "other": types.Optional(types.Int(byteorder="little", signed=False, size=4)),
    }

    data = encode(obj, fmt)

    assert data == b"\x2a\x00\x00\x00"

    result = decode(data, fmt)
    assert result == obj
