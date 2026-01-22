"""Tests for the Switch type."""

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


def test_decode_known_case() -> None:
    """Switch should decode using the matched case format."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    inner_fmt = {"a": u1, "b": u1}
    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={1: inner_fmt},
        ),
    }

    # type=1, then 2 bytes for inner format
    data = b"\x00\x01\x0a\x14"
    result = decode(data, fmt)

    assert result == {"type": 1, "body": {"a": 10, "b": 20}}


def test_decode_unknown_case_returns_raw_bytes() -> None:
    """Switch should return raw bytes for unknown cases with no default."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={1: {"x": u2}},
            default=None,
        ),
    }

    # type=99 (unknown), then 4 raw bytes
    data = b"\x00\x63\xde\xad\xbe\xef"
    result = decode(data, fmt)

    assert result == {"type": 99, "body": b"\xde\xad\xbe\xef"}


def test_encode_known_case() -> None:
    """Switch should encode using the matched case format."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    inner_fmt = {"a": u1, "b": u1}
    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={1: inner_fmt},
        ),
    }

    obj = {"type": 1, "body": {"a": 10, "b": 20}}
    data = encode(obj, fmt)

    # type=1, then encoded inner
    assert data == b"\x00\x01\x0a\x14"


def test_encode_unknown_case_raw_bytes() -> None:
    """Switch should encode raw bytes for unknown cases."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={1: {"x": u2}},
            default=None,
        ),
    }

    obj = {"type": 99, "body": b"\xde\xad\xbe\xef"}
    data = encode(obj, fmt)

    # type=99, then raw bytes
    assert data == b"\x00\x63\xde\xad\xbe\xef"


def test_roundtrip() -> None:
    """Switch should roundtrip correctly."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={
                1: {"a": u1, "b": u1},
                2: {"x": u2, "y": u2},
            },
        ),
    }

    obj1 = {"type": 1, "body": {"a": 10, "b": 20}}
    assert decode(encode(obj1, fmt), fmt) == obj1

    obj2 = {"type": 2, "body": {"x": 100, "y": 200}}
    assert decode(encode(obj2, fmt), fmt) == obj2


def test_decode_missing_key_raises() -> None:
    """Switch should raise DecodeError with KeyError as cause if the key is missing from context."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("wrong_key"),
            cases={1: {"x": u2}},
        ),
    }

    # type=1, data
    data = b"\x00\x01\x00\x02\x00\x05"

    with pytest.raises(DecodeError, match="wrong_key") as exc_info:
        decode(data, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_encode_missing_key_raises() -> None:
    """Switch should raise EncodeError with KeyError as cause if the key is missing from context."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("wrong_key"),
            cases={1: {"x": u2}},
        ),
    }

    obj = {"type": 1, "body": {"x": 5}}

    with pytest.raises(EncodeError, match="wrong_key") as exc_info:
        encode(obj, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_little_endian_prefix() -> None:
    """Switch should support little-endian length prefix."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "type": u2,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={},
        ),
    }

    obj = {"type": 1, "body": b"\x01\x02\x03"}
    data = encode(obj, fmt)

    # type=1 (big), then data
    assert data == b"\x00\x01\x01\x02\x03"

    result = decode(data, fmt)
    assert result == obj


def test_different_prefix_sizes() -> None:
    """Switch should support different prefix sizes."""
    u1 = types.Int(byteorder="big", signed=False, size=1)

    # Test with 1-byte prefix
    fmt1 = {
        "type": u1,
        "body": types.Switch(key=types.Ref("type"), cases={}),
    }
    obj = {"type": 1, "body": b"\xaa\xbb"}
    data1 = encode(obj, fmt1)
    assert data1 == b"\x01\xaa\xbb"  # type=1, len=2 (1 byte), data

    # Test with 4-byte prefix
    fmt4 = {
        "type": u1,
        "body": types.Switch(key=types.Ref("type"), cases={}),
    }
    data4 = encode(obj, fmt4)
    assert data4 == b"\x01\xaa\xbb"  # type=1, len=2 (4 bytes), data
