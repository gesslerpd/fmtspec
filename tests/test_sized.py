"""Tests for the size property on types and the Sized type."""

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


def test_int_has_size() -> None:
    """Int types should have their byte size."""
    assert types.u8.size == types.u8le.size == types.i8.size == types.i8le.size == 1
    assert types.u16.size == types.u16le.size == types.i16.size == types.i16le.size == 2
    assert types.u32.size == types.u32le.size == types.i32.size == types.i32le.size == 4
    assert types.u64.size == types.u64le.size == types.i64.size == types.i64le.size == 8


def test_bytes_has_size() -> None:
    """Bytes types should have their fixed size or None if greedy."""
    assert types.Bytes(size=0).size == 0
    assert types.Bytes(size=16).size == 16
    assert types.Bytes(size=1024).size == 1024
    assert types.Bytes().size is None  # greedy


def test_prefixed_bytes_size_is_none() -> None:
    assert types.Sized(length=types.u16, fmt=types.Bytes()).size is ...


def test_prefixed_bytes() -> None:
    fmt = types.Sized(length=types.u16, fmt=types.Bytes())
    obj = b"hello world"
    data = encode(obj, fmt)
    assert data == b"\x00\x0bhello world"
    result = decode(data, fmt)
    assert result == obj

    with pytest.raises(DecodeError, match="Expected 5 bytes, got 3"):
        decode(b"\x00\x05abc", fmt)

    data = encode(obj, types.Sized(length=len(data), fmt=fmt))
    assert data == b"\x00\x0bhello world"
    result = decode(data, fmt)
    assert result == obj


def test_terminated_string_size_is_none() -> None:
    """TerminatedString is greedy, so size should be None."""
    assert types.TakeUntil(types.Str(), b"\0").size is ...


def test_prefixed_array_size_is_none() -> None:
    """PrefixedArray is variable-size, so size should be None."""
    assert types.array(types.u16, dims=types.u16).size is ...


def test_switch_size_is_none() -> None:
    """Switch is variable-size, so size should be None."""
    assert types.Switch(key=types.Ref("type"), cases={}).size is ...


def test_sized_size_is_none() -> None:
    """Sized wraps unsized types, so size should be None."""
    assert types.Sized(length=types.Ref("length"), fmt=types.Bytes()).size is ...


