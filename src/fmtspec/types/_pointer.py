from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

from ..stream import decode_stream, encode_stream, seek_to
from ._ref import Ref

if TYPE_CHECKING:
    from types import EllipsisType

    from .._protocol import Context, Format, Type


type OffsetResolver = int | Ref | Callable[[Context], int]


def _resolve_offset(value: OffsetResolver, context: Context) -> int:
    if isinstance(value, Ref):
        return int(value.resolve(context))
    if isinstance(value, int):
        return value
    return int(value(context))


@dataclass(frozen=True, slots=True)
class Pointer:
    """Read or write a value stored elsewhere in the stream via an offset field.

    The pointer field itself occupies the size of ``offset`` at the current stream
    position. The pointed value is read or written at ``base + decoded_offset`` on
    the same seekable stream, after which the original cursor position is restored.

    The decoded result is the pointed value rather than the offset. For encoding,
    the caller must provide a mapping with both the offset and pointed value.
    """

    offset: Type
    fmt: Format
    _: KW_ONLY
    base: OffsetResolver = 0
    allow_null: bool = False
    null_value: Any = None
    offset_key: str | int = "offset"
    value_key: str | int = "value"
    validate_target: Callable[[int], None] | None = None
    size: int | EllipsisType = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", getattr(self.offset, "size", ...))

    def _absolute_offset(self, offset_value: int, context: Context) -> int:
        absolute_offset = _resolve_offset(self.base, context) + offset_value
        if self.validate_target is not None:
            self.validate_target(absolute_offset)
        return absolute_offset

    def _split_value(self, value: Any) -> tuple[int, Any]:
        if isinstance(value, Mapping):
            return int(value[self.offset_key]), value[self.value_key]
        raise TypeError("Pointer.encode expects a mapping with offset/value entries")

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        offset_value, pointed_value = self._split_value(value)
        encode_stream(stream, offset_value, self.offset, context=context, key=self.offset_key)

        if self.allow_null and offset_value == 0:
            return

        absolute_offset = self._absolute_offset(offset_value, context)
        with seek_to(stream, absolute_offset):
            encode_stream(stream, pointed_value, self.fmt, context=context, key=self.value_key)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        offset_value = int(decode_stream(stream, self.offset, context=context, key=self.offset_key))

        if self.allow_null and offset_value == 0:
            return self.null_value

        absolute_offset = self._absolute_offset(offset_value, context)
        with seek_to(stream, absolute_offset):
            return decode_stream(stream, self.fmt, context=context, key=self.value_key)
