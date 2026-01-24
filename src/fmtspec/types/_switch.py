"""Switch type for conditional format selection and tag-based dispatch.

This merged `Switch` supports the original key-based dispatch (sibling field
selection) and an optional tag-based dispatch mode for formats that encode
their own tag in the stream. Tag-mode supports exact tag decoders and range
decoders and an optional encoding dispatch path.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Annotated, Any, BinaryIO, ClassVar, get_args, get_origin

from .._stream import _decode_stream, _encode_stream
from .._utils import _normalize_format, derive_fmt

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import EllipsisType

    from .._protocol import Context, Format
    from ._ref import Ref


@dataclass(frozen=True, slots=True)
class RangeDecoder:
    """Helper for decoding tag ranges where tag encodes partial data.

    Mirrors the previous `RangeDecoder` used by the tagged-union helper.
    """

    min_tag: int
    max_tag: int
    decoder: Callable[[BinaryIO, int, Context], Any]

    def matches(self, tag: int) -> bool:
        return self.min_tag <= tag <= self.max_tag


@dataclass(frozen=True, slots=True)
class Switch:
    """Conditional or tag-based format selection.

    Key-mode (existing behaviour): provide `key` and `cases` to select a
    `Format` based on a sibling field in the `context`.

    """

    size: ClassVar[EllipsisType] = ...

    key: Ref
    cases: dict[Any, Format]
    default: Format | None = None

    def _get_format(self, key_value: Any) -> Format | None:
        return self.cases.get(key_value, self.default)

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        key_value = self.key.resolve(context)
        fmt = self._get_format(key_value)
        if fmt is None:
            # Historically Switch wrote raw bytes when default is None
            stream.write(value)
        else:
            _encode_stream(value, fmt, stream, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Decode using either key-mode or tag-mode dispatch.

        Key-mode preserves existing semantics where the body is length-prefixed
        and decoded via the selected `Format` (or returned as raw bytes if
        `default` is None).
        """
        inner_data = stream.read()
        key_value = self.key.resolve(context)
        fmt = self._get_format(key_value)

        if fmt is None:
            return inner_data

        inner_stream = BytesIO(inner_data)
        return _decode_stream(inner_stream, fmt, context=context)[0]


@dataclass(frozen=True, slots=True)
class TaggedUnion:
    size: ClassVar[EllipsisType] = ...

    tag: Format | Ref
    fmt_map: dict[int | range, Any]
    # runtime mappings populated in __post_init__
    fmt_by_tag: dict[Any, Any] | None = None
    encoders_by_type: dict[type, tuple[Any, Any]] | None = None

    def __post_init__(self) -> None:
        fmt_map_norm: dict[Any, Any] = {}
        enc_by_type: dict[type, tuple[Any, Any]] = {}

        for tag_val, fmt_val in (self.fmt_map or {}).items():
            if isinstance(fmt_val, type):
                fmt_norm = derive_fmt(fmt_val)
                fmt_map_norm[tag_val] = fmt_norm
                enc_by_type[fmt_val] = (tag_val, fmt_norm)
                continue

            fmt_norm = _normalize_format(fmt_val)
            fmt_map_norm[tag_val] = fmt_norm

            origin = get_origin(fmt_val)
            if origin is Annotated:
                base = get_args(fmt_val)[0]
                if isinstance(base, type):
                    enc_by_type[base] = (tag_val, fmt_norm)

        # Always set the normalized map; store encoders only if any were found
        object.__setattr__(self, "fmt_by_tag", fmt_map_norm)
        object.__setattr__(self, "encoders_by_type", enc_by_type or None)

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        # Fast path: type-based dispatch
        if self.encoders_by_type:
            for t, mapping in self.encoders_by_type.items():
                if isinstance(value, t):
                    tag_val, fmt = mapping
                    _encode_stream(tag_val, self.tag, stream, context=context)
                    _encode_stream(value, fmt, stream, context=context)
                    return

        # Fallback: attempt each format until one succeeds
        for tag_val, fmt in (self.fmt_by_tag or {}).items():
            try:
                tmp = BytesIO()
                _encode_stream(value, fmt, tmp, context=context)
            except Exception:
                continue

            _encode_stream(tag_val, self.tag, stream, context=context)
            stream.write(tmp.getvalue())
            return

        raise ValueError("Unknown type")

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        tag = _decode_stream(stream, self.tag, context=context)[0]

        fmt = (self.fmt_by_tag or {}).get(tag)
        if fmt is None:
            raise ValueError(f"Unknown tag: 0x{int(tag):02x}")

        inner = stream.read()
        return _decode_stream(BytesIO(inner), fmt, context=context)[0]
