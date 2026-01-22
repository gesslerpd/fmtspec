"""Array types for binary serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Literal

from .._stream import _decode_stream, _encode_stream
from .._utils import sizeof
from ._ref import Ref

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import EllipsisType

    from .._protocol import Context, Format, Size


@dataclass(frozen=True, slots=True)
class PrefixedArray:
    """Length-prefixed array type.

    The length prefix indicates the total byte size of all elements.
    Elements are decoded until the byte budget is exhausted.
    """

    # class variables
    size: ClassVar[EllipsisType] = ...

    # fields
    byteorder: Literal["little", "big"]
    prefix_size: Literal[1, 2, 4, 8]
    element_fmt: Format

    def encode(self, value: list[Any], stream: BinaryIO, *, context: Context) -> None:
        buffer = BytesIO()
        for elem in value:
            _encode_stream(elem, self.element_fmt, buffer, context=context)
        encoded_elements = buffer.getvalue()
        length = len(encoded_elements)
        prefix = length.to_bytes(self.prefix_size, self.byteorder, signed=False)
        stream.write(prefix + encoded_elements)

    def decode(self, stream: BinaryIO, *, context: Context) -> list[Any]:
        prefix = stream.read(self.prefix_size)
        length = int.from_bytes(prefix, self.byteorder, signed=False)
        element_data = stream.read(length)

        inner_stream = BytesIO(element_data)
        result = []
        while inner_stream.tell() < length:
            elem, _ = _decode_stream(inner_stream, self.element_fmt, context=context)
            result.append(elem)

        return result


# FUTURE: simple array helper, need a format `class Array: ...` later
@dataclass(frozen=True, slots=True)
class Array:
    """Fixed-shape array type.

    Encodes/decodes a multi-dimensional fixed-size array. The element format
    is applied to each element in row-major order.
    """

    element_fmt: Format
    # dims may be static ints or string keys looked up from the current
    # parent context (e.g., sibling field names). When any dimension is a
    # context key the overall array size is dynamic (`...`).
    dims: tuple[int | Ref, ...]

    # post-init public
    size: Size = field(init=False)

    # post-init private

    def __post_init__(self) -> None:
        dims = self.dims
        ddims = False
        sdims: list[int] = []
        if not dims:
            raise ValueError("Array dimensions must be non-empty.")

        # validate static integer dims; string dims are resolved at runtime
        for d in dims:
            if isinstance(d, int):
                if d <= 0:
                    raise ValueError("Array dimensions must be positive integers.")
                sdims.append(d)
            else:
                ddims = True

        # If element size or any dimension is dynamic, mark overall size
        # as dynamic (`...`). Only compute a concrete size when element
        # size is an int and all dims are ints.
        if ddims:
            size: Size = ...
        else:
            # try to compute fixed size if element_fmt exposes a concrete `size`
            elem_size = sizeof(self.element_fmt)
            if elem_size is None:
                raise ValueError("Element format must have a fixed size (non-greedy).")
            if elem_size is ...:
                size = ...
            else:
                size = elem_size
                for d in sdims:
                    size *= d

        object.__setattr__(self, "size", size)

    def _encode_level(self, stream, v: list[Any], idx: int, context: Context) -> None:
        dims = self.dims
        elem_fmt = self.element_fmt

        # resolve the expected length for this dimension from context when
        # a string key was provided
        dim_def = dims[idx]
        e_len = dim_def if isinstance(dim_def, int) else dim_def.resolve(context)

        if len(v) != e_len:
            dim_mismatch = f"Dimension mismatch: expected dims[{idx}]={e_len}, got {len(v)}."
            raise ValueError(dim_mismatch)

        if idx == len(dims) - 1:
            for elem in v:
                _encode_stream(elem, elem_fmt, stream, context=context)
        else:
            for sub in v:
                self._encode_level(stream, sub, idx + 1, context)

    def encode(self, value: list[Any], stream: BinaryIO, *, context: Context) -> None:
        self._encode_level(stream, value, 0, context=context)

    def _decode_level(self, stream, idx: int, context: Context) -> list[Any]:
        dims = self.dims
        elem_fmt = self.element_fmt

        dim_def = dims[idx]
        count = dim_def if isinstance(dim_def, int) else dim_def.resolve(context)

        if idx == len(dims) - 1:
            return [_decode_stream(stream, elem_fmt, context=context)[0] for _ in range(count)]
        else:
            return [self._decode_level(stream, idx + 1, context) for _ in range(count)]

    def decode(self, stream: BinaryIO, *, context: Context) -> list[Any]:
        return self._decode_level(stream, 0, context)


def array(fmt: Format, dims: int | Ref | Iterable[int | Ref]) -> Array:
    """Helper that returns an `Array` instance for the given element format
    and dimensions. Mirrors the old helper but produces an efficient `Array`.
    """
    if isinstance(dims, (int, Ref)):
        dims = (dims,)
    return Array(fmt, tuple(dims))
