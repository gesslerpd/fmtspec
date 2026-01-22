"""Count-prefixed collection types for binary serialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Literal

from .._stream import _decode_stream, _encode_stream

if TYPE_CHECKING:
    from .._protocol import Context, Format


@dataclass(frozen=True, slots=True)
class CountPrefixedArray:
    """Array type with element count prefix.

    Unlike PrefixedArray which uses byte-length prefix, this type
    uses an element count prefix. Useful for formats like MessagePack.
    """

    # class variables
    size: ClassVar[None] = None

    # fields
    byteorder: Literal["little", "big"]
    prefix_size: Literal[1, 2, 4, 8]
    element_fmt: Format

    def encode(self, value: list[Any], stream: BinaryIO, *, context: Context) -> None:
        count = len(value)
        stream.write(count.to_bytes(self.prefix_size, self.byteorder, signed=False))
        for elem in value:
            _encode_stream(elem, self.element_fmt, stream, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> list[Any]:
        prefix = stream.read(self.prefix_size)
        count = int.from_bytes(prefix, self.byteorder, signed=False)
        return [_decode_stream(stream, self.element_fmt, context=context)[0] for _ in range(count)]


@dataclass(frozen=True, slots=True)
class CountPrefixedMap:
    """Map type with entry count prefix.

    Uses an entry count prefix where each entry consists of a key-value pair.
    Both keys and values use the same element format.
    """

    # class variables
    size: ClassVar[None] = None

    # fields
    byteorder: Literal["little", "big"]
    prefix_size: Literal[1, 2, 4, 8]
    element_fmt: Format

    def encode(self, value: dict[Any, Any], stream: BinaryIO, *, context: Context) -> None:
        count = len(value)
        stream.write(count.to_bytes(self.prefix_size, self.byteorder, signed=False))
        for k, v in value.items():
            _encode_stream(k, self.element_fmt, stream, context=context)
            _encode_stream(v, self.element_fmt, stream, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> dict[Any, Any]:
        prefix = stream.read(self.prefix_size)
        count = int.from_bytes(prefix, self.byteorder, signed=False)
        result = {}
        for _ in range(count):
            key, _ = _decode_stream(stream, self.element_fmt, context=context)
            val, _ = _decode_stream(stream, self.element_fmt, context=context)
            result[key] = val
        return result
