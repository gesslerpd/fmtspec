from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from fmtspec._core import _convert, _create_new_instance, _to_builtins, frozendict, is_all_primitive


@dataclass(frozen=True, slots=True)
class DataclassExample:
    """An example data class to demonstrate derive_fmt usage."""

    sentinel: ClassVar[object] = object()

    key: str
    number: int


class StandardClassExample:
    """An example standard class to demonstrate derive_fmt usage."""

    __slots__ = ("key", "number")

    sentinel: ClassVar[object] = object()

    key: str
    number: int

    def __init__(self, key: str, number: int) -> None:
        self.key = key
        self.number = number

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StandardClassExample):
            return NotImplemented
        return self.key == other.key and self.number == other.number

    def __hash__(self) -> int:
        return hash((self.key, self.number))


class StandardClassProperty:
    """An example standard class to demonstrate derive_fmt usage."""

    __slots__ = ("key1", "number1")

    sentinel: ClassVar[object] = object()

    key1: str
    number1: int

    def __init__(self, key: str, number: int) -> None:
        self.key1 = key
        self.number1 = number


class NestedExample:
    """An example class with nested Annotated fields."""

    data_class: DataclassExample
    standard_class: StandardClassExample

    def __init__(
        self,
        data_class: DataclassExample,
        standard_class: StandardClassExample,
    ) -> None:
        self.data_class = data_class
        self.standard_class = standard_class


def test_create_new_instance():
    data = {"key": "value", "number": 42}
    instance = _create_new_instance(StandardClassExample, data)
    instance.key = data["key"]
    instance.number = data["number"]

    assert instance.key == "value"
    assert instance.number == 42


def test_create_new_instance_dataclass():
    data = {"key": "value", "number": 42}
    instance = _create_new_instance(DataclassExample, data)

    assert instance.key == "value"
    assert instance.number == 42


def test_create_new_instance_property():
    data = {"key": "value", "number": 42}
    instance = _create_new_instance(StandardClassProperty, data)
    instance.key1 = data["key"]
    instance.number1 = data["number"]

    assert instance.key1 == "value"
    assert instance.number1 == 42


def test_convert_recursive():
    data = {
        "data_class": {"key": "value1", "number": 1},
        "standard_class": {"key": "value2", "number": 2},
    }
    instance = _convert(data, NestedExample, recursive=True)

    assert instance.data_class.key == "value1"
    assert instance.data_class.number == 1
    assert instance.standard_class.key == "value2"
    assert instance.standard_class.number == 2


def test_to_builtins_recursive():
    obj = NestedExample(
        data_class=DataclassExample(key="value1", number=1),
        standard_class=StandardClassExample(key="value2", number=2),
    )
    data = _to_builtins(obj, recursive=True)

    assert data["data_class"]["key"] == "value1"
    assert data["data_class"]["number"] == 1
    assert data["standard_class"]["key"] == "value2"
    assert data["standard_class"]["number"] == 2


@dataclass
class SpecialExample:
    key: str
    number: int

    @classmethod
    def from_builtins(cls, data: dict) -> SpecialExample:
        key, number = data["nested"]
        return cls(key, number)

    def to_builtins(self) -> dict:
        return {"nested": (self.key, self.number)}


# remove dataclass fields after creation so msgspec sees it as standard class
del SpecialExample.__dataclass_fields__


def test_to_builtins_special():
    obj = SpecialExample(key="value", number=42)
    data = _to_builtins(obj, recursive=False)

    assert data == {"nested": ("value", 42)}

    result = _convert(data, SpecialExample, recursive=False)
    assert result == obj
    assert isinstance(result, SpecialExample)


def test_is_all_primitive_supports_frozendict_nested():
    value = [frozendict({"b": 2}), {"c": (3, 4)}]
    obj = {frozendict({"a": 1}): value}

    assert is_all_primitive(obj) is True


def test_is_all_primitive_supports_bytes_like():
    obj = {b"": b"x", "y": bytearray(b"z"), "m": memoryview(b"abc")}
    assert is_all_primitive(obj) is True


def test_to_builtins_preserves_frozendict_keys_with_nested_values():
    # msgspec.to_builtins will raise TypeError if a dict key would become an
    # unhashable built-in dict; _to_builtins should fall back to returning the
    # original object when it's already all-primitive.
    value = [frozendict({"b": 2}), {"c": (3, 4)}]
    obj = {frozendict({"a": 1}): value}

    result = _to_builtins(obj, recursive=False)
    assert result is obj
    (key,) = obj.keys()
    assert isinstance(key, frozendict)


def test_frozendict_equality():
    a1 = {"x": 1, b"y": 2}
    b1 = {b"y": 2, "x": 1}
    c1 = {"x": 1, b"y": 3}

    a = frozendict(a1)
    b = frozendict(b1)
    c = frozendict(c1)

    assert a == b
    assert a1 == b
    assert b1 == a
    assert a == b1
    assert b == a1

    assert a != c
    assert a1 != c
    assert c1 != a
    assert a != c1
    assert b != c
    assert b1 != c
