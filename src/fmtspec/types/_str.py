from dataclasses import dataclass, field
from io import BytesIO
from struct import Struct
from typing import Any, BinaryIO, ClassVar

from ._int import Int


@dataclass(frozen=True, slots=True)
class TerminatedString:
    """String terminated by a specific byte sequence."""

    # class variables
    size: ClassVar[None] = None

    # fields
    terminator: bytes
    encoding: str = "utf-8"

    def encode(self, value: str, stream: BinaryIO, **_: Any) -> None:
        # perf: avoid temporary concatenation of bytes
        stream.write(value.encode(self.encoding))
        stream.write(self.terminator)

    def decode(self, stream: BinaryIO, **_: Any) -> str:
        term = self.terminator
        term_len = len(term)

        # perf: optimized path for BytesIO without per-byte reads
        if isinstance(stream, BytesIO):
            start = stream.tell()
            mv = stream.getbuffer()
            # search in the remaining buffer
            idx = mv[start:].tobytes().find(term)
            if idx == -1:
                raise ValueError(f"Terminator {term!r} not found in data")
            # read exactly the found slice (advances stream)
            stream.read(idx + term_len)
            return mv[start : start + idx].tobytes().decode(self.encoding)

        result = bytearray()
        while True:
            byte = stream.read(1)
            if not byte:
                raise ValueError(f"Terminator {term!r} not found in data")
            result.append(byte[0])
            if len(result) >= term_len and result[-term_len:] == term:
                return bytes(result[:-term_len]).decode(self.encoding)


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
