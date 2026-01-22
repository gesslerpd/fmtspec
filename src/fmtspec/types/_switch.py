"""Switch type for conditional format selection."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Literal

from .._stream import _decode_stream, _encode_stream

if TYPE_CHECKING:
    from .._protocol import Context, Format
    from ._ref import Ref


@dataclass(frozen=True, slots=True)
class Switch:
    """Conditional format selection based on a discriminator value.

    Encodes/decodes a length-prefixed body using a format selected from cases
    based on a discriminator value from a sibling field.

    The `key` parameter specifies which sibling field to use as the discriminator.
    During encoding/decoding, the context (parent dict) is used to look up the key.

    Example:
        extension_fmt = {
            "type": u2,
            "body": Switch(
                key="type",
                cases={0: sni_fmt, 16: alpn_fmt},
            ),
        }
    """

    size: ClassVar[None] = None

    key: Ref
    cases: dict[Any, Format]
    default: Format | None = None
    byteorder: Literal["little", "big"] = "big"
    prefix_size: Literal[1, 2, 4, 8] = 2

    def _get_format(self, key_value: Any) -> Format | None:
        return self.cases.get(key_value, self.default)

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        """Encode value using format selected by context[key]."""
        key_value = self.key.resolve(context)
        fmt = self._get_format(key_value)

        if fmt is None:
            length = len(value)
            prefix = length.to_bytes(self.prefix_size, self.byteorder, signed=False)
            stream.write(prefix + value)
        else:
            buffer = BytesIO()
            _encode_stream(value, fmt, buffer, context=context)
            encoded = buffer.getvalue()
            length = len(encoded)
            prefix = length.to_bytes(self.prefix_size, self.byteorder, signed=False)
            stream.write(prefix + encoded)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Decode data using format selected by context[key]."""
        prefix = stream.read(self.prefix_size)
        length = int.from_bytes(prefix, self.byteorder, signed=False)
        inner_data = stream.read(length)

        key_value = self.key.resolve(context)
        fmt = self._get_format(key_value)

        if fmt is None:
            return inner_data

        inner_stream = BytesIO(inner_data)
        return _decode_stream(inner_stream, fmt, context=context)[0]
