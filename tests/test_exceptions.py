from io import BytesIO

import pytest

from fmtspec import DecodeError, EncodeError, decode, decode_stream, encode, encode_stream, types

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
    assert exc.local_context == {"key": "value"}
    assert exc.context == {"key": "value"}  # encode: context is user's root object
    assert exc.start_offset == 0
    assert exc.offset > 0


def test_decode_error():
    with pytest.raises(DecodeError) as exc_info:
        decode(VALID_DATA[:-1], FMT)

    exc = exc_info.value

    assert exc.fmt == FMT["number"]
    assert exc.local_context == {"key": "value"}
    # decode: context is stitched partial tree (single-level, same as local_context)
    assert exc.context == {"key": "value"}
    assert exc.start_offset == 0
    assert exc.offset > 0


def test_direct_encode_error():
    fmt = types.Int(byteorder="big", signed=False, size=4)
    with pytest.raises(EncodeError) as exc_info:
        encode("bad type", fmt)

    exc = exc_info.value

    assert exc.fmt == fmt
    assert exc.context == {}  # sentinel when no dict format wrapping
    assert exc.local_context == {}
    assert exc.start_offset == 0
    assert exc.offset == 0


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
    # encode: context is user's root object
    assert exc.context == {"level1": {"level2": {"number": "not_a_number"}}}
    assert exc.local_context == {"number": "not_a_number"}


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
    # decode: context is stitched partial tree
    assert exc.context == {"level1": {"level2": {}}}


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
    assert exc_info.value.local_context == {"inner": "bad"}
    assert exc_info.value.context == {"outer": {"inner": "bad"}}


def test_encode_error_start_offset_nonzero():
    """Test that start_offset captures stream position before the operation."""
    stream = BytesIO()
    stream.write(b"\x00" * 10)  # pre-fill
    fmt = types.Int(byteorder="big", signed=False, size=4)
    with pytest.raises(EncodeError) as exc_info:
        encode_stream(stream, "bad type", fmt)

    exc = exc_info.value
    assert exc.start_offset == 10
    assert exc.offset == 10  # no bytes written before error


def test_decode_error_start_offset_nonzero():
    """Test that start_offset captures stream position before the operation."""
    header = b"\x00" * 5
    # u16 needs 2 bytes, only give 1
    stream = BytesIO(header + b"\x01")
    stream.read(5)  # advance past header

    fmt = types.Int(byteorder="big", signed=False, size=2)
    with pytest.raises(DecodeError) as exc_info:
        decode_stream(stream, fmt)

    exc = exc_info.value
    assert exc.start_offset == 5


def test_parents_full_stack_nested():
    """Test that context/local_context capture root and innermost."""
    fmt = {
        "outer": {
            "inner": types.Int(byteorder="little", signed=False, size=4),
        }
    }
    obj = {"outer": {"inner": "bad"}}

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    exc = exc_info.value
    # encode: context is user's root, local_context is innermost parent
    assert exc.context == {"outer": {"inner": "bad"}}
    assert exc.local_context == {"inner": "bad"}


def test_offset_frozen_at_raise_time():
    """Test that offset is frozen at raise time, not dynamic."""
    fmt = {
        "a": types.Int(byteorder="big", signed=False, size=4),
        "b": types.Int(byteorder="big", signed=False, size=4),
    }
    # Only 5 bytes: 'a' succeeds (4 bytes), 'b' fails mid-read
    data = b"\x00\x00\x00\x01\x02"

    with pytest.raises(DecodeError) as exc_info:
        decode(data, fmt)

    exc = exc_info.value
    frozen_offset = exc.offset
    # Seeking the stream should NOT change the stored offset
    exc.stream.seek(0)
    assert exc.offset == frozen_offset


def test_decode_context_stitched_nested():
    """Test that decode context stitches partial tree from nested dicts."""
    fmt = {
        "a": types.Int(byteorder="big", signed=False, size=4),
        "b": {
            "c": types.Int(byteorder="big", signed=False, size=4),
        },
    }
    # 'a' decodes fine (4 bytes), 'b.c' fails (not enough data)
    data = b"\x00\x00\x00\x01\x02"

    with pytest.raises(DecodeError) as exc_info:
        decode(data, fmt)

    exc = exc_info.value
    # context is stitched: root has 'a' decoded, 'b' linked to partial inner dict
    assert exc.context == {"a": 1, "b": {}}  # 'b' is empty dict since it failed before decoding 'c'
    assert exc.local_context == {}


def test_decode_context_single_level():
    """Test that decode context at single dict level has partial fields."""
    fmt = {
        "x": types.Int(byteorder="big", signed=False, size=2),
        "y": types.Int(byteorder="big", signed=False, size=2),
        "z": types.Int(byteorder="big", signed=False, size=2),
    }
    # 'x' and 'y' decode fine (4 bytes), 'z' fails (1 byte left)
    data = b"\x00\x01\x00\x02\x03"

    with pytest.raises(DecodeError) as exc_info:
        decode(data, fmt)

    exc = exc_info.value
    assert exc.context["x"] == 1
    assert exc.context["y"] == 2
    assert "z" not in exc.context


def test_encode_context_is_user_root_object():
    """Test that encode context is the user's original root object."""
    fmt = {
        "a": types.Int(byteorder="big", signed=False, size=4),
        "b": types.Int(byteorder="big", signed=False, size=4),
    }
    obj = {"a": 1, "b": "bad"}

    with pytest.raises(EncodeError) as exc_info:
        encode(obj, fmt)

    exc = exc_info.value
    assert exc.context == {"a": 1, "b": "bad"}
    assert exc.local_context == {"a": 1, "b": "bad"}
