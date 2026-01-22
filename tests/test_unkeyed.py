from fmtspec import decode, encode, types


def test_roundtrip():
    obj = ["value", 42]
    fmt = [
        types.TerminatedString(b"\0", encoding="utf-8"),
        types.Int(byteorder="little", signed=False, size=4),
    ]

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, fmt)
    assert result == obj


def test_iterable():
    obj = ("value", 42)
    fmt = (
        types.TerminatedString(b"\0", encoding="utf-8"),
        types.Int(byteorder="little", signed=False, size=4),
    )

    data = encode(iter(obj), iter(fmt))

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, iter(fmt))
    assert isinstance(result, list)
    assert tuple(result) == obj
