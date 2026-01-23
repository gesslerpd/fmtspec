from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from struct import Struct
from typing import Any, BinaryIO, Literal

SIZE_MAP = {
    (1, False): "B",
    (1, True): "b",
    (2, False): "H",
    (2, True): "h",
    (4, False): "I",
    (4, True): "i",
    (8, False): "Q",
    (8, True): "q",
}


@dataclass(frozen=True, slots=True)
class Int:
    """Fixed-size integer type."""

    byteorder: Literal["little", "big"]
    signed: bool
    size: Literal[1, 2, 4, 8]
    enum: type[IntEnum] | type[IntFlag] | None = None
    # FUTURE: implement `strict` enum mode?
    _struct: Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        endian = ">" if self.byteorder == "big" else "<"
        key = (self.size, self.signed)
        object.__setattr__(self, "_struct", Struct(f"{endian}{SIZE_MAP[key]}"))

    def encode(self, value: int, stream: BinaryIO, **_: Any) -> None:
        # FUTURE: use the pack_into method for efficiency?
        # FUTURE: validate enum membership? or warn about it? strict mode?
        # if self.enum and value not in self.enum:
        #     value = self.enum(value)
        stream.write(self._struct.pack(value))

    def decode(self, stream: BinaryIO, **_: Any) -> int:
        raw = stream.read(self.size)
        if len(raw) < self.size:
            raise ValueError(f"Expected {self.size} bytes, got {len(raw)}")
        # FUTURE: use the unpack_from method for efficiency?
        value = self._struct.unpack(raw)[0]
        if self.enum and value in self.enum:
            # convert to enum member if possible
            value = self.enum(value)
        return value


# big endian variants (shorthand names)
u8 = u8be = Int(byteorder="big", signed=False, size=1)
u16 = u16be = Int(byteorder="big", signed=False, size=2)
u32 = u32be = Int(byteorder="big", signed=False, size=4)
u64 = u64be = Int(byteorder="big", signed=False, size=8)

i8 = i8be = Int(byteorder="big", signed=True, size=1)
i16 = i16be = Int(byteorder="big", signed=True, size=2)
i32 = i32be = Int(byteorder="big", signed=True, size=4)
i64 = i64be = Int(byteorder="big", signed=True, size=8)

# little endian variants
u8le = Int(byteorder="little", signed=False, size=1)
u16le = Int(byteorder="little", signed=False, size=2)
u32le = Int(byteorder="little", signed=False, size=4)
u64le = Int(byteorder="little", signed=False, size=8)

i8le = Int(byteorder="little", signed=True, size=1)
i16le = Int(byteorder="little", signed=True, size=2)
i32le = Int(byteorder="little", signed=True, size=4)
i64le = Int(byteorder="little", signed=True, size=8)
