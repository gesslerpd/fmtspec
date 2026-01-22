"""Bitfield types for binary serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, BinaryIO, Literal

from ._int import Int, u8, u16, u32, u64

SIZE_MAP = {1: u8, 2: u16, 4: u32, 8: u64}


@dataclass(frozen=True, slots=True)
class Bitfield:
    bits: int
    # zero means auto-assign
    offset: int = 0
    align: Literal[1, 2, 4, 8] | None = None
    # aka max value
    mask: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.bits <= 0:
            raise ValueError("bits must be positive")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")

        object.__setattr__(self, "mask", (1 << self.bits) - 1)


@dataclass(frozen=True, slots=True)
class Bitfields:
    fields: dict[str, Bitfield]
    size: Literal[0, 1, 2, 4, 8] = 0
    _int_type: Int = field(init=False, repr=False, compare=False)
    _offsets: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:  # noqa: PLR0912, PLR0915
        if not self.size:
            # Simplified pass: convert to a list and scan by index. Maintain
            # `running_bits` for sequential offset-less fields and
            # `max_offset_bits` for explicit offsets; take the max at end.
            fields = list(self.fields.values())
            n = len(fields)
            i = 0
            total_bits = 0

            while i < n:
                bf = fields[i]
                if bf.offset:
                    total_bits = bf.offset + bf.bits
                    i += 1
                    continue

                if bf.align is not None:
                    forced_bits = bf.align * 8
                    group_bits = bf.bits
                    j = i + 1
                    while j < n and not fields[j].offset and fields[j].align is None:
                        group_bits += fields[j].bits
                        j += 1
                    if group_bits > forced_bits:
                        raise ValueError("Bitfield exceeds forced align group size")
                    total_bits += forced_bits
                    i = j
                    continue

                # auto group
                group_bits = bf.bits
                j = i + 1
                while j < n and not fields[j].offset and fields[j].align is None:
                    group_bits += fields[j].bits
                    j += 1
                total_bits += group_bits
                i = j

            size = 1
            while total_bits > size * 8:
                size *= 2
            object.__setattr__(self, "size", size)

        if self.size not in SIZE_MAP:
            raise ValueError(f"Unsupported size {self.size}")
        object.__setattr__(self, "_int_type", SIZE_MAP[self.size])

        max_bits = self.size * 8
        nbits = 0
        offsets = {}
        for name, bitfield in self.fields.items():
            if bitfield.offset:
                if bitfield.offset < nbits:
                    raise ValueError("Bitfield offsets overlap")
                offsets[name] = bitfield.offset
                nbits = bitfield.offset + bitfield.bits
            else:
                offsets[name] = nbits
                nbits += bitfield.bits

        if nbits > max_bits:
            raise ValueError("Bitfield exceeds total size")

        object.__setattr__(self, "_offsets", offsets)

    def encode(self, value: Any, stream: BinaryIO, **_: Any) -> None:
        int_val = 0
        for name, bitfield in self.fields.items():
            if name not in value:
                raise ValueError(f"Missing field {name!r}")
            val = value[name]
            if val < 0 or val > bitfield.mask:
                raise ValueError(f"Value {val} for field {name!r} out of range")
            int_val |= val << self._offsets[name]
        self._int_type.encode(int_val, stream, **_)

    def decode(self, stream: BinaryIO, **_: Any) -> dict[str, int | bool]:
        int_val = self._int_type.decode(stream, **_)
        return {
            name: (int_val >> self._offsets[name]) & bitfield.mask
            for name, bitfield in self.fields.items()
        }
