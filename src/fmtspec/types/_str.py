from dataclasses import dataclass
from typing import Any, BinaryIO


@dataclass(frozen=True, slots=True)
class Str:
    size: int | None = None
    encoding: str = "utf-8"

    def encode(self, value: str, stream: BinaryIO, **_: Any) -> None:
        data = value.encode(self.encoding)
        if self.size is not None and len(data) != self.size:
            raise ValueError(f"Expected {self.size} bytes, got {len(data)}")
        stream.write(data)

    def decode(self, stream: BinaryIO, **_: Any) -> str:
        # read fixed size or until EOS
        return stream.read(-1 if self.size is None else self.size).decode(self.encoding)


str_ = str_utf8 = Str()
str_ascii = Str(encoding="ascii")
