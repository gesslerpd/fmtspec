from dataclasses import dataclass

from fmtspec import decode, encode, types


@dataclass
class ExampleDataClass:
    key: str
    number: int


@dataclass
class NestedDataClass:
    inner: ExampleDataClass
    flag: int


def test_roundtrip():
    obj = ExampleDataClass(key="value", number=42)
    fmt = {
        "key": types.TerminatedString(b"\0", encoding="utf-8"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, fmt, shape=ExampleDataClass)
    assert result == obj


def test_nested():
    obj = NestedDataClass(inner=ExampleDataClass(key="value", number=42), flag=1)
    fmt = {
        "inner": {
            "key": types.TerminatedString(b"\0", encoding="utf-8"),
            "number": types.Int(byteorder="little", signed=False, size=4),
        },
        "flag": types.Int(byteorder="big", signed=False, size=2),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00\x00\x01"

    result = decode(data, fmt, shape=NestedDataClass)
    assert result == obj


def test_partial_nested():
    obj = NestedDataClass(inner=ExampleDataClass(key="value", number=42), flag=1)
    partial_obj = {"inner": ExampleDataClass(key="value", number=42), "flag": 1}
    fmt = {
        "inner": {
            "key": types.TerminatedString(b"\0", encoding="utf-8"),
            "number": types.Int(byteorder="little", signed=False, size=4),
        },
        "flag": types.Int(byteorder="big", signed=False, size=2),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00\x00\x01"
    assert data == encode(partial_obj, fmt)

    assert decode(encode(partial_obj, fmt), fmt, shape=NestedDataClass) == obj


@dataclass
class DataClassWithDefaults:
    key: str
    number: int = 42


def test_defaults():
    obj = DataClassWithDefaults(key="value")
    fmt = {
        "key": types.TerminatedString(b"\0", encoding="utf-8"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, fmt, shape=DataClassWithDefaults)
    assert result == obj


def test_partial_fmt():
    obj = DataClassWithDefaults(key="value")
    fmt = {
        "key": types.TerminatedString(b"\0", encoding="utf-8"),
    }

    data = encode(obj, fmt)

    assert data == b"value\0"

    assert decode(data, fmt, shape=DataClassWithDefaults) == obj
    assert obj.number == 42
