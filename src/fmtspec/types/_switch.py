"""Switch type for conditional format selection and tag-based dispatch.

This merged `Switch` supports the original key-based dispatch (sibling field
selection) and an optional tag-based dispatch mode for formats that encode
their own tag in the stream. Tag-mode supports exact tag decoders and range
decoders and an optional encoding dispatch path.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

from .._stream import _decode_stream, _encode_stream

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

    Tag-mode (new): provide `decode_tag` and `decoders`/`range_decoders` to
    parse a tag from the stream and dispatch to an appropriate decoder.
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

    default: Format | Callable[[BinaryIO, Any, Context], Any] | None = None
    # Tag-mode (new): optional tag reader and decoders
    decode_tag: Callable[[BinaryIO], Any] | None = None
    decoders: dict[Any, Callable[[BinaryIO, Any, Context], Any]] | None = None
    range_decoders: list[RangeDecoder] | None = None

    # Encoding helpers for tag-mode
    encode_dispatch: Callable[[Any, BinaryIO, Context], None] | None = None
    encoders_by_type: dict[type, tuple[Any, Format | Callable]] | None = None
    tag_writer: Callable[[Any, BinaryIO, Context], None] | None = None
    tag_unknown_raises: bool = True

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        # Tag-mode encoding
        if self.encode_dispatch is not None:
            self.encode_dispatch(value, stream, context)
            return

        if self.encoders_by_type:
            enc = self.encoders_by_type.get(type(value))
            if not enc:
                raise ValueError("no encoder registered for value type")
            tag, fmt_or_callable = enc

            # Write tag
            if self.tag_writer is not None:
                self.tag_writer(tag, stream, context)
            # Best-effort simple tag writing for small integer tags or bytes
            # elif isinstance(tag, int) and 0 <= tag <= 0xFF:
            #     stream.write(bytes((tag,)))
            elif isinstance(tag, (bytes, bytearray)):
                stream.write(tag)
            else:
                raise ValueError("tag_writer required for non-byte/int tags")

            # Write payload
            if hasattr(fmt_or_callable, "__call__") and not hasattr(fmt_or_callable, "decode"):
                # callable encoder
                fmt_or_callable(value, stream, context)
            else:
                # Assume it's a Format
                _encode_stream(value, fmt_or_callable, stream, context=context)
            return

        raise ValueError("no encoding strategy available for Switch in tag-mode")

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:  # noqa: PLR0911
        # Tag-mode decoding
        if self.decode_tag is None:
            # No discriminator provided; nothing to do
            return stream.read()

        tag = self.decode_tag(stream)

        # Exact-match decoders first
        if self.decoders:
            dec = self.decoders.get(tag)
            if dec is not None:
                return dec(stream, tag, context)

        # Range decoders next
        if self.range_decoders:
            for rd in self.range_decoders:
                if rd.matches(tag):
                    return rd.decoder(stream, tag, context)

        # Default behavior
        if callable(self.default):
            # default expected to be like a decoder(stream, tag, context)
            return self.default(stream, tag, context)

        if self.default is not None:
            # treat default as a Format and decode remaining payload with it
            inner_data = stream.read()
            inner_stream = BytesIO(inner_data)
            return _decode_stream(inner_stream, self.default, context=context)[0]

        if self.tag_unknown_raises:
            raise ValueError(f"Unknown tag: 0x{int(tag):02x}")

        # Fall back to returning raw payload bytes (Switch-like behaviour)
        return stream.read()
