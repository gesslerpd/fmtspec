from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._protocol import Format, InspectNode


@dataclass(slots=True)
class Error(Exception):
    """Base class for all encoding/decoding errors.

    Attributes:
        message: Human-readable error description.
        context: The partially encoded/decoded object at the time of the error.
        cause: The underlying exception that caused this error.
        path: The path (field names/indices) leading to the error.
        inspect_node: Optional partial inspection tree showing state at time of error.
    """

    message: str
    fmt: Format | None
    context: Any
    cause: Exception | None
    path: tuple[str | int, ...]
    inspect_node: InspectNode | None

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class EncodeError(Error):
    """Raised when an error occurs during encoding."""


@dataclass(slots=True)
class DecodeError(Error):
    """Raised when an error occurs during decoding."""
