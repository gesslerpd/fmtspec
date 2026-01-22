"""Array types for binary serialization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

from .._stream import _decode_stream, _encode_stream
from .._utils import sizeof
from ._ref import Ref

if TYPE_CHECKING:
    from .._protocol import Context, Format, Size, Type


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
    dims: tuple[int | Ref | Type, ...]

    # post-init public
    size: Size = field(init=False)

    # post-init private

    def __post_init__(self) -> None:
        dims = self.dims
        ddims = False
        # empty-tuple dimension `()` means greedy: repeat until end of stream
        greedy = not dims
        sdims: list[int] = []

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
        if greedy:
            size: Size = None
        elif ddims:
            size = ...
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
        if isinstance(dim_def, int):
            e_len = dim_def
        elif isinstance(dim_def, Ref):
            e_len = dim_def.resolve(context)
        else:
            e_len = None
            dim_def.encode(len(v), stream, context=context)

        if e_len is not None and len(v) != e_len:
            dim_mismatch = f"Dimension mismatch: expected dims[{idx}]={e_len}, got {len(v)}."
            raise ValueError(dim_mismatch)

        if idx == len(dims) - 1:
            for elem in v:
                _encode_stream(elem, elem_fmt, stream, context=context)
        else:
            for sub in v:
                self._encode_level(stream, sub, idx + 1, context)

    def encode(self, value: list[Any], stream: BinaryIO, *, context: Context) -> None:
        # Support greedy (no-dims) arrays: stream elements until exhaustion
        if not self.dims:
            for elem in value:
                _encode_stream(elem, self.element_fmt, stream, context=context)
            return

        self._encode_level(stream, value, 0, context=context)

    def _decode_level(self, stream, idx: int, context: Context) -> list[Any]:
        dims = self.dims
        elem_fmt = self.element_fmt

        dim_def = dims[idx]
        if isinstance(dim_def, int):
            count = dim_def
        elif isinstance(dim_def, Ref):
            count = dim_def.resolve(context)
        else:
            count = dim_def.decode(stream, context=context)

        if idx == len(dims) - 1:
            return [_decode_stream(stream, elem_fmt, context=context)[0] for _ in range(count)]
        else:
            return [self._decode_level(stream, idx + 1, context) for _ in range(count)]

    def decode(self, stream: BinaryIO, *, context: Context) -> list[Any]:
        # Support greedy (no-dims) arrays: read elements until exhaustion
        if not self.dims:
            return self._decode_greedy(stream, self.element_fmt, context)

        return self._decode_level(stream, 0, context)

    def _decode_greedy(self, stream: BinaryIO, elem_fmt: Any, context: Context) -> list[Any]:
        elem_size = sizeof(elem_fmt)

        if hasattr(stream, "getbuffer"):
            remaining = len(stream.getbuffer()) - stream.tell()
        else:
            cur = stream.tell()
            end = stream.seek(0, 2)
            stream.seek(cur)
            remaining = end - cur

        # If element has fixed size and remaining bytes known, compute count
        if isinstance(elem_size, int):
            count = remaining // elem_size
            return [_decode_stream(stream, elem_fmt, context=context)[0] for _ in range(count)]

        # Otherwise, decode in a loop until decoding fails (stream exhausted)
        items: list[Any] = []
        while True:
            try:
                v, _ = _decode_stream(stream, elem_fmt, context=context)
                items.append(v)
            except Exception:
                break
        return items


def array(fmt: Format, dims: int | Ref | Type | Iterable[int | Ref | Type] = ()) -> Array:
    """Helper that returns an `Array` instance for the given element format
    and dimensions. Mirrors the old helper but produces an efficient `Array`.
    """
    if not isinstance(dims, Iterable):
        dims = (dims,)
    return Array(fmt, tuple(dims))
