from dataclasses import dataclass
from typing import ClassVar

from fmtspec._core import _convert, _create_new_instance, _to_builtins


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
    instance = _convert(data, NestedExample)

    assert instance.data_class.key == "value1"
    assert instance.data_class.number == 1
    assert instance.standard_class.key == "value2"
    assert instance.standard_class.number == 2


def test_to_builtins_recursive():
    obj = NestedExample(
        data_class=DataclassExample(key="value1", number=1),
        standard_class=StandardClassExample(key="value2", number=2),
    )
    data = _to_builtins(obj)

    assert data["data_class"]["key"] == "value1"
    assert data["data_class"]["number"] == 1
    assert data["standard_class"]["key"] == "value2"
    assert data["standard_class"]["number"] == 2
