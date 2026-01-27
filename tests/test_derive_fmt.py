from dataclasses import dataclass, field
from io import BytesIO
from typing import Annotated, ClassVar

import msgspec
import pytest

from fmtspec import EncodeError, decode, decode_stream, derive_fmt, encode, types

INT_FMT = types.Int(byteorder="little", signed=False, size=4)
STR_FMT = types.TakeUntil(types.Str(), b"\0")

FMT = {
    "key": STR_FMT,
    "number": INT_FMT,
}


@dataclass(frozen=True, slots=True)
class DataclassExample:
    """An example data class to demonstrate derive_fmt usage."""

    sentinel: ClassVar[object] = object()

    key: Annotated[str, STR_FMT]
    number: Annotated[int, INT_FMT]


@dataclass
class MismatchTypeFmtShape:
    sentinel: ClassVar[object] = object()

    key: Annotated[int, STR_FMT]
    number: Annotated[str, INT_FMT]


class StandardClassExample:
    """An example standard class to demonstrate derive_fmt usage."""

    __slots__ = ("key", "number")

    sentinel: ClassVar[object] = object()

    key: Annotated[str, STR_FMT]
    number: Annotated[int, INT_FMT]

    def __init__(self, key: str, number: int) -> None:
        self.key = key
        self.number = number

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StandardClassExample):
            return NotImplemented
        return self.key == other.key and self.number == other.number

    def __hash__(self) -> int:
        return hash((self.key, self.number))


class StructExample(msgspec.Struct):
    key: Annotated[str, msgspec.Meta(min_length=0), STR_FMT]
    number: Annotated[int, msgspec.Meta(ge=0), Annotated[int, INT_FMT]]
    sentinel: ClassVar[object] = object()


@dataclass
class NestedExample:
    """An example class with nested Annotated fields."""

    data_class: DataclassExample
    standard_class: StandardClassExample


class NestedStructExample(msgspec.Struct):
    key: Annotated[str, msgspec.Meta(min_length=0), STR_FMT]
    number: Annotated[int, msgspec.Meta(ge=0), Annotated[int, INT_FMT]]
    data_class: Annotated[DataclassExample, msgspec.Meta()]
    sentinel: ClassVar[object] = object()


class Empty:
    sentinel: ClassVar[object] = object()


@dataclass
class NoInitDataclassExample:
    # init=False works as long as a default exists
    key: Annotated[str, STR_FMT] = field(default="value", init=False)
    number: Annotated[int, INT_FMT] = 42
    other: Annotated[int, INT_FMT] = field(init=False)


@dataclass
class EmptyDataclass:
    pass


class EmptyStruct(msgspec.Struct):
    sentinel: ClassVar[object] = object()


def test_empty_class():
    assert derive_fmt(Empty) == {}
    assert derive_fmt(EmptyDataclass) == {}
    assert derive_fmt(EmptyStruct) == {}


def test_dataclass():
    derived_fmt = derive_fmt(DataclassExample)
    assert derived_fmt == FMT


def test_no_init_dataclass():
    derived_fmt = derive_fmt(NoInitDataclassExample)
    assert derived_fmt == {
        "key": STR_FMT,
        "number": INT_FMT,
        "other": INT_FMT,
    }


def test_mismatch_type():
    derived_fmt = derive_fmt(MismatchTypeFmtShape)
    assert derived_fmt == FMT


def test_standard_class():
    derived_fmt = derive_fmt(StandardClassExample)
    assert derived_fmt == FMT


def test_msgspec():
    derived_fmt = derive_fmt(StructExample)
    assert derived_fmt == FMT


def test_nested():
    derived_fmt = derive_fmt(NestedExample)
    expected_fmt = {
        "data_class": FMT,
        "standard_class": FMT,
    }
    assert derived_fmt == expected_fmt


def test_msgspec_nested():
    derived_fmt = derive_fmt(NestedStructExample)
    assert derived_fmt == {
        **FMT,
        "data_class": FMT,
    }


def test_empty_roundtrip():
    encoded = encode(EmptyDataclass())
    assert encoded == b""
    decoded = decode(encoded, shape=EmptyDataclass)
    assert isinstance(decoded, EmptyDataclass)


def test_dataclass_roundtrip():
    obj = DataclassExample(key="value", number=42)

    data = encode(obj)
    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, shape=DataclassExample)
    assert result == obj

    assert result.sentinel is DataclassExample.sentinel is obj.sentinel


def test_dataclass_no_init_roundtrip():
    obj = NoInitDataclassExample()

    assert obj.key == "value"
    assert obj.number == 42

    obj.key = "val"
    obj.number = 43

    with pytest.raises(EncodeError, match="other"):
        encode(obj)

    # init=False w/ no default works as long as the attribute is set before encoding
    obj.other = 42

    data = encode(obj)

    assert data == b"val\0\x2b\x00\x00\x00\x2a\x00\x00\x00"

    result = decode(data, shape=NoInitDataclassExample)
    assert result == obj


def test_msgspec_roundtrip():
    obj = StructExample(key="value", number=42)

    data = encode(obj)
    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, shape=StructExample)
    assert result == obj

    assert result.sentinel is StructExample.sentinel is obj.sentinel


def test_decode_without_fmt_or_shape_raises():
    with pytest.raises(TypeError):
        decode(b"")


def test_decode_stream_requires_fmt_or_shape():
    stream = BytesIO(b"")
    with pytest.raises(TypeError):
        decode_stream(stream)


@dataclass
class UnannotatedDataclassExample:
    sentinel: ClassVar[Annotated[str, STR_FMT]] = "class_var"

    number: Annotated[int, INT_FMT]
    key: str
    other: Annotated[int, INT_FMT]


def test_unannotated_dataclass_raises():
    with pytest.raises(
        TypeError,
        match="Cannot derive format for field 'key' without an associated format type",
    ):
        derive_fmt(UnannotatedDataclassExample)


@dataclass
class NestedUnannotatedExample:
    number: Annotated[int, INT_FMT]
    should_error: UnannotatedDataclassExample


def test_nested_unannotated_raises():
    with pytest.raises(
        TypeError,
        match="Cannot derive format for field 'key' without an associated format type",
    ):
        derive_fmt(NestedUnannotatedExample)


@pytest.mark.xfail(strict=True, raises=TypeError)
def test_standard_class_roundtrip():
    # FUTURE: handle standard class instances with attribute lookup?
    obj = StandardClassExample(key="value", number=42)
    data = encode(obj)

    assert data == b"value\0\x2a\x00\x00\x00"
    result = decode(data, shape=StandardClassExample)
    assert result == obj

    assert result.sentinel is StandardClassExample.sentinel is obj.sentinel


@pytest.mark.xfail(strict=True, raises=msgspec.ValidationError)
def test_mismatch_type_roundtrip():
    # FUTURE: fallback for decode conversion with mismatched types?
    # would require disabling msgpack validation (warn of type mistmatch on derive_fmt?)
    obj = MismatchTypeFmtShape(key="value", number=42)  # type: ignore[arg-type]

    data = encode(obj)
    assert data == b"value\0\x2a\x00\x00\x00"

    result = decode(data, shape=MismatchTypeFmtShape)

    assert result.sentinel is MismatchTypeFmtShape.sentinel is obj.sentinel
