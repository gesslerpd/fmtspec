from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from ._protocol import Format, InspectNode


class Error(Exception):
    """Base class for all fmtspec errors."""


@dataclass(slots=True, kw_only=True)
class StreamError(Error):
    """Base class for all encode/decode stream errors."""

    _PREAMBLE = "Error"

    message: str
    obj: Any | None
    stream: BinaryIO
    fmt: Format | None
    context: Any
    local_context: Any
    cause: Exception
    path: tuple[str | int, ...]
    inspect_node: InspectNode | None
    start_offset: int
    offset: int

    def __str__(self) -> str:
        if self._PREAMBLE is None:
            return f"{self.message}"
        return f"{self._PREAMBLE} @ [{self.start_offset}:{self.offset}] {self.path}: {self.message}"


class EncodeError(StreamError):
    """Raised when an error occurs during encoding."""

    _PREAMBLE = "Error encoding"


class DecodeError(StreamError):
    """Raised when an error occurs during decoding."""

    _PREAMBLE = "Error decoding"


@dataclass(slots=True, kw_only=True)
class TypeConversionError(Error):
    """Raised when a conversion error occurs during decoding for provided type."""

    message: str
    obj: Any
    type: type
    fmt: Format
    cause: Exception
    inspect_node: InspectNode | None

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True, kw_only=True)
class ExcessDecodeError(Error):
    """Raised when trailing bytes remain after `decode`.

    The stream is positioned at the start of the excess data, so further
    decoding attempts can be made directly via ``decode_stream(exc.stream, ...)``.

    Attributes:
        remaining: Number of unconsumed bytes left in the stream.
    """

    obj: Any
    stream: BinaryIO
    fmt: Format
    inspect_node: InspectNode | None
    remaining: int
    start_offset: int
    offset: int

    def __str__(self) -> str:
        return (
            f"Excess data @ [{self.start_offset}:{self.offset}]: {self.remaining} bytes remaining"
        )
