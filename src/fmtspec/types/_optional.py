"""Lazy format evaluation for self-referential type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

from .._core import decode_stream
from .._exceptions import DecodeError
from .._stream import _encode_stream

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

    def decode(self, stream: BinaryIO, **_) -> Any:
        try:
            return decode_stream(stream, self.fmt)
        except DecodeError:
            return None
