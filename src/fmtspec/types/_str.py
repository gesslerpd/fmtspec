from dataclasses import dataclass
from typing import Any, BinaryIO

from ..stream import read_exactly, write_all


@dataclass(frozen=True, slots=True)
class Str:
    """Text format backed by encoded bytes.

    Example:
        >>> from fmtspec import decode, encode, types
        >>> decode(encode("ok", types.Str(2, encoding="ascii")), types.Str(2, encoding="ascii"))
        'ok'
    """

    size: int | None = None
    encoding: str = "utf-8"

    def encode(self, stream: BinaryIO, value: str, **_: Any) -> None:
        data = value.encode(self.encoding)
        if self.size is not None and len(data) != self.size:
            raise ValueError(f"Expected {self.size} bytes, got {len(data)}")
        write_all(stream, data)

    def decode(self, stream: BinaryIO, **_: Any) -> str:
        if self.size is None:
            # read until EOS
            data = stream.read()
        else:
            data = read_exactly(stream, self.size)
        return data.decode(self.encoding)


str_ = str_utf8 = Str()
str_ascii = Str(encoding="ascii")
