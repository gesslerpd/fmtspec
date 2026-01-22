"""Float types for binary serialization."""

import struct
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Literal

# Float size constants
FLOAT32_SIZE = 4
FLOAT64_SIZE = 8


@dataclass(frozen=True, slots=True)
class Float:
    """IEEE 754 floating point type."""

    byteorder: Literal["little", "big"]
    size: Literal[4, 8]
    _struct: struct.Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        endian = ">" if self.byteorder == "big" else "<"
        precision = "f" if self.size == FLOAT32_SIZE else "d"
        object.__setattr__(self, "_struct", struct.Struct(f"{endian}{precision}"))

    def encode(self, value: float, stream: BinaryIO, **_: Any) -> None:
        stream.write(self._struct.pack(value))

    def decode(self, stream: BinaryIO, **_: Any) -> float:
        raw = stream.read(self.size)
        return self._struct.unpack(raw)[0]
