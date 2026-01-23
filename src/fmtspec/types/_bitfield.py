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
    # computed minimal size in bytes for this single bitfield when used alone
    size: Literal[1, 2, 4, 8] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.bits <= 0:
            raise ValueError("bits must be positive")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")

        object.__setattr__(self, "mask", (1 << self.bits) - 1)

        # compute minimal size (in bytes) required to hold this bitfield
        total_bits = self.offset + self.bits
        if self.align:
            forced_bits = self.align * 8
            if total_bits > forced_bits:
                raise ValueError("Bitfield exceeds forced align group size")
            total_bits = forced_bits

        # ensure size is power-of-two bytes
        size = 8
        while total_bits > size:
            size *= 2
        object.__setattr__(self, "size", size // 8)

    # implement Type interface so this can be used directly
    # FUTURE: see if this can be garbage collected or make weak `self` reference
    def encode(self, value: int, stream: BinaryIO, **_: Any):
        return Bitfields(fields={"": self}).encode({"": value}, stream, **_)

    def decode(self, stream: BinaryIO, **_: Any) -> int:
        return Bitfields(fields={"": self}).decode(stream, **_)[""]


@dataclass(frozen=True, slots=True)
class Bitfields:
    fields: dict[str, Bitfield]
    size: Literal[1, 2, 4, 8] | None = None
    _int_type: Int = field(init=False, repr=False, compare=False)
    _offsets: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:  # noqa: PLR0912, PLR0915
        if not self.size:
            # Minimal bit accounting: walk fields in order, tracking the
            # running bit position for auto-placed groups and the maximum
            # required bits from explicit offsets. Grouping rules are the
            # same as before (align applies to a contiguous run).
            fields = list(self.fields.values())
            n = len(fields)
            i = 0
            running_bits = 0
            max_bits = 0

            while i < n:
                bf = fields[i]
                if bf.offset:
                    # Preserve any previously-reserved bits (e.g. from a
                    # forced align group) while resuming auto-placement at
                    # the explicit offset end.
                    prev_running = running_bits
                    running_bits = bf.offset + bf.bits
                    max_bits = max(max_bits, prev_running, running_bits)
                    i += 1
                    continue

                if bf.align is not None:
                    # Only allow `align` on the first field of a contiguous
                    # auto-placement group.
                    if i > 0 and not fields[i - 1].offset and fields[i - 1].align is None:
                        raise ValueError(
                            "Bitfield align is only allowed on the first field of a group"
                        )

                    forced_bits = bf.align * 8
                    group_bits = bf.bits
                    j = i + 1
                    while j < n and not fields[j].offset and fields[j].align is None:
                        group_bits += fields[j].bits
                        j += 1
                    if group_bits > forced_bits:
                        raise ValueError("Bitfield exceeds forced align group size")
                    running_bits += forced_bits
                    i = j
                    continue

                # auto group
                group_bits = bf.bits
                j = i + 1
                while j < n and not fields[j].offset and fields[j].align is None:
                    group_bits += fields[j].bits
                    j += 1
                running_bits += group_bits
                i = j

            total_bits = max(max_bits, running_bits)
            # ensure size is power-of-two bytes
            size = 8
            while total_bits > size:
                size *= 2
            object.__setattr__(self, "size", size // 8)

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

    def encode(self, value: dict[str, int], stream: BinaryIO, **_: Any) -> None:
        int_val = 0
        for name, bitfield in self.fields.items():
            if name not in value:
                raise ValueError(f"Missing field {name!r}")
            val = value[name]
            if val < 0 or val > bitfield.mask:
                raise ValueError(f"Value {val} for field {name!r} out of range")
            int_val |= val << self._offsets[name]
        self._int_type.encode(int_val, stream, **_)

    def decode(self, stream: BinaryIO, **_: Any) -> dict[str, int]:
        int_val = self._int_type.decode(stream, **_)
        # if the bitfield is a single bit, return bool to support `bool` annotated fields
        # True/False behave as `int` but not other way around
        return {
            name: (
                (int_val >> self._offsets[name]) & bitfield.mask
                if bitfield.bits > 1
                # convert to bool with `==` for single-bit fields
                else (int_val >> self._offsets[name]) & 1 == 1
            )
            for name, bitfield in self.fields.items()
        }
