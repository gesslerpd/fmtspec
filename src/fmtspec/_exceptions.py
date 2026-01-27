from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from ._protocol import Format, InspectNode


@dataclass(slots=True, kw_only=True)
class Error(Exception):
    """Base class for all encoding/decoding errors.

    Attributes:
        message: Human-readable error description.
        context: The partially encoded/decoded object at the time of the error.
        cause: The underlying exception that caused this error.
        path: The path (field names/indices) leading to the error.
        inspect_node: Optional partial inspection tree showing state at time of error.
    """

    _PREAMBLE = "Error"

    message: str
    stream: BinaryIO
    fmt: Format | None
    context: Any
    cause: Exception | None
    path: tuple[str | int, ...]
    inspect_node: InspectNode | None

    def __str__(self) -> str:
        return f"{self._PREAMBLE} @ pos={self.stream.tell()} path={self.path}: {self.message}"


class EncodeError(Error):
    """Raised when an error occurs during encoding."""

    _PREAMBLE = "Error encoding"


class DecodeError(Error):
    """Raised when an error occurs during decoding."""

    _PREAMBLE = "Error decoding"
