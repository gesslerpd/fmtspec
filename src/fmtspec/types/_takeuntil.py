from dataclasses import dataclass
from io import BytesIO
from types import EllipsisType
from typing import Any, BinaryIO, ClassVar

from .._protocol import Type
from ..stream import write_all


@dataclass(frozen=True, slots=True)
class TakeUntil:
    """Read or write values terminated by a sentinel byte sequence.

    The wrapped ``fmt`` is applied to the bytes before the terminator.

    Example:
        >>> from fmtspec import decode, encode, types
        >>> fmt = types.TakeUntil(types.str_utf8, b"\0")
        >>> decode(encode("ok", fmt), fmt)
        'ok'
    """

    # dynamic size
    size: ClassVar[EllipsisType] = ...
    fmt: Type
    terminator: bytes
    max_size: int | None = None

    def __post_init__(self) -> None:
        if not self.terminator:
            raise ValueError("terminator must not be empty")

    def encode(self, value: Any, stream: BinaryIO, **_: Any) -> None:
        self.fmt.encode(value, stream, **_)
        write_all(stream, self.terminator)

    def decode(self, stream: BinaryIO, **_: Any) -> Any:
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
