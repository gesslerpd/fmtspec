"""Byte array types for binary serialization."""

from dataclasses import dataclass
from typing import Any, BinaryIO

from ..stream import read_exactly, write_all


@dataclass(frozen=True, slots=True)
class Bytes:
    """Byte array type.

    If size is specified, reads/writes exactly that many bytes.
    If size is None (greedy), reads all remaining bytes from stream.
    """

    size: int | None = None

    def encode(self, value: bytes, stream: BinaryIO, **_: Any) -> None:
        if self.size is not None and len(value) != self.size:
            raise ValueError(f"Expected {self.size} bytes, got {len(value)}")
        write_all(stream, value)

    def decode(self, stream: BinaryIO, **_: Any) -> bytes:
        if self.size is None:
            return stream.read()
        return read_exactly(stream, self.size)


bytes_ = Bytes()
