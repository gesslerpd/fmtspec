"""Array types for binary serialization."""

from __future__ import annotations

import sys
from array import array as _parray
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

from .._stream import _decode_stream, _encode_stream
from .._utils import sizeof
from ._float import Float
from ._int import Int
from ._ref import Ref

# Module-level mappings for array typecodes (used by fast-path logic)
TYPECODE_MAP_INT: dict[tuple[int, bool], str] = {
    (1, False): "B",
    (1, True): "b",
    (2, False): "H",
    (2, True): "h",
    (4, False): "I",
    (4, True): "i",
    (8, False): "Q",
    (8, True): "q",
}

FLOAT_TYPECODE_MAP: dict[int, str] = {4: "f", 8: "d"}

if TYPE_CHECKING:
    from .._protocol import Context, Format, Size, Type


def flatten(nd_list: Iterable[Any]) -> Iterable[Any]:
    for item in nd_list:
        # flatten nested lists and tuples
        if isinstance(item, (list, tuple)):
            yield from flatten(item)
        else:
            yield item


def _unflatten_build(it: Iterator[Any], dims: tuple[int], level: int) -> list[Any]:
    count = dims[level]
    if count <= 0:
        raise ValueError("Array dimensions must be positive integers.")
    if level == len(dims) - 1:
        out: list[Any] = []
        for _ in range(count):
            try:
                out.append(next(it))
            except StopIteration:
                raise ValueError("Not enough elements to unflatten")
        return out
    return [_unflatten_build(it, dims, level + 1) for _ in range(count)]


def unflatten(flat_list: Iterable[Any], dims: tuple[int]) -> list[Any]:
    if not dims:
        raise ValueError("dims must be non-empty")
    return _unflatten_build(iter(flat_list), dims, 0)


def _resolve_dims_product(
    dims: tuple[int | Type | Ref, ...], context: Context | None = None
) -> int | None:
    """Resolve a product of `dims` where each dim is an int or a `Ref`.

    If `context` is provided, `Ref`s will be resolved using it. If
    `context` is None, `Ref`s cannot be resolved and the function
    returns ``None`` when encountering a `Ref`.

    Returns the product as int when all dims are ints or `Ref`s that
    successfully resolve; returns ``None`` if any dim is a `Type`-like
    prefix or if resolving a `Ref` fails or cannot be done.
    """
    prod: int = 1
    for d in dims:
        if isinstance(d, int):
            prod *= d
        elif isinstance(d, Ref):
            if context is None:
                return None
            try:
                prod *= d.resolve(context)
            except Exception:
                return None
        else:
            return None
    return prod


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
    dims: tuple[int | Type | Ref, ...]

    # post-init public
    size: Size = field(init=False, repr=False, compare=False)

    # cached fast-path info
    _fast_typecode: str | None = field(init=False, repr=False, compare=False)
    _fast_expected_count: int | None = field(init=False, repr=False, compare=False)
    _fast_byteorder_mismatch: bool = field(init=False, repr=False, compare=False)
    _fast_elem_size: int | None = field(init=False, repr=False, compare=False)

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

        # Precompute fast-path attributes for Int element formats when
        # applicable: greedy arrays or single-dimension arrays where the
        # dimension is a static int or a Ref. Skip fast-path when the
        # dimension is a `Type` (prefix), which must encode/decode the
        # length value itself.
        fast_typecode: str | None = None
        fast_expected: int | None = None
        fast_bomismatch = False
        fast_elem_size: int | None = None

        # TODO: quickly flatten all multi-dimensional arrays encode regardless of element type?
        # and then also unflatten on decode? May increase the performance for all element types.

        # Fast-path for single-dimension or greedy arrays of simple C types
        if isinstance(self.element_fmt, (Int, Float)):
            elem = self.element_fmt
            fast_elem_size = elem.size

            # integer typecodes depend on signedness
            if isinstance(elem, Int):
                fast_typecode = TYPECODE_MAP_INT.get((fast_elem_size, elem.signed))
            else:
                # Float: map sizes to array typecodes
                fast_typecode = FLOAT_TYPECODE_MAP.get(fast_elem_size)
            # Only enable the stdlib-array fast-path when all dims are
            # either static ints or `Ref`s (no `Type`/prefix dims). Compute
            # a concrete expected flattened count when all dims are ints.
            if fast_typecode is not None and self.dims:
                # disable fast-path if any dim is a non-int/non-Ref (i.e., a Type)
                if any(not (isinstance(d, int) or isinstance(d, Ref)) for d in self.dims):
                    fast_typecode = None
                else:
                    # compute static expected product if all dims are ints
                    fast_expected = _resolve_dims_product(self.dims, None)

            fast_bomismatch = elem.byteorder != sys.byteorder

        object.__setattr__(self, "_fast_typecode", fast_typecode)
        object.__setattr__(self, "_fast_expected_count", fast_expected)
        object.__setattr__(self, "_fast_byteorder_mismatch", fast_bomismatch)
        object.__setattr__(self, "_fast_elem_size", fast_elem_size)

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
        # Fast-path using precomputed values for 1-D/greedy Int element arrays
        if getattr(self, "_fast_typecode", None) is not None:
            typecode = self._fast_typecode
            expected = self._fast_expected_count
            # Resolve runtime expected count if dims contain `Ref`s.
            if expected is None and self.dims:
                expected = _resolve_dims_product(self.dims, context)

            # For multi-dimensional arrays, flatten before writing.
            # For greedy arrays (no dims) `expected` will be None.
            data_vals = [int(v) for v in flatten(value)]
            if expected is None or len(data_vals) == expected:
                arr = _parray(typecode, data_vals)
                if self._fast_byteorder_mismatch and (self._fast_elem_size or 0) > 1:
                    arr.byteswap()
                arr.tofile(stream)
                return

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
        # Fast-path using precomputed values for 1-D/greedy Int element arrays
        if getattr(self, "_fast_typecode", None) is not None:
            typecode = self._fast_typecode
            count = self._fast_expected_count
            # resolve Ref-based count at runtime if necessary
            if count is None and self.dims:
                count = _resolve_dims_product(self.dims, context)
            # for greedy or unknown count, compute remaining bytes
            if count is None:
                if hasattr(stream, "getbuffer"):
                    remaining = len(stream.getbuffer()) - stream.tell()
                else:
                    cur = stream.tell()
                    end = stream.seek(0, 2)
                    stream.seek(cur)
                    remaining = end - cur
                count = remaining // (self._fast_elem_size or 1)

            arr = _parray(typecode)
            arr.fromfile(stream, count)
            # arr.frombytes(data)
            if self._fast_byteorder_mismatch and (self._fast_elem_size or 0) > 1:
                arr.byteswap()
            lst = arr.tolist()
            # If this is a multi-dimensional fixed-shape array, rebuild
            # the nested structure from the flattened list.
            if self.dims and len(self.dims) > 1:
                # build resolved dims tuple of ints
                resolved_dims: list[int] = []
                for d in self.dims:
                    if isinstance(d, int):
                        resolved_dims.append(d)
                    else:
                        resolved_dims.append(d.resolve(context))
                return unflatten(lst, tuple(resolved_dims))
            return lst

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


def array(fmt: Format, dims: int | Type | Ref | Iterable[int | Type | Ref] = ()) -> Array:
    """Helper that returns an `Array` instance for the given element format
    and dimensions. Mirrors the old helper but produces an efficient `Array`.
    """
    if not isinstance(dims, Iterable):
        dims = (dims,)
    return Array(fmt, tuple(dims))
