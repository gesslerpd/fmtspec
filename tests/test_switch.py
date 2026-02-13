"""Tests for the Switch type."""

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


def test_decode_known_case() -> None:
    """Switch should decode using the matched case format."""

    inner_fmt = {"a": types.u8, "b": types.u8}
    fmt = {
        "type": types.u16,
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

    fmt = {
        "type": types.u16,
        "body": types.Switch(
            key=types.Ref("type"), cases={1: {"x": types.u16}}, default=types.bytes_
        ),
    }

    # type=99 (unknown), then 4 raw bytes
    data = b"\x00\x63\xde\xad\xbe\xef"
    result = decode(data, fmt)

    assert result == {"type": 99, "body": b"\xde\xad\xbe\xef"}


def test_encode_known_case() -> None:
    """Switch should encode using the matched case format."""

    inner_fmt = {"a": types.u8, "b": types.u8}
    fmt = {
        "type": types.u16,
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

    fmt = {
        "type": types.u16,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={1: {"x": types.u16}},
            default=types.bytes_,  # Unknown cases write raw bytes
        ),
    }

    obj = {"type": 99, "body": b"\xde\xad\xbe\xef"}
    data = encode(obj, fmt)

    # type=99, then raw bytes
    assert data == b"\x00\x63\xde\xad\xbe\xef"


def test_roundtrip() -> None:
    """Switch should roundtrip correctly."""

    fmt = {
        "type": types.u16,
        "padding": types.Bytes(2),
        "body": types.Switch(
            key=types.Ref("type"),
            cases={
                1: {"a": types.u8, "b": types.u8},
                2: {"x": types.u16, "y": types.u16},
            },
        ),
    }

    obj1 = {"type": 1, "padding": b"\x02\x03", "body": {"a": 10, "b": 20}}

    data = encode(obj1, fmt)
    assert data == b"\x00\x01\x02\x03\x0a\x14"  # type=1, padding, then body
    assert decode(data, fmt) == obj1

    obj2 = {"type": 2, "padding": b"\x02\x03", "body": {"x": 100, "y": 200}}
    data = encode(obj2, fmt)
    assert data == b"\x00\x02\x02\x03\x00\x64\x00\xc8"  # type=2, padding, then body

    assert decode(data, fmt) == obj2


def test_decode_missing_key_raises() -> None:
    """Switch should raise DecodeError with KeyError as cause if the key is missing from context."""

    fmt = {
        "type": types.u16,
        "body": types.Switch(
            key=types.Ref("wrong_key"),
            cases={1: {"x": types.u16}},
        ),
    }

    # type=1, data
    data = b"\x00\x01\x00\x02\x00\x05"

    with pytest.raises(DecodeError, match="wrong_key") as exc_info:
        decode(data, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_encode_missing_key_raises() -> None:
    """Switch should raise EncodeError with KeyError as cause if the key is missing from context."""

    fmt = {
        "type": types.u16,
        "body": types.Switch(
            key=types.Ref("wrong_key"),
            cases={1: {"x": types.u16}},
        ),
    }

    obj = {"type": 1, "body": {"x": 5}}

    with pytest.raises(EncodeError, match="wrong_key") as exc_info:
        encode(obj, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_little_endian_prefix() -> None:
    """Switch should support little-endian length prefix."""

    fmt = {
        "type": types.u16,
        "body": types.Switch(
            key=types.Ref("type"),
            cases={0x1: types.Bytes(3)},
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
    fmt1 = {
        "type": types.u8,
        "body": types.Switch(key=types.Ref("type"), cases={}, default=types.bytes_),
    }
    obj = {"type": 1, "body": b"\xaa\xbb"}
    data1 = encode(obj, fmt1)
    assert data1 == b"\x01\xaa\xbb"  # type=1, data

    fmt4 = {
        "type": types.u16,
        "body": types.Switch(key=types.Ref("type"), cases={}, default=types.bytes_),
    }
    data1 = encode(obj, fmt4)
    assert data1 == b"\x00\x01\xaa\xbb"  # type=1, data
