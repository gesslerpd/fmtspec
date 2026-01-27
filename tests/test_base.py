from fmtspec import decode, encode, types


def test_roundtrip():
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, fmt)
    assert result == obj


def test_direct_type():
    obj = 0x01020304
    fmt = types.Int(byteorder="big", signed=False, size=4)

    data = encode(obj, fmt)

    assert data == b"\x01\x02\x03\x04"

    result = decode(data, fmt)
    assert result == obj


# def test_direct_annotated():
#     obj = 0x01020304
#     fmt = types.Int(byteorder="big", signed=False, size=4)

#     data = encode(obj, Annotated[int, fmt])

#     assert data == b"\x01\x02\x03\x04"

#     result = decode(data, Annotated[int, fmt])
#     assert_type(result, int)
#     assert result == obj

# def test_container_annotated():
#     obj = [0x01020304]
#     fmt = types.Int(byteorder="big", signed=False, size=4)

#     data = encode(obj, list[Annotated[int, fmt]])

#     assert data == b"\x01\x02\x03\x04"

#     result = decode(data, list[Annotated[int, fmt]])
#     assert_type(result, list[int])
#     assert type(result[0]) is int
#     assert type(result) is list
#     assert result == obj
