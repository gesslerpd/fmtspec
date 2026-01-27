import pytest

from fmtspec import DecodeError, decode, encode, types


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


def test_greedy_last():
    # nothing special should happen if only the last field is greedy
    fmt = {
        "other": types.u16,
        "greedy": types.Bytes(),
    }

    obj = {"other": 6, "greedy": b"foobar"}
    data = encode(obj, fmt)
    assert data == b"\x00\x06foobar"

    result = decode(data, fmt)
    assert result == obj


def test_too_greedy():
    # decoding should fail if there are multiple greedy fields
    fmt = {
        "first": types.Bytes(),
        "second": types.Bytes(),
    }

    obj = {"first": b"hello", "second": b"world"}
    data = encode(obj, fmt)
    assert data == b"helloworld"

    with pytest.raises(DecodeError, match="multiple greedy items in mapping format"):
        decode(data, fmt)


def test_greedy_first():
    # for decode automatically detects that the first field is greedy and wraps the fmt in Sized with fixed length
    # FUTURE: reenable _preprocess_greedy_fmt usage in _core::decode
    fmt = {
        "greedy": types.Sized(6, types.Bytes()),
        # "greedy": types.Bytes(),
        "other": types.u16,
    }

    obj = {"other": 6, "greedy": b"foobar"}
    data = encode(obj, fmt)
    assert data == b"foobar\x00\x06"

    result = decode(data, fmt)
    assert result == obj


def test_greedy_middle():
    # for decode automatically detects that the first field is greedy and wraps the fmt in Sized with fixed length
    # FUTURE: reenable _preprocess_greedy_fmt usage in _core::decode
    fmt = {
        "first": types.u16,
        "greedy": types.Sized(6, types.Bytes()),
        # "greedy": types.Bytes(),
        "last": types.u32,
    }

    obj = {"first": 6, "greedy": b"foobar", "last": 42}
    data = encode(obj, fmt)
    assert data == b"\x00\x06foobar\x00\x00\x00\x2a"

    result = decode(data, fmt)
    assert result == obj
