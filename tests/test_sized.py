"""Tests for the size property on types and the Sized type."""

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


def test_int_has_size() -> None:
    """Int types should have their byte size."""
    assert types.Int(byteorder="big", signed=False, size=1).size == 1
    assert types.Int(byteorder="big", signed=False, size=2).size == 2
    assert types.Int(byteorder="little", signed=True, size=4).size == 4
    assert types.Int(byteorder="big", signed=False, size=8).size == 8


def test_bytes_has_size() -> None:
    """Bytes types should have their fixed size or None if greedy."""
    assert types.Bytes(size=0).size == 0
    assert types.Bytes(size=16).size == 16
    assert types.Bytes(size=1024).size == 1024
    assert types.Bytes().size is None  # greedy


def test_prefixed_bytes_size_is_none() -> None:
    prefix_fmt = types.Int(byteorder="big", signed=False, size=2)
    assert types.Sized(length=prefix_fmt, fmt=types.Bytes()).size is ...


def test_terminated_string_size_is_none() -> None:
    """TerminatedString is greedy, so size should be None."""
    assert types.TakeUntil(types.String(), b"\0").size is ...


def test_prefixed_array_size_is_none() -> None:
    """PrefixedArray is variable-size, so size should be None."""
    u2 = types.Int(byteorder="big", signed=False, size=2)
    assert types.PrefixedArray(byteorder="big", prefix_size=2, element_fmt=u2).size is ...


def test_switch_size_is_none() -> None:
    """Switch is variable-size, so size should be None."""
    assert types.Switch(key=types.Ref("type"), cases={}).size is None


def test_sized_size_is_none() -> None:
    """Sized wraps unsized types, so size should be None."""
    assert types.Sized(length=types.Ref("length"), fmt=types.Bytes()).size is ...


def test_decode_simple() -> None:
    """Sized should read exactly the number of bytes from context key."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "length": u2,
        "data": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    # length=5, then 5 bytes of data, then extra byte that should not be read
    data = b"\x00\x05hello\xff"
    result = decode(data, fmt)

    assert result == {"length": 5, "data": b"hello"}


def test_decode_with_inner_format() -> None:
    """Sized should pass bounded data to inner format."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    inner_fmt = {"a": u1, "b": u1}
    fmt = {
        "size": u2,
        "body": types.Sized(length=types.Ref("size"), fmt=inner_fmt),
    }

    # size=2, then 2 bytes for inner format
    data = b"\x00\x02\x0a\x14"
    result = decode(data, fmt)

    assert result == {"size": 2, "body": {"a": 10, "b": 20}}


def test_encode_simple() -> None:
    """Sized should encode and verify length matches context."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "length": u2,
        "data": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    obj = {"length": 5, "data": b"hello"}
    data = encode(obj, fmt)

    assert data == b"\x00\x05hello"


def test_encode_with_inner_format() -> None:
    """Sized should encode inner format and verify length."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    inner_fmt = {"a": u1, "b": u1}
    fmt = {
        "size": u2,
        "body": types.Sized(length=types.Ref("size"), fmt=inner_fmt),
    }

    obj = {"size": 2, "body": {"a": 10, "b": 20}}
    data = encode(obj, fmt)

    assert data == b"\x00\x02\x0a\x14"


def test_encode_length_mismatch_raises() -> None:
    """Sized should raise if encoded length doesn't match context."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "length": u2,
        "data": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    # length says 10 but data is only 5 bytes
    obj = {"length": 10, "data": b"hello"}

    with pytest.raises(EncodeError, match="does not match expected length") as exc_info:
        encode(obj, fmt)

    assert isinstance(exc_info.value.cause, ValueError)


def test_roundtrip() -> None:
    """Sized should roundtrip correctly."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "header_size": u2,
        "header": types.Sized(
            length=types.Ref("header_size"),
            fmt={"version": u2, "flags": u2},
        ),
        "payload_size": u2,
        "payload": types.Sized(length=types.Ref("payload_size"), fmt=types.Bytes()),
    }

    obj = {
        "header_size": 4,
        "header": {"version": 1, "flags": 0x0F},
        "payload_size": 8,
        "payload": b"\x01\x02\x03\x04\x05\x06\x07\x08",
    }

    data = encode(obj, fmt)
    result = decode(data, fmt)

    assert result == obj


def test_decode_missing_key_raises() -> None:
    """Sized should raise DecodeError with KeyError as cause if the key is missing from context."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "length": u2,
        "data": types.Sized(length=types.Ref("wrong_key"), fmt=types.Bytes()),
    }

    data = b"\x00\x05hello"

    with pytest.raises(DecodeError, match="wrong_key") as exc_info:
        decode(data, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_encode_missing_key_raises() -> None:
    """Sized should raise EncodeError with KeyError as cause if the key is missing from context."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "length": u2,
        "data": types.Sized(length=types.Ref("wrong_key"), fmt=types.Bytes()),
    }

    obj = {"length": 5, "data": b"hello"}

    with pytest.raises(EncodeError, match="wrong_key") as exc_info:
        encode(obj, fmt)

    assert isinstance(exc_info.value.cause, KeyError)
