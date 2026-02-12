"""Lazy format evaluation for self-referential type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from types import EllipsisType
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

from .._stream import _decode_stream, _encode_stream

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._protocol import Context, Format


@dataclass(frozen=True, slots=True)
class Lazy:
    """Lazily evaluated format reference.

    Wraps a callable that returns a Format, deferring evaluation until
    encode/decode time. This enables self-referential format definitions
    where a type needs to reference itself for recursive structures.

    Example:
        # Forward reference to a type defined later
        msgpack: MsgPack  # Type hint for IDE support

        # Use Lazy to defer resolution
        array_elements = Lazy(lambda: msgpack)
        array16 = Array(
            array_elements, dims=(u16,)
        )

        # Now define the actual type
        msgpack = MsgPack(...)  # Lambda captures 'msgpack' by name

    The factory function is called on every encode/decode operation.
    For module-level singletons, this is essentially free (just a name lookup).
    """

    size: ClassVar[EllipsisType] = ...

    get_format: Callable[[], Format]

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        """Encode by delegating to the lazily-resolved format."""
        fmt = self.get_format()
        _encode_stream(value, fmt, stream, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Decode by delegating to the lazily-resolved format."""
        fmt = self.get_format()
        return _decode_stream(stream, fmt, context=context)[0]
