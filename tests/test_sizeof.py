from fmtspec import sizeof, types


def test_sizeof_int() -> None:
    """sizeof should return the byte size of Int types."""
    assert sizeof(types.Int(byteorder="big", signed=False, size=1)) == 1
    assert sizeof(types.Int(byteorder="big", signed=False, size=2)) == 2
    assert sizeof(types.Int(byteorder="little", signed=True, size=4)) == 4
    assert sizeof(types.Int(byteorder="big", signed=False, size=8)) == 8


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
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)
    u4 = types.Int(byteorder="big", signed=False, size=4)

    assert sizeof({"a": u1}) == 1
    assert sizeof({"a": u1, "b": u2}) == 3
    assert sizeof({"a": u1, "b": u2, "c": u4}) == 7


def test_sizeof_nested_dict_format() -> None:
    """sizeof should handle nested dict formats."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "header": {"version": u1, "flags": u1},
        "length": u2,
    }
    assert sizeof(fmt) == 4


def test_sizeof_tuple_format() -> None:
    """sizeof should sum sizes for tuple/list formats."""
    u1 = types.Int(byteorder="big", signed=False, size=1)
    u2 = types.Int(byteorder="big", signed=False, size=2)

    assert sizeof((u1, u2)) == 3
    assert sizeof([u1, u1, u1]) == 3


def test_sizeof_dict_with_greedy_is_none() -> None:
    """sizeof should return None if any dict field is greedy."""
    u2 = types.Int(byteorder="big", signed=False, size=2)

    fmt = {
        "length": u2,
        "data": types.Bytes(),  # greedy
    }
    assert sizeof(fmt) is None


def test_sizeof_variable_types_is_none() -> None:
    """sizeof should return None for variable-size types."""
    prefix_fmt = types.Int(byteorder="big", signed=False, size=2)
    assert sizeof(types.Sized(length=prefix_fmt, fmt=types.Bytes())) is ...
    assert sizeof(types.TakeUntil(types.String(), b"\0")) is ...
    assert sizeof(types.Switch(key=types.Ref("type"), cases={})) is None
    assert sizeof(types.Sized(length=types.Ref("length"), fmt=types.Bytes())) is ...


def test_sizeof_empty_formats() -> None:
    """sizeof should return 0 for empty dict/tuple formats."""
    assert sizeof({}) == 0
    assert sizeof(()) == 0
    assert sizeof(i for i in range(0)) == 0
