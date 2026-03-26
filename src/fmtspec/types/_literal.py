from dataclasses import dataclass, field
from typing import Any, BinaryIO, ClassVar

from ..stream import read_exactly, write_all


@dataclass(frozen=True, slots=True)
class Literal:
    """Constant byte sequence type.

    Encodes nothing (the value is fixed) and decodes by verifying
    the expected bytes are present in the stream.

    Useful for magic numbers, protocol markers, and fixed headers.

    Example:
        fmt = {
            "magic": Literal(b"PNG"),
            "version": u2,
        }
    """

    # class variables
    constant: ClassVar[bool] = True

    # fields
    value: bytes
    strict: bool = field(kw_only=True, default=True)

    @property
    def size(self) -> int:
        """The byte size of the literal value."""
        return len(self.value)

    def encode(self, stream: BinaryIO, value: Any, **_: Any) -> None:
        """Write the literal bytes to stream. Value is ignored."""
        if self.strict and value is not None and value != self.value:
            raise ValueError(f"Expected {self.value!r}, got {value!r}")
        write_all(stream, self.value)

    def decode(self, stream: BinaryIO, **_: Any) -> bytes:
        """Read and verify the literal bytes from stream."""
        data = read_exactly(stream, len(self.value))
        if self.strict and data != self.value:
            raise ValueError(f"Expected {self.value!r}, got {bytes(data)!r}")
        return self.value


@dataclass(frozen=True, slots=True)
class Null:
    """Zero-width format that only accepts and returns ``None``."""

    # class variables
    constant: ClassVar[bool] = True
    size: ClassVar[int] = 0

    def encode(self, stream: BinaryIO, value: Any, **_: Any) -> None:  # noqa: ARG002
        assert value is None

    def decode(self, stream: BinaryIO, **_: Any) -> None:  # noqa: ARG002
        return None


null = Null()
