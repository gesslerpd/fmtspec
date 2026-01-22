from dataclasses import dataclass, field
from struct import Struct
from typing import Any, BinaryIO, ClassVar

from ._int import Int


@dataclass(frozen=True, slots=True)
class String:
    size: int | None = None
    encoding: str = "utf-8"

    def encode(self, value: str, stream: BinaryIO, **_: Any) -> None:
        data = value.encode(self.encoding)
        if self.size is not None and len(data) != self.size:
            raise ValueError(f"Expected {self.size} bytes, got {len(data)}")
        stream.write(data)

    def decode(self, stream: BinaryIO, **_: Any) -> str:
        if self.size is None:
            return stream.read().decode(self.encoding)
        return stream.read(self.size).decode(self.encoding)


@dataclass(frozen=True, slots=True)
class PrefixedStr:
    """Length-prefixed UTF-8 string type.

    The length prefix is an unsigned integer of the specified size and byte order.
    Length is in bytes (not characters).
    """

    # class variables
    size: ClassVar[None] = None

    # fields
    prefix_fmt: Int
    encoding: str = "utf-8"
    prefix_struct: Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # perf: borrow prefix_struct from prefix_fmt directly
        object.__setattr__(self, "prefix_struct", self.prefix_fmt.prefix_struct)

    def encode(self, value: str, stream: BinaryIO, **_: Any) -> None:
        data = value.encode(self.encoding)
        length = len(data)
        stream.write(self.prefix_struct.pack(length))
        stream.write(data)

    def decode(self, stream: BinaryIO, **_: Any) -> str:
        raw = stream.read(self.prefix_struct.size)
        length = self.prefix_struct.unpack(raw)[0]
        return stream.read(length).decode(self.encoding)
