from fmtspec import sizeof, types


def test_sizeof_int() -> None:
    """sizeof should return the byte size of Int types."""
    assert sizeof(types.u8) == sizeof(types.u8le) == sizeof(types.i8) == sizeof(types.i8le) == 1
    assert sizeof(types.u16) == sizeof(types.u16le) == sizeof(types.i16) == sizeof(types.i16le) == 2
    assert sizeof(types.u32) == sizeof(types.u32le) == sizeof(types.i32) == sizeof(types.i32le) == 4
    assert sizeof(types.u64) == sizeof(types.u64le) == sizeof(types.i64) == sizeof(types.i64le) == 8


def test_sizeof_fixed_bytes() -> None:
    """sizeof should return the size of fixed Bytes types."""
    assert sizeof(types.Bytes(size=0)) == 0
    assert sizeof(types.Bytes(size=16)) == 16
    assert sizeof(types.Bytes(size=1024)) == 1024


def test_sizeof_greedy_bytes_is_none() -> None:
    """sizeof should return None for greedy Bytes."""
    assert sizeof(types.Bytes()) is None


def test_sizeof_dict_format() -> None:
    """sizeof should sum the sizes of all fields in a dict format."""

    assert sizeof({"a": types.u8}) == 1
    assert sizeof({"a": types.u8, "b": types.u16}) == 3
    assert sizeof({"a": types.u8, "b": types.u16, "c": types.u32}) == 7


def test_sizeof_nested_dict_format() -> None:
    """sizeof should handle nested dict formats."""

    fmt = {
        "header": {"version": types.u8, "flags": types.u8},
        "length": types.u16,
    }
    assert sizeof(fmt) == 4


def test_sizeof_tuple_format() -> None:
    """sizeof should sum sizes for tuple/list formats."""

    assert sizeof((types.u8, types.u16)) == 3
    assert sizeof([types.u8, types.u8, types.u8]) == 3


def test_sizeof_dict_with_greedy_is_none() -> None:
    """sizeof should return None if any dict field is greedy."""

    fmt = {
        "length": types.u16,
        "data": types.Bytes(),  # greedy
    }
    assert sizeof(fmt) is None


def test_sizeof_variable_types_is_none() -> None:
    """sizeof should return None for variable-size types."""
    assert sizeof(types.Sized(length=types.u16, fmt=types.Bytes())) is ...
    assert sizeof(types.TakeUntil(types.String(), b"\0")) is ...
    assert sizeof(types.Switch(key=types.Ref("type"), cases={})) is ...
    assert sizeof(types.Sized(length=types.Ref("length"), fmt=types.Bytes())) is ...


def test_sizeof_empty_formats() -> None:
    """sizeof should return 0 for empty dict/tuple formats."""
    assert sizeof({}) == 0
    assert sizeof(()) == 0
    assert sizeof(i for i in range(0)) == 0
