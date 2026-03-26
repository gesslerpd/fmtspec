"""Float types for binary serialization."""

import struct
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Literal

from ..stream import read_exactly, write_all

# Float size constants
FLOAT32_SIZE = 4
FLOAT64_SIZE = 8


@dataclass(frozen=True, slots=True)
class Float:
    """Fixed-width IEEE 754 floating-point format."""

    # can use `sys.byteorder` for native byte order
    byteorder: Literal["little", "big"]
    size: Literal[4, 8]
    _struct: struct.Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        endian = ">" if self.byteorder == "big" else "<"
        precision = "f" if self.size == FLOAT32_SIZE else "d"
        object.__setattr__(self, "_struct", struct.Struct(f"{endian}{precision}"))

    def encode(self, stream: BinaryIO, value: float, **_: Any) -> None:
        # FUTURE: use the pack_into method for efficiency?
        write_all(stream, self._struct.pack(value))

    def decode(self, stream: BinaryIO, **_: Any) -> float:
        raw = read_exactly(stream, self.size)
        # FUTURE: use the unpack_from method for efficiency?
        return self._struct.unpack(raw)[0]


# big endian variants (shorthand names)
f32 = f32be = Float(byteorder="big", size=4)
f64 = f64be = Float(byteorder="big", size=8)

# little endian variants
f32le = Float(byteorder="little", size=4)
f64le = Float(byteorder="little", size=8)
