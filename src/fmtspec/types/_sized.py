"""Sized type for context-driven dynamic sizing."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

from .._stream import _decode_stream, _encode_stream
from ._ref import Ref

if TYPE_CHECKING:
    from types import EllipsisType

    from .._protocol import Context, Format, Type


@dataclass(frozen=True, slots=True)
class Sized:
    """Dynamically sized type using a context key for length.

    Wraps an inner format and uses a sibling field value to determine
    the byte length during encoding/decoding.

    Example:
        fmt = {
            "length": u2,
            "data": Sized(key="length", fmt=GreedyBytes()),
        }

    During decode, reads `length` bytes from the stream and passes
    that bounded data to the inner format.

    During encode, encodes the value with the inner format and verifies
    the encoded length matches the sibling field value.
    """

    # class variables
    size: ClassVar[EllipsisType] = ...

    # fields
    length: Ref | Type
    fmt: Format

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        """Encode value and verify length matches context[length]."""

        buffer = BytesIO()
        _encode_stream(value, self.fmt, buffer, context=context)
        encoded = buffer.getvalue()

        if isinstance(self.length, Ref):
            expected_length = self.length.resolve(context)
            if len(encoded) != expected_length:
                raise ValueError(
                    f"Encoded length {len(encoded)} does not match "
                    f"expected length {expected_length} from key {self.length!r}"
                )
        else:
            self.length.encode(len(encoded), stream, context=context)

        stream.write(encoded)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Decode using length from context[length]."""
        if isinstance(self.length, Ref):
            length = self.length.resolve(context)
        else:
            length = self.length.decode(stream, context=context)
        bounded_data = stream.read(length)
        if len(bounded_data) != length:
            raise ValueError(f"Expected {length} bytes, got {len(bounded_data)}")

        inner_stream = BytesIO(bounded_data)
        return _decode_stream(inner_stream, self.fmt, context=context)[0]
