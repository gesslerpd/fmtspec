from dataclasses import dataclass
from io import BytesIO
from types import EllipsisType
from typing import Any, BinaryIO, ClassVar

from .._protocol import Type
from .._stream import write_all


@dataclass(frozen=True, slots=True)
class TakeUntil:
    """Generic take-until format: either terminated by bytes or length-prefixed.

    Exactly one of `terminator` or `max_size` must be provided.
    Returns `str` by default (decoded with `encoding`) unless `as_bytes` is True.
    """

    # dynamic size
    size: ClassVar[EllipsisType] = ...
    fmt: Type
    terminator: bytes
    max_size: int | None = None

    def __post_init__(self) -> None:
        if not self.terminator:
            raise ValueError("terminator must not be empty")

    def encode(self, value: bytes, stream: BinaryIO, **_: Any) -> None:
        self.fmt.encode(value, stream, **_)
        write_all(stream, self.terminator)

    def decode(self, stream: BinaryIO, **_: Any) -> str | bytes:
        term = self.terminator
        term_len = len(term)
        max_size = float("inf") if self.max_size is None else self.max_size
        read = stream.read

        # search for terminator
        buffer = bytearray(read(term_len))
        append = buffer.append
        size = 0
        while True:
            if buffer[-term_len:] == term:
                return self.fmt.decode(BytesIO(buffer[:-term_len]), **_)

            chunk = read(1)
            if not chunk:
                raise EOFError("Unexpected end of stream while searching for terminator")
            # perf: avoid buffer.extend() for single byte
            append(chunk[0])
            size += 1

            if size > max_size:
                raise ValueError("Terminator not found within max_size limit")
