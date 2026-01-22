from dataclasses import dataclass, field
from typing import Any, BinaryIO, ClassVar


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

    def encode(self, value: Any, stream: BinaryIO, **_: Any) -> None:
        """Write the literal bytes to stream. Value is ignored."""
        if self.strict and value is not None and value != self.value:
            raise ValueError(f"Expected {self.value!r}, got {value!r}")
        stream.write(self.value)

    def decode(self, stream: BinaryIO, **_: Any) -> bytes:
        """Read and verify the literal bytes from stream."""
        data = stream.read(len(self.value))
        if self.strict and data != self.value:
            raise ValueError(f"Expected {self.value!r}, got {data!r}")
        return self.value


@dataclass(frozen=True, slots=True)
class Null:
    # class variables
    constant: ClassVar[bool] = True
    size: ClassVar[int] = 0

    def encode(self, value: Any, stream: BinaryIO, **_: Any) -> None:  # noqa: ARG002
        assert value is None

    def decode(self, stream: BinaryIO, **_: Any) -> None:
        pass
