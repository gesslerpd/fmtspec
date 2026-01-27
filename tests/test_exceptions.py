import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types

FMT = {
    "key": types.TakeUntil(types.Str(), b"\0"),
    "number": types.Int(byteorder="little", signed=False, size=4),
}
VALID_DATA = b"value\0\x2a\x00\x00\x00"


@pytest.fixture
def valid_obj():
    return {
        "key": "value",
        "number": 42,
    }


def test_encode_str(valid_obj):
    fmt = "fmt"
    assert fmt.encode
    assert callable(fmt.encode)
    with pytest.raises(
        EncodeError,
        match="Unsupported format type",
        check=lambda e: "str" in str(e),
    ):
        encode(valid_obj, fmt)  # type: ignore

    with pytest.raises(
        EncodeError,
        match="Unsupported format type",
        check=lambda e: "str" in str(e),
    ):
        encode(valid_obj, [fmt])  # type: ignore


def test_decode_bytes():
    fmt = b"fmt"
    assert fmt.decode
    assert callable(fmt.decode)
    with pytest.raises(
        DecodeError,
        match="Unsupported format type",
        check=lambda e: "bytes" in str(e),
    ):
        decode(VALID_DATA, fmt)  # type: ignore

    with pytest.raises(
        DecodeError,
        match="Unsupported format type",
        check=lambda e: "bytes" in str(e),
    ):
        decode(VALID_DATA, [fmt])  # type: ignore


def test_decode_int():
    fmt = 1
    with pytest.raises(
        DecodeError,
        match="Unsupported format type",
        check=lambda e: "int" in str(e),
    ):
        decode(VALID_DATA, fmt)  # type: ignore

    with pytest.raises(
        DecodeError,
        match="Unsupported format type",
        check=lambda e: "int" in str(e),
    ):
        decode(VALID_DATA, [fmt])  # type: ignore


def test_encode_error(valid_obj):
    del valid_obj["number"]
    with pytest.raises(EncodeError) as exc_info:
        encode(valid_obj, FMT)

    exc = exc_info.value

    assert exc.fmt == FMT["number"]
    assert exc.context == {"key": "value"}


def test_decode_error():
    with pytest.raises(DecodeError) as exc_info:
        decode(VALID_DATA[:-1], FMT)

    exc = exc_info.value

    assert exc.fmt == FMT["number"]
    assert exc.context == {"key": "value"}


def test_direct_encode_error():
    fmt = types.Int(byteorder="big", signed=False, size=4)
    with pytest.raises(EncodeError) as exc_info:
        encode("bad type", fmt)

    exc = exc_info.value

    assert exc.fmt == fmt
    assert exc.context == {}


def test_iterable_encode():
    obj = ["value"]
    int_fmt = types.Int(byteorder="little", signed=False, size=4)
    fmt = [int_fmt]  # Trying to encode string "value" as an int
    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    assert exc_info.value.fmt == int_fmt


def test_iterator_encode():
    obj = ("value",)
    int_fmt = types.Int(byteorder="little", signed=False, size=4)
    fmt = (int_fmt,)  # Trying to encode string "value" as an int

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    assert exc_info.value.fmt == int_fmt


def test_encode_error_path_nested_dict():
    """Test that path tracks nested dictionary keys."""
    fmt = {
        "level1": {
            "level2": {
                "number": types.Int(byteorder="little", signed=False, size=4),
            }
        }
    }
    obj = {"level1": {"level2": {"number": "not_a_number"}}}

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    exc = exc_info.value
    assert exc.path == ("level1", "level2", "number")


def test_decode_error_path_nested_dict():
    """Test that path tracks nested dictionary keys during decode."""
    fmt = {
        "level1": {
            "level2": {
                "number": types.Int(byteorder="little", signed=False, size=4),
            }
        }
    }
    # Missing one byte for the nested number field
    data = b"\x2a\x00\x00"

    with pytest.raises(DecodeError) as exc_info:
        decode(data, fmt)

    exc = exc_info.value
    assert exc.path == ("level1", "level2", "number")


def test_encode_error_path_list():
    """Test that path tracks list indices."""
    int_fmt = types.Int(byteorder="little", signed=False, size=4)
    fmt = [int_fmt, int_fmt, int_fmt]
    obj = [1, "not_a_number", 3]

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    exc = exc_info.value
    assert exc.path == (1,)
    assert exc.fmt == int_fmt


def test_decode_error_path_list():
    """Test that path tracks list indices during decode."""
    int_fmt = types.Int(byteorder="little", signed=False, size=4)
    other_int_fmt = types.Int(byteorder="little", signed=False, size=8)
    fmt = [int_fmt, other_int_fmt, int_fmt]
    # Missing bytes for third element
    data = b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00"

    with pytest.raises(DecodeError) as exc_info:
        decode(data, fmt)

    exc = exc_info.value
    assert exc.path == (2,)
    assert exc.fmt == int_fmt


def test_encode_error_path_mixed():
    """Test path tracking with mixed dicts and lists."""
    fmt = {
        "items": [
            {"value": types.Int(byteorder="little", signed=False, size=4)},
            {"value": types.Int(byteorder="little", signed=False, size=8)},
        ]
    }
    obj = {"items": [{"value": 1}, {"value": "not_a_number"}]}

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    exc = exc_info.value
    assert exc.path == ("items", 1, "value")


def test_decode_error_path_mixed():
    """Test path tracking with mixed dicts and lists during decode."""
    inner_fmt = types.Int(byteorder="little", signed=False, size=8)
    fmt = {
        "items": [
            {"value": types.Int(byteorder="little", signed=False, size=4)},
            {"value": inner_fmt},
        ]
    }
    # Missing bytes for second item's value
    data = b"\x01\x00\x00\x00\x02\x00"

    with pytest.raises(DecodeError) as exc_info:
        decode(data, fmt)

    exc = exc_info.value
    assert exc.path == ("items", 1, "value")
    assert exc.fmt == inner_fmt


def test_encode_error_path_top_level():
    """Test that path is empty for top-level errors."""
    fmt = types.Int(byteorder="little", signed=False, size=4)
    obj = "not_a_number"

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    exc = exc_info.value
    assert exc.path == ()


def test_path_preserved_in_context():
    """Test that path in context matches what's in the exception."""
    fmt = {
        "outer": {
            "inner": types.Int(byteorder="little", signed=False, size=4),
        }
    }
    obj = {"outer": {"inner": "bad"}}

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    # Path should reflect where the error occurred
    assert exc_info.value.path == ("outer", "inner")
    assert exc_info.value.context == {"inner": "bad"}
