"""Byte array types for binary serialization."""

from dataclasses import dataclass, field
from struct import Struct
from typing import Any, BinaryIO, ClassVar

from ._int import Int


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
        stream.write(value)

    def decode(self, stream: BinaryIO, **_: Any) -> bytes:
        if self.size is None:
            return stream.read()
        return stream.read(self.size)


@dataclass(frozen=True, slots=True)
class PrefixedBytes:
    """Length-prefixed byte array type.

    The length prefix is an unsigned integer of the specified size and byte order.
    """

    # class variables
    size: ClassVar[None] = None

    # fields
    prefix_fmt: Int
    prefix_struct: Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # perf: borrow prefix_struct from prefix_fmt directly
        object.__setattr__(self, "prefix_struct", self.prefix_fmt.prefix_struct)

    def encode(self, value: bytes, stream: BinaryIO, **_: Any) -> None:
        length = len(value)
        stream.write(self.prefix_struct.pack(length))
        stream.write(value)

    def decode(self, stream: BinaryIO, **_: Any) -> bytes:
        length = self.prefix_struct.unpack(stream.read(self.prefix_struct.size))[0]
        return stream.read(length)
