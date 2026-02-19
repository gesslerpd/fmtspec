"""Lazy format evaluation for self-referential type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

from .._stream import _decode_stream, _encode_stream

if TYPE_CHECKING:
    from types import EllipsisType

    from .._protocol import Context, Format


@dataclass(frozen=True, slots=True)
class Optional:
    size: ClassVar[EllipsisType] = ...

    fmt: Format

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        if value is not None:
            _encode_stream(value, self.fmt, stream, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        try:
            return _decode_stream(stream, self.fmt, context=context)[0]
        except EOFError:
            return None
