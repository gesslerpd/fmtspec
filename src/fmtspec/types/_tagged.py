"""Tagged union type for tag-based polymorphic formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._protocol import Context


@dataclass(frozen=True, slots=True)
class TaggedUnion:
    """Tag-based polymorphic type dispatcher.

    Reads a tag value from the stream and dispatches to the appropriate
    format based on registered handlers. Useful for self-describing formats
    like MessagePack, CBOR, BSON, etc.

    The encoder selects the appropriate tag and format based on the Python
    type of the value being encoded.

    Example:
        msgpack_value = TaggedUnion(
            decode_tag=lambda stream: stream.read(1)[0],
            decoders={
                0xc0: lambda s, ctx: None,  # nil
                0xc2: lambda s, ctx: False,  # false
                0xc3: lambda s, ctx: True,   # true
            },
            encode_dispatch=lambda v: (tag, fmt) based on type(v),
        )
    """

    size: ClassVar[None] = None

    # Decoding: tag reader and tag-to-decoder mapping
    decode_tag: Callable[[BinaryIO], int]
    decoders: dict[int, Callable[[BinaryIO, int, Context], Any]]

    # Encoding: dispatches Python value to (tag_writer, encoder) pair
    encode_dispatch: Callable[[Any, BinaryIO, Context], None]

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        """Encode value by dispatching to appropriate encoder."""
        self.encode_dispatch(value, stream, context)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Decode by reading tag and dispatching to appropriate decoder."""
        tag = self.decode_tag(stream)
        decoder = self.decoders.get(tag)
        if decoder is None:
            raise ValueError(f"Unknown tag: 0x{tag:02x}")
        return decoder(stream, tag, context)


@dataclass(frozen=True, slots=True)
class RangeDecoder:
    """Helper for decoding tag ranges where tag encodes partial data.

    For formats where a range of tags encode the same type but with
    data embedded in the tag itself (e.g., msgpack fixint, fixstr).
    """

    min_tag: int
    max_tag: int
    decoder: Callable[[BinaryIO, int, Context], Any]

    def matches(self, tag: int) -> bool:
        return self.min_tag <= tag <= self.max_tag
