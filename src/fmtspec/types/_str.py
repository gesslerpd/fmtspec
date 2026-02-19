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
        stream.write_all(data)

    def decode(self, stream: BinaryIO, **_: Any) -> str:
        if self.size is None:
            # read until EOS
            data = stream.read()
        else:
            data = stream.read_exactly(self.size)
        return data.decode(self.encoding)


str_ = str_utf8 = Str()
str_ascii = Str(encoding="ascii")
