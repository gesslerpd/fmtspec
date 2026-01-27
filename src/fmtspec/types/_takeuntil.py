from dataclasses import dataclass
from io import BytesIO
from types import EllipsisType
from typing import Any, BinaryIO, ClassVar

from .._protocol import Type


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

    def encode(self, value: bytes, stream: BinaryIO, **_: Any) -> None:
        # terminator mode
        self.fmt.encode(value, stream, **_)
        stream.write(self.terminator)

    def decode(self, stream: BinaryIO, **_: Any) -> str | bytes:
        # terminator mode
        term = self.terminator  # type: ignore[assignment]
        term_len = len(term)

        # search for terminator
        buffer = bytearray()
        while True:
            chunk = stream.read(1)
            if not chunk:
                raise EOFError("Unexpected end of stream while searching for terminator")
            buffer.extend(chunk)

            if len(buffer) >= term_len:
                with memoryview(buffer) as view:
                    if view[-term_len:] == term:
                        # found terminator
                        return self.fmt.decode(BytesIO(view[:-term_len]), **_)

            if self.max_size is not None and len(buffer) > self.max_size:
                raise ValueError("Terminator not found within max_size limit")