def test_decode_simple() -> None:
    """Sized should read exactly the number of bytes from context key."""

    fmt = {
        "length": types.u16,
        "data": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    # length=5, then 5 bytes of data, then extra byte that should not be read
    data = b"\x00\x05hello\xff"
    result = decode(data, fmt)

    assert result == {"length": 5, "data": b"hello"}


def test_decode_nested() -> None:
    fmt = {
        "length": types.u16,
        "data": types.Sized(
            length=5, fmt=types.Sized(length=types.Ref("length"), fmt=types.Bytes())
        ),
    }

    # length=5, then 5 bytes of data, then extra byte that should not be read
    data = b"\x00\x05hello\xff"
    result = decode(data, fmt)

    assert result == {"length": 5, "data": b"hello"}


def test_decode_with_inner_format() -> None:
    """Sized should pass bounded data to inner format."""

    inner_fmt = {"a": types.u8, "b": types.u8}
    fmt = {
        "size": types.u16,
        "body": types.Sized(length=types.Ref("size"), fmt=inner_fmt),
    }

    # size=2, then 2 bytes for inner format
    data = b"\x00\x02\x0a\x14"
    result = decode(data, fmt)

    assert result == {"size": 2, "body": {"a": 10, "b": 20}}


def test_encode_simple() -> None:
    """Sized should encode and verify length matches context."""

    fmt = {
        "length": types.u16,
        "data": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    obj = {"length": 5, "data": b"hello"}
    data = encode(obj, fmt)

    assert data == b"\x00\x05hello"


@pytest.mark.skip
@pytest.mark.xfail(strict=True, raises=EncodeError)
def test_encode_autopopulate() -> None:
    # FUTURE: support auto-populating length keys during encode?
    # implement some generic solution to do this, requires backreferencing items higher in context
    fmt = {
        "_data_len": types.u16,
        "other": types.u8,
        "data": types.Sized(length=types.Ref("_data_len"), fmt=types.Bytes()),
    }

    obj = {"other": 0xFF, "data": b"hello"}
    obj_with_length = obj | {"_data_len": 5}

    data = encode(obj, fmt)

    assert data == encode(obj_with_length, fmt) == b"\x00\x05\xffhello"

    result = decode(data, fmt)
    assert result == obj_with_length


def test_encode_with_inner_format() -> None:
    """Sized should encode inner format and verify length."""

    inner_fmt = {"a": types.u8, "b": types.u8}
    fmt = {
        "size": types.u16,
        "body": types.Sized(length=types.Ref("size"), fmt=inner_fmt),
    }

    obj = {"size": 2, "body": {"a": 10, "b": 20}}
    data = encode(obj, fmt)

    assert data == b"\x00\x02\x0a\x14"


def test_encode_length_mismatch_raises() -> None:
    """Sized should raise if encoded length doesn't match context."""

    fmt = {
        "length": types.u16,
        "data": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    # length says 10 but data is only 5 bytes
    obj = {"length": 10, "data": b"hello"}

    with pytest.raises(EncodeError, match="does not match expected length") as exc_info:
        encode(obj, fmt)

    assert isinstance(exc_info.value.cause, ValueError)


def test_roundtrip() -> None:
    """Sized should roundtrip correctly."""

    fmt = {
        "header_size": types.u16,
        "header": types.Sized(
            length=types.Ref("header_size"),
            fmt={"version": types.u16, "flags": types.u16},
        ),
        "payload_size": types.u16,
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

    fmt = {
        "length": types.u16,
        "data": types.Sized(length=types.Ref("wrong_key"), fmt=types.Bytes()),
    }

    data = b"\x00\x05hello"

    with pytest.raises(DecodeError, match="wrong_key") as exc_info:
        decode(data, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_encode_missing_key_raises() -> None:
    """Sized should raise EncodeError with KeyError as cause if the key is missing from context."""

    fmt = {
        "length": types.u16,
        "data": types.Sized(length=types.Ref("wrong_key"), fmt=types.Bytes()),
    }

    obj = {"length": 5, "data": b"hello"}

    with pytest.raises(EncodeError, match="wrong_key") as exc_info:
        encode(obj, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_sized_with_int_length_padding() -> None:
    """Fixed int length should pad with `fill` and decode correctly."""

    fmt = {"data": types.Sized(length=5, fmt=types.Bytes(size=3))}
    obj = {"data": b"abc"}

    assert fmt["data"].size == 5

    data = encode(obj, fmt)
    assert data == b"abc\x00\x00"

    result = decode(data, fmt)
    assert result == obj

    # can't use align with fixed int length
    with pytest.raises(ValueError, match="align is not allowed with fixed int length"):
        types.Sized(length=5, fmt=types.Bytes(size=3), align=2)


def test_sized_with_ref_align_and_fill() -> None:
    """Ref-based length honors `align` and uses `fill` for padding."""

    fmt = {
        "len": types.u16,
        "data": types.Sized(length=types.Ref("len"), fmt=types.Bytes(), align=4, fill=b"\xff"),
    }
    obj = {"len": 3, "data": b"abc"}

    data = encode(obj, fmt)
    assert data == b"\x00\x03abc\xff"

    result = decode(data, fmt)
    assert result == obj

    obj = {"len": 4, "data": b"abcd"}

    data = encode(obj, fmt)
    assert data == b"\x00\x04abcd"

    result = decode(data, fmt)
    assert result == obj

    obj = {"len": 5, "data": b"abcde"}

    data = encode(obj, fmt)
    assert data == b"\x00\x05abcde\xff\xff\xff"

    result = decode(data, fmt)
    assert result == obj


def test_sized_with_format_length_and_align_and_fill() -> None:
    """Format-based length writes length, then honors `align` and `fill`."""

    fmt = types.Sized(length=types.u8, fmt=types.Bytes(), align=2, fill=b"\x55")
    obj = b"a"

    data = encode(obj, fmt)
    assert data == b"\x01a\x55"

    result = decode(data, fmt)
    assert result == obj

    obj = b"ab"
    data = encode(obj, fmt)
    assert data == b"\x02ab"

    result = decode(data, fmt)
    assert result == obj
