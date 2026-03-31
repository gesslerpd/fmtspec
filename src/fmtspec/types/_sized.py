"""Sized type for context-driven dynamic sizing (simplified)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import KW_ONLY, dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO

from ..stream import decode_stream, encode_stream, read_exactly, write_all
from ._ref import Ref

if TYPE_CHECKING:
    from types import EllipsisType

    from .._protocol import Context, Format, Type


@dataclass(frozen=True, slots=True)
class Sized:
    """Wrap an inner format whose byte length is determined at runtime.

    `length` may be:
    - an `int`: fixed-size (pad to that size with `fill`)
    - a `Ref`: read sibling value from `context` (no length header written)
    - a format/type: encode/decode the length using that format

    `factor` multiplies the decoded length to get byte count (e.g., factor=2 for word count).

    Example:
        >>> from fmtspec import decode, encode, types
        >>> fmt = types.Sized(length=types.u8, fmt=types.Bytes())
        >>> decode(encode(b"abc", fmt), fmt)
        b'abc'
    """

    length: int | Type | Ref
    fmt: Format
    _: KW_ONLY
    align: int | None = None
    fill: bytes = b"\x00"
    # FUTURE: allow factor to be 2 callables for encode/decode?
    factor: int = 1
    inline: bool = False
    size: int | EllipsisType = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.length, int) and self.align:
            raise ValueError("align is not allowed with fixed int length")
        if self.inline and not isinstance(self.fmt, Mapping):
            raise ValueError("inline=True requires fmt to be a Mapping")

        object.__setattr__(self, "size", self.length if isinstance(self.length, int) else ...)

    def _pad_len(self, length: int) -> int:
        if not self.align:
            return 0
        return (self.align - (length % self.align)) % self.align

    def _check_padding(self, padding: bytes, pad_len: int) -> None:
        if len(padding) != pad_len:
            raise ValueError("Invalid or missing padding bytes after sized field")
        if not self.fill:
            if padding:
                raise ValueError("Unexpected padding bytes present")
            return
        unit = len(self.fill)
        if pad_len % unit != 0 or padding != self.fill * (pad_len // unit):
            raise ValueError("Invalid or missing padding bytes after sized field")

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        buf = BytesIO()
        encode_stream(buf, value, self.fmt, context=context)
        encoded = buf.getvalue()
        n = len(encoded)

        if isinstance(self.length, Ref):
            expected = self.length.resolve(context)
            if n != expected:
                raise ValueError(
                    f"Encoded length {n} does not match expected length {expected} from key {self.length!r}"
                )
            write_all(stream, encoded)
            pad = self._pad_len(n)
            if pad:
                write_all(stream, self.fill * pad)
            return

        if isinstance(self.length, int):
            fixed = self.length
            if n > fixed:
                raise ValueError(f"Encoded length {n} exceeds fixed size {fixed}")
            write_all(stream, encoded)
            pad = fixed - n
            if pad:
                write_all(stream, self.fill * pad)
            return

        # length is a format/type: write length first, then data
        if n % self.factor != 0:
            raise ValueError(f"Encoded length {n} is not divisible by factor {self.factor}")
        length_value = n // self.factor
        start = stream.tell()
        self.length.encode(stream, length_value, context=context)
        context.inspect_leaf(
            stream,
            "--size--",
            self.length,
            length_value,
            start,
            prepend=True,
        )
        write_all(stream, encoded)
        pad = self._pad_len(n)
        if pad:
            write_all(stream, self.fill * pad)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        if isinstance(self.length, Ref):
            length = self.length.resolve(context)
            data = read_exactly(stream, length)
            pad_len = self._pad_len(length)
            if pad_len:
                padding = read_exactly(stream, pad_len)
                self._check_padding(padding, pad_len)
            return decode_stream(BytesIO(data), self.fmt, context=context)

        if isinstance(self.length, int):
            length = self.length
            data = read_exactly(stream, length)
            inner_stream = BytesIO(data)
            inner = decode_stream(inner_stream, self.fmt, context=context)
            remaining = inner_stream.read()
            if remaining:
                self._check_padding(remaining, len(remaining))
            return inner

        # length is a format: decode it from stream, then read that many bytes
        start = stream.tell()
        length_value = self.length.decode(stream, context=context)
        context.inspect_leaf(stream, "--size--", self.length, length_value, start)
        length = length_value * self.factor
        data = read_exactly(stream, length)
        pad_len = self._pad_len(length)
        if pad_len:
            padding = read_exactly(stream, pad_len)
            self._check_padding(padding, pad_len)
        return decode_stream(BytesIO(data), self.fmt, context=context)
