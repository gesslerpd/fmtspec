from dataclasses import dataclass
from enum import IntEnum, IntFlag, auto

import pytest

from fmtspec import ShapeError, decode, encode, types


class NumberEnum(IntEnum):
    NOTHING = 0
    EVERYTHING = 42


class Permission(IntFlag):
    READ = auto()
    WRITE = auto()
    EXECUTE = auto()


@dataclass
class ExampleDataClass:
    key: str
    number: int  # `int | NumberEnum` is not supported directly by msgspec


@dataclass
class StrictEnum:
    key: str
    number: NumberEnum


@dataclass
class StrictFlag:
    key: str
    number: Permission


@dataclass
class NestedDataClass:
    inner: ExampleDataClass
    flag: int


def test_roundtrip():
    obj = ExampleDataClass(key="value", number=NumberEnum.EVERYTHING)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
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
            "key": types.TakeUntil(types.Str(), b"\0"),
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
            "key": types.TakeUntil(types.Str(), b"\0"),
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
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    data = encode(obj, fmt)

    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, fmt, shape=DataClassWithDefaults)
    assert result == obj


def test_partial_fmt():
    obj = DataClassWithDefaults(key="value")
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
    }

    data = encode(obj, fmt)

    assert data == b"value\0"

    assert decode(data, fmt, shape=DataClassWithDefaults) == obj
    assert obj.number == 42


def test_strict_enum():
    obj = StrictEnum(key="value", number=42)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=NumberEnum),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x2a\x00\x00\x00"
    result = decode(data, fmt, shape=StrictEnum)
    assert result == obj
    assert result.number.name == "EVERYTHING"

    obj = StrictEnum(key="value", number=NumberEnum.EVERYTHING)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=NumberEnum),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x2a\x00\x00\x00"
    result = decode(data, fmt, shape=StrictEnum)
    assert result == obj
    assert result.number.name == "EVERYTHING"

    # FUTURE: should this error? right now doesn't error until decoding
    encode(StrictEnum(key="value", number=1), fmt)

    with pytest.raises(ShapeError, match="Invalid enum value 1"):
        decode(b"value\0\x01\x00\x00\x00", fmt, shape=StrictEnum)


def test_strict_flag():
    obj = StrictFlag(key="value", number=Permission.READ | Permission.WRITE)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=Permission),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x03\x00\x00\x00"
    result = decode(data, fmt, shape=StrictFlag)
    assert result == obj
    assert result.number.name == "READ|WRITE"


def test_unstrict_enum():
    obj = StrictEnum(key="value", number=NumberEnum.EVERYTHING)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=NumberEnum),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x2a\x00\x00\x00"
    result = decode(data, fmt)
    assert encode(result, fmt) == data
    assert result["number"].name == "EVERYTHING"

    obj = StrictFlag(key="value", number=0)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=NumberEnum),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x00\x00\x00\x00"
    result = decode(data, fmt)
    assert encode(result, fmt) == data
    assert result["number"].name == "NOTHING"

    obj = StrictEnum(key="value", number=8)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=NumberEnum),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x08\x00\x00\x00"
    result = decode(data, fmt)
    assert encode(result, fmt) == data
    assert not hasattr(result["number"], "name")


def test_unstrict_flag():
    obj = StrictFlag(key="value", number=Permission.READ | Permission.WRITE)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=Permission),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x03\x00\x00\x00"
    result = decode(data, fmt)
    assert encode(result, fmt) == data
    assert result["number"].name == "READ|WRITE"

    obj = StrictFlag(key="value", number=Permission(0))
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=Permission),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x00\x00\x00\x00"
    result = decode(data, fmt)
    assert encode(result, fmt) == data
    assert result["number"].name is None

    obj = StrictFlag(key="value", number=8)
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4, enum=Permission),
    }
    data = encode(obj, fmt)
    assert data == b"value\0\x08\x00\x00\x00"
    result = decode(data, fmt)
    assert encode(result, fmt) == data
    assert result["number"].name is None
