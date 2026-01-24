from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from struct import Struct
from typing import Any, BinaryIO, Literal

SIZE_MAP = {
    1: "B",
    2: "H",
    4: "I",
    8: "Q",
}


@dataclass(frozen=True, slots=True)
class _Struct:
    byteorder: Literal["little", "big"]
    signed: bool
    size: int

    def pack(self, value: int) -> bytes:
        return value.to_bytes(self.size, byteorder=self.byteorder, signed=self.signed)

    def unpack(self, data: bytes) -> tuple[int]:
        # assert len(data) == self.size
        return (int.from_bytes(data, byteorder=self.byteorder, signed=self.signed),)


@dataclass(frozen=True, slots=True)
class Int:
    """Fixed-size integer type."""

    # can use `sys.byteorder` for native byte order
    byteorder: Literal["little", "big"]
    signed: bool
    size: Literal[1, 2, 4, 8, 16]  # this can be extended for larger sizes
    enum: type[IntEnum] | type[IntFlag] | None = None
    # FUTURE: implement `strict` enum mode?
    _struct: Struct | _Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        endian = ">" if self.byteorder == "big" else "<"
        if self.size in SIZE_MAP:
            format_str = f"{endian}{SIZE_MAP[self.size]}"
            if self.signed:
                format_str = format_str.lower()
            object.__setattr__(self, "_struct", Struct(format_str))
        else:
            # slower fallback for large integers
            object.__setattr__(self, "_struct", _Struct(self.byteorder, self.signed, self.size))

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

# unsigned
u8 = u8be = Int(byteorder="big", signed=False, size=1)
u16 = u16be = Int(byteorder="big", signed=False, size=2)
u32 = u32be = Int(byteorder="big", signed=False, size=4)
u64 = u64be = Int(byteorder="big", signed=False, size=8)
u128 = u128be = Int(byteorder="big", signed=False, size=16)

# signed
i8 = i8be = Int(byteorder="big", signed=True, size=1)
i16 = i16be = Int(byteorder="big", signed=True, size=2)
i32 = i32be = Int(byteorder="big", signed=True, size=4)
i64 = i64be = Int(byteorder="big", signed=True, size=8)
i128 = i128be = Int(byteorder="big", signed=True, size=16)

# little endian variants

# unsigned
u8le = Int(byteorder="little", signed=False, size=1)
u16le = Int(byteorder="little", signed=False, size=2)
u32le = Int(byteorder="little", signed=False, size=4)
u64le = Int(byteorder="little", signed=False, size=8)
u128le = Int(byteorder="little", signed=False, size=16)

# signed
i8le = Int(byteorder="little", signed=True, size=1)
i16le = Int(byteorder="little", signed=True, size=2)
i32le = Int(byteorder="little", signed=True, size=4)
i64le = Int(byteorder="little", signed=True, size=8)
i128le = Int(byteorder="little", signed=True, size=16)
