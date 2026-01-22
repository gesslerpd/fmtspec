"""Tests for the Literal constant type."""

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


def test_size_property() -> None:
    """Literal.size should return the length of the value."""
    assert types.Literal(b"").size == 0
    assert types.Literal(b"A").size == 1
    assert types.Literal(b"PNG").size == 3
    assert types.Literal(b"\x89PNG\r\n\x1a\n").size == 8


def test_encode_writes_value() -> None:
    """Literal should write its constant value to stream."""
    fmt = types.Literal(b"MAGIC")
    data = encode(None, fmt)  # value is ignored
    assert data == b"MAGIC"


def test_encode_ignores_input_value() -> None:
    """Literal should ignore the input value during encoding."""
    fmt = types.Literal(b"FIXED")
    # Any value should produce the same output
    assert encode(None, fmt) == b"FIXED"


def test_decode_returns_value() -> None:
    """Literal should return its constant value when bytes match."""
    fmt = types.Literal(b"MAGIC")
    result = decode(b"MAGIC", fmt)
    assert result == b"MAGIC"


def test_decode_mismatch_raises() -> None:
    """Literal should raise DecodeError with ValueError as cause when bytes don't match."""
    fmt = types.Literal(b"MAGIC")
    with pytest.raises(DecodeError, match="Expected b'MAGIC', got b'OTHER'") as exc_info:
        decode(b"OTHER", fmt)

    assert isinstance(exc_info.value.cause, ValueError)


def test_decode_partial_mismatch_raises() -> None:
    """Literal should raise DecodeError with ValueError as cause on partial mismatch."""
    fmt = types.Literal(b"MAGIC")
    with pytest.raises(DecodeError, match="Expected b'MAGIC', got b'MAGIX'") as exc_info:
        decode(b"MAGIX", fmt)

    assert isinstance(exc_info.value.cause, ValueError)


def test_in_format_dict() -> None:
    """Literal should work within a format dict."""
    u2 = types.Int(byteorder="big", signed=False, size=2)
    fmt = {
        "magic": types.Literal(b"\x89PNG"),
        "version": u2,
    }

    data = encode({"magic": None, "version": 1}, fmt)
    assert data == b"\x89PNG\x00\x01"

    result = decode(b"\x89PNG\x00\x01", fmt)
    assert result == {"magic": b"\x89PNG", "version": 1}


def test_empty_literal() -> None:
    """Empty literal should work (no-op)."""
    fmt = types.Literal(b"")
    assert encode(None, fmt) == b""
    assert decode(b"", fmt) == b""


def test_roundtrip_with_data() -> None:
    """Literal should roundtrip correctly in a compound format."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    fmt = {
        "header": types.Literal(b"\x00\x01"),
        "length": u1,
        "data": types.Bytes(size=3),
        "footer": types.Literal(b"\xff"),
    }

    obj = {
        "header": None,
        "length": 3,
        "data": b"ABC",
    }

    data = encode(obj, fmt)
    assert data == b"\x00\x01\x03ABC\xff"

    result = decode(data, fmt)
    assert result == {
        "header": b"\x00\x01",
        "length": 3,
        "data": b"ABC",
        "footer": b"\xff",
    }


def test_strict_encode():
    """Literal should perform strict checking during encode."""
    fmt = types.Literal(b"TEST")
    with pytest.raises(EncodeError, match="Expected b'TEST', got b'TES'") as exc_info:
        encode(b"TES", fmt)

    assert isinstance(exc_info.value.cause, ValueError)

    with pytest.raises(EncodeError, match="Expected b'TEST', got 123") as exc_info:
        encode(123, fmt)

    assert isinstance(exc_info.value.cause, ValueError)


def test_non_strict_encode():
    """Literal should skip strict checking during encode if strict is False."""
    fmt = types.Literal(b"TEST", strict=False)
    # Any value should produce the same output
    assert encode(b"TES", fmt) == b"TEST"
    # other type
    assert encode(123, fmt) == b"TEST"
