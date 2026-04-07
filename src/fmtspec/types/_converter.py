from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..stream import decode_stream, encode_stream
from ._ref import Ref

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._protocol import Context, Format, Size


type ConverterFn = Callable[[Any], Any]


def scale(fmt: Format | Ref, factor: int) -> Converter:
    """Create a converter that scales values by a fixed integer factor.

    Decoding multiplies the inner value by ``factor``.
    Encoding performs the inverse operation.
    """
    if not isinstance(factor, int) or factor <= 0:
        raise ValueError("scale factor must be a positive integer")

    def _decode(raw: Any) -> Any:
        return raw * factor

    def _encode(obj: Any) -> Any:
        # FUTURE: add `strict` mode?
        # quotient, remainder = divmod(obj, factor)
        # if remainder:
        #     raise ValueError(f"Value {obj} is not divisible by scale factor {factor}")
        return obj // factor

    return Converter(fmt, decode_fn=_decode, encode_fn=_encode)


@dataclass(frozen=True, slots=True)
class Converter:
    """Adapt values encoded by an inner format.

    ``Converter`` wraps a single inner format and applies optional conversion
    functions around its encode and decode operations. This is useful when the
    wire representation is already handled by an existing fmtspec format but the
    public Python value should be a different shape.
    """

    fmt: Format | Ref
    decode_fn: ConverterFn | None = field(default=None, repr=False, compare=False)
    encode_fn: ConverterFn | None = field(default=None, repr=False, compare=False)
    size: Size = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "size",
            ... if isinstance(self.fmt, Ref) else getattr(self.fmt, "size", ...),
        )

    def _resolve_fmt(self, *, context: Context) -> Format:
        fmt = self.fmt
        if isinstance(fmt, Ref):
            fmt = fmt.resolve(context)
        return fmt

    def encode(self, stream, value: Any, *, context: Context) -> None:
        converted = self.encode_fn(value) if self.encode_fn is not None else value
        encode_stream(stream, converted, self._resolve_fmt(context=context), context=context)

    def decode(self, stream, *, context: Context) -> Any:
        value = decode_stream(stream, self._resolve_fmt(context=context), context=context)
        if self.decode_fn is not None:
            value = self.decode_fn(value)
        return value
