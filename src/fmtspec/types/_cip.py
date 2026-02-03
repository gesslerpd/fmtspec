"""CIP (Common Industrial Protocol) types for binary serialization.

This module provides fmtspec-compatible types for CIP path segments and EPATH
structures. All types conform to the fmtspec Type protocol with encode/decode
methods that accept stream and context parameters.

CIP segments encode routing paths through industrial control networks.
Each segment type has a 3-bit type code in the high bits of its first byte.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import IntEnum
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

import msgspec

from .._core import _decode_stream, _encode_stream
from ._array import array
from ._bitfield import Bitfield, Bitfields
from ._bytes import Bytes
from ._int import u8le, u16le, u32le, u64le
from ._sized import Sized

if TYPE_CHECKING:
    from types import EllipsisType


# Type aliases for CIP integer types (little-endian per CIP spec)
usint = u8le  # Unsigned 8-bit integer
uint = u16le  # Unsigned 16-bit integer
udint = u32le  # Unsigned 32-bit integer
ulint = u64le  # Unsigned 64-bit integer


class SegmentType(IntEnum):
    """CIP segment type codes (bits 5-7 of segment byte)."""

    port = 0b_000
    logical = 0b_001
    network = 0b_010
    symbolic = 0b_011
    data = 0b_100
    constructed_data_type = 0b_101
    elementary_data_type = 0b_110
    # reserved = 0b_111


SEGMENT_TYPE_MAP: dict[str, int] = {
    # default for a class that doesn't match any known segment type
    "CIPSegment": 0b111,
}


# ---------------------------------------------------------------------------
# Bitfield definitions for segment headers
# ---------------------------------------------------------------------------

# Port segment header byte:
# Bits 0-3: Port Identifier
# Bit 4: Extended Link Address flag
# Bits 5-7: Segment Type (0b000 for port)
_port_header = Bitfields(
    size=1,
    fields={
        "port": Bitfield(bits=4),
        "ext_link": Bitfield(bits=1),
        "segment_type": Bitfield(bits=3),
    },
)

# Logical segment header byte:
# Bits 0-1: Logical Format (8-bit, 16-bit, 32-bit)
# Bits 2-4: Logical Type
# Bits 5-7: Segment Type (0b001 for logical)
_logical_header = Bitfields(
    size=1,
    fields={
        "format": Bitfield(bits=2),
        "logical_type": Bitfield(bits=3),
        "segment_type": Bitfield(bits=3),
    },
)

# Network segment header byte:
# Bits 0-4: Network Segment Subtype
# Bits 5-7: Segment Type (0b010 for network)
_network_header = Bitfields(
    size=1,
    fields={
        "subtype": Bitfield(bits=5),
        "segment_type": Bitfield(bits=3),
    },
)

# Symbolic segment header byte:
# Bits 0-4: Symbol Size (0 = extended format)
# Bits 5-7: Segment Type (0b011 for symbolic)
_symbolic_header = Bitfields(
    size=1,
    fields={
        "symbol_size": Bitfield(bits=5),
        "segment_type": Bitfield(bits=3),
    },
)

_header = Bitfields(
    size=1,
    fields={
        "segment_type": Bitfield(bits=3, offset=5),
    },
)


def _min_uint_size(value: int) -> int:
    """Determine minimum byte size needed to encode an unsigned integer (1, 2, or 4)."""
    if value < 0:
        raise ValueError("Value must be non-negative")
    if value <= 0xFF:
        return 1
    if value <= 0xFFFF:
        return 2
    if value <= 0xFFFFFFFF:
        return 4
    raise ValueError(f"Value {value} too large for CIP encoding")


# ---------------------------------------------------------------------------
# CIPSegment base class (value type)
# ---------------------------------------------------------------------------


class CIPSegment(
    msgspec.Struct,
    tag_field="segment_type",
    tag=lambda qualname: SEGMENT_TYPE_MAP[qualname],
):
    """Base class for CIP path segment values.

    Segment types encode their type in the high 3 bits of the first byte:
    - 000: Port segment
    - 001: Logical segment
    - 010: Network segment
    - 011: Symbolic segment
    - 100: Data segment
    - 101: Constructed data type
    - 110: Elementary data type
    - 111: Reserved

    +----+----+----+----+----+----+----+----+
    | Segment Type | Segment Format         |
    +====+====+====+====+====+====+====+====+
    | 7  | 6  | 5  | 4  | 3  | 2  | 1  | 0  |
    +----+----+----+----+----+----+----+----+

    Uses msgspec tagged unions: when serialized with msgspec, a 'type' field
    is added to identify the segment type, enabling automatic reconstruction.
    """

    TYPE: ClassVar[SegmentType] = SegmentType.port
    TYPES: ClassVar[dict[int, type[CIPSegment]]] = {}
    HEADER_FMT: ClassVar[Bitfields] = _header

    # does not run for this base class
    def __init_subclass__(cls, *args) -> None:
        # register relevant subclass information
        SEGMENT_TYPE_MAP[cls.__name__] = int(cls.TYPE)
        cls.TYPES[cls.TYPE] = cls
        return super().__init_subclass__(*args)


class PortSegment(CIPSegment):
    """Port segment of a CIP path.

    +----+----+----+--------------------+----+----+----+----+
    | Segment Type | Extended Link Addr | Port Identifier   |
    +====+====+====+====================+====+====+====+====+
    |  7 |  6 | 5  |         4          |  3 |  2 |  1 |  0 |
    +----+----+----+--------------------+----+----+----+----+

    Attributes:
        port: Port identifier (backplane, enet, etc.) or port number.
        link_address: Link address as int, IP string, or raw bytes.
    """

    TYPE: ClassVar[SegmentType] = SegmentType.port
    HEADER_FMT: ClassVar[Bitfields] = _port_header

    port: int
    link_address: int | bytes
    ext_link: bool = False

    def _get_port_info(self) -> tuple[int, int]:
        """Get normalized port value and extended port.

        Returns:
            Tuple of (port_value, ex_port) where ex_port is 0 if not extended.
        """
        port_val: int
        if isinstance(self.port, str):
            if self.port.isdigit():
                port_val = int(self.port)
            else:
                raise NotImplementedError
        else:
            port_val = int(self.port)

        if port_val > 0x0F:
            return (0x0F, port_val)
        return (port_val, 0)

    def _get_link_bytes(self) -> bytes:
        """Get normalized link address as bytes."""
        if isinstance(self.link_address, str):
            if self.link_address.isnumeric():
                val = int(self.link_address)
                size = _min_uint_size(val)
                return val.to_bytes(size, byteorder="little")
            else:
                ip = ipaddress.ip_address(self.link_address)
                return str(ip).encode()
        elif isinstance(self.link_address, int):
            size = _min_uint_size(self.link_address)
            return self.link_address.to_bytes(size, byteorder="little")
        else:
            return self.link_address

    def encode(self, stream: BinaryIO, _padded: bool) -> None:
        """Encode port segment to stream."""
        port_value, ex_port = self._get_port_info()
        link_bytes = self._get_link_bytes()
        ex_link = len(link_bytes) > 1

        # Write header byte using bitfield
        _port_header.encode(
            {
                "port_id": port_value,
                "ex_link": ex_link,
                "segment_type": self.TYPE,
            },
            stream,
        )

        # Extended port (2 bytes) if port > 15
        if ex_port:
            uint.encode(ex_port, stream)

        # Link address
        if ex_link:
            usint.encode(len(link_bytes), stream)
            stream.write(link_bytes)
            # Pad to even length
            if len(link_bytes) % 2:
                stream.write(b"\x00")
        else:
            stream.write(link_bytes)

    @classmethod
    def decode(cls, stream: BinaryIO, _padded: bool) -> PortSegment:
        """Decode port segment from stream."""
        header = _port_header.decode(stream)

        if header["segment_type"] != cls.TYPE:
            raise TypeError(f"Segment type invalid for PortSegment: {header['segment_type']:03b}")

        ex_link = header["ex_link"]
        port = header["port_id"]

        # Extended port
        if port == 0x0F:
            port = uint.decode(stream)

        # Link address
        if ex_link:
            link_size = usint.decode(stream)
            if not link_size:
                raise ValueError("Extended link address size is 0")
            link = Bytes(link_size).decode(stream)
            # Consume pad byte if odd length
            if link_size % 2:
                stream.read(1)
        else:
            link = usint.decode(stream)

        return cls(port, link)


class LogicalSegmentType(IntEnum):
    type_class_id = 0b000
    type_instance_id = 0b001
    type_member_id = 0b010
    type_connection_point = 0b011
    type_attribute_id = 0b100
    type_special = 0b101
    type_service_id = 0b110
    type_reserved = 0b111


class LogicalFormat(IntEnum):
    format_8bit = 0b00
    format_16bit = 0b01
    format_32bit = 0b10
    format_reserved = 0b11


class LogicalSegment(CIPSegment):
    """Logical segment of a CIP path.

    +----+----+----+----+----+----+-------+--------+
    | Segment Type | Logical Type | Logical Format |
    +====+====+====+====+====+====+=======+========+
    |  7 |  6 |  5 | 4  |  3 |  2 |   1   |    0   |
    +----+----+----+----+----+----+-------+--------+

    Attributes:
        type: Logical segment type (class_id, instance_id, etc.).
        value: The logical value as an integer or raw bytes.
    """

    TYPE: ClassVar[SegmentType] = SegmentType.logical
    HEADER_FMT: ClassVar[Bitfields] = _logical_header

    type: LogicalSegmentType
    value: int | bytes

    def _get_value_info(self) -> tuple[bytes, LogicalFormat]:
        """Get normalized value bytes and format.

        Returns:
            Tuple of (value_bytes, format).

        Raises:
            ValueError: If value is invalid for the segment type.
        """
        # Normalize value to bytes
        if isinstance(self.value, int):
            size = _min_uint_size(self.value)
            value_bytes = self.value.to_bytes(size, byteorder="little")
        else:
            value_bytes = self.value

        val_len = len(value_bytes)

        # Determine format based on type and value size
        if self.type == LogicalSegmentType.type_service_id:
            if val_len != 1:
                raise ValueError(
                    f"Invalid logical value for Service ID type, expected 1 byte, got: {val_len}"
                )
            return (value_bytes, LogicalFormat.format_8bit)
        elif self.type == LogicalSegmentType.type_special:
            raise ValueError("Logical segments with Special type are not supported")
        elif val_len == 1:
            return (value_bytes, LogicalFormat.format_8bit)
        elif val_len == 2:
            return (value_bytes, LogicalFormat.format_16bit)
        elif val_len == 4:
            if self.type not in (
                LogicalSegmentType.type_instance_id,
                LogicalSegmentType.type_connection_point,
            ):
                raise ValueError(
                    "32-bit logical value only valid for Instance ID and Connection Point types"
                )
            return (value_bytes, LogicalFormat.format_32bit)
        else:
            raise ValueError("logical value too large")

    def encode(self, stream: BinaryIO, padded: bool) -> None:
        """Encode logical segment to stream."""
        value_bytes, fmt = self._get_value_info()

        _logical_header.encode(
            {
                "format": fmt,
                "logical_type": self.type,
                "segment_type": self.TYPE,
            },
            stream,
        )

        # Pad byte for 16/32 bit formats in padded mode
        if padded and fmt in (LogicalFormat.format_16bit, LogicalFormat.format_32bit):
            stream.write(b"\x00")

        stream.write(value_bytes)

    @classmethod
    def decode(cls, stream: BinaryIO, padded: bool) -> LogicalSegment:
        """Decode logical segment from stream."""
        header = _logical_header.decode(stream)

        if header["segment_type"] != cls.TYPE:
            raise TypeError(
                f"Segment type invalid for LogicalSegment: {header['segment_type']:03b}"
            )

        _type = header["logical_type"]
        _format = header["format"]

        if _type == LogicalSegmentType.type_reserved:
            raise ValueError("Unsupported logical type: Reserved")

        if _format == LogicalFormat.format_reserved:
            raise ValueError("Unsupported logical format: Reserved")
        elif _format == LogicalFormat.format_32bit and _type not in (
            LogicalSegmentType.type_instance_id,
            LogicalSegmentType.type_connection_point,
        ):
            raise ValueError(f"32-bit logical format on unsupported logical type: {_type:03b}")

        value: int | bytes
        if _type == LogicalSegmentType.type_special:
            if _format != LogicalFormat.format_8bit:
                raise ValueError(f"Unsupported logical format for Special type: {_format:02b}")
            value = Bytes(6).decode(stream)  # Electronic key
        elif _type == LogicalSegmentType.type_service_id:
            if _format != LogicalFormat.format_8bit:
                raise ValueError(f"Unsupported logical format for Service ID type: {_format:02b}")
            value = usint.decode(stream)
        elif _format == LogicalFormat.format_8bit:
            value = usint.decode(stream)
        else:
            if padded:
                stream.read(1)  # Consume pad byte
            if _format == LogicalFormat.format_16bit:
                value = uint.decode(stream)
            else:
                value = udint.decode(stream)

        return cls(LogicalSegmentType(_type), value)


class NetworkSegmentType(IntEnum):
    scheduled = 0b00001
    fixed_tag = 0b00010
    production_inhibit_time = 0b00011
    safety = 0b10000
    extended = 0b11111


# Network types with data array format (bit 4 set)
_NETWORK_DATA_ARRAY_MASK = 0b10000


class NetworkSegment(CIPSegment):
    """Network segment of a CIP path.

    Attributes:
        type: Network segment subtype.
        data: Segment data bytes.
    """

    TYPE: ClassVar[SegmentType] = SegmentType.network
    HEADER_FMT: ClassVar[Bitfields] = _network_header

    type: NetworkSegmentType
    data: bytes

    def __post_init__(self) -> None:
        NetworkSegmentType(self.type)  # validate type
        if not (self.type & _NETWORK_DATA_ARRAY_MASK) and len(self.data) != 1:
            raise ValueError(
                f"Network segment subtype {self.type:05b} requires exactly one byte of data"
            )

    def encode(self, stream: BinaryIO, _padded: bool) -> None:
        """Encode network segment to stream."""
        _network_header.encode(
            {"subtype": self.type, "segment_type": self.TYPE},
            stream,
        )

        if self.type & _NETWORK_DATA_ARRAY_MASK:
            data_len = len(self.data)
            if self.type == NetworkSegmentType.extended:
                data_len -= 2
            usint.encode(data_len, stream)
            stream.write(self.data)
        else:
            stream.write(self.data)

    @classmethod
    def decode(cls, stream: BinaryIO, _padded: bool) -> NetworkSegment:
        """Decode network segment from stream."""
        header = _network_header.decode(stream)

        if header["segment_type"] != cls.TYPE:
            raise TypeError(
                f"Segment type invalid for NetworkSegment: {header['segment_type']:03b}"
            )

        _type = header["subtype"]
        NetworkSegmentType(_type)  # validate type

        if _type & _NETWORK_DATA_ARRAY_MASK:
            data_len = usint.decode(stream)
            if _type == NetworkSegmentType.extended:
                data_len += 2
            data = Bytes(data_len).decode(stream)
        else:
            data = usint.decode(stream).to_bytes(1, byteorder="little")

        return cls(NetworkSegmentType(_type), data)


class SymbolicSegmentExtendedFormat(IntEnum):
    double_byte_chars = 0b001_00000
    triple_byte_chars = 0b010_00000

    _numeric_format = 0b110_00000
    _numeric_usint = 0b000_00110
    _numeric_uint = 0b000_00111
    _numeric_udint = 0b000_01000

    numeric_symbol_usint = _numeric_format | _numeric_usint
    numeric_symbol_uint = _numeric_format | _numeric_uint
    numeric_symbol_udint = _numeric_format | _numeric_udint


_SYMBOLIC_EX_FORMAT_MASK = 0b111_00000
_SYMBOLIC_EX_SIZE_MASK = 0b000_11111
MAX_SYMBOL_SIZE = 31


class SymbolicSegment(CIPSegment):
    """Symbolic segment of a CIP path.

    Attributes:
        symbol: Symbol as ASCII string, numeric value, or raw bytes.
        ex_type: Extended format type (required for bytes, auto-set otherwise).
    """

    TYPE: ClassVar[SegmentType] = SegmentType.symbolic
    HEADER_FMT: ClassVar[Bitfields] = _symbolic_header

    symbol: int | bytes
    ex_type: SymbolicSegmentExtendedFormat | int | None = None

    def _get_symbol_info(self) -> tuple[bytes, bool, int | None]:
        """Get normalized symbol bytes, extended flag, and ex_type.

        Returns:
            Tuple of (symbol_bytes, is_extended, ex_type).

        Raises:
            ValueError: If symbol configuration is invalid.
        """
        if isinstance(self.symbol, bytes):
            if self.ex_type is None:
                raise ValueError("symbol of type bytes requires 'ex_type' to be provided")
            _format = self.ex_type & _SYMBOLIC_EX_FORMAT_MASK
            ex_type_val = self.ex_type
            if _format == SymbolicSegmentExtendedFormat.double_byte_chars:
                if len(self.symbol) % 2:
                    raise ValueError(
                        "length of symbol with double-byte characters is not a multiple of 2"
                    )
                ex_type_val = (
                    SymbolicSegmentExtendedFormat.double_byte_chars | len(self.symbol) // 2
                )
            elif _format == SymbolicSegmentExtendedFormat.triple_byte_chars:
                if len(self.symbol) % 3:
                    raise ValueError(
                        "length of symbol with triple-byte characters is not a multiple of 3"
                    )
                ex_type_val = (
                    SymbolicSegmentExtendedFormat.triple_byte_chars | len(self.symbol) // 3
                )
            return (self.symbol, True, ex_type_val)

        elif isinstance(self.symbol, str):
            if len(self.symbol) > MAX_SYMBOL_SIZE:
                raise ValueError("symbol size too large, must be <= 31 characters")
            return (self.symbol.encode("ascii"), False, None)

        elif isinstance(self.symbol, int):
            # Numeric symbol - determine size
            size = _min_uint_size(self.symbol)
            if size == 1:
                ex_type_val = SymbolicSegmentExtendedFormat.numeric_symbol_usint
            elif size == 2:
                ex_type_val = SymbolicSegmentExtendedFormat.numeric_symbol_uint
            else:
                ex_type_val = SymbolicSegmentExtendedFormat.numeric_symbol_udint
                size = 4
            return (self.symbol.to_bytes(size, byteorder="little"), True, ex_type_val)

        raise TypeError(f"Unsupported symbol type: {type(self.symbol)}")

    def encode(self, stream: BinaryIO, _padded: bool) -> None:
        """Encode symbolic segment to stream."""
        symbol_bytes, is_extended, ex_type_val = self._get_symbol_info()

        if is_extended:
            if ex_type_val is None:
                raise ValueError("symbol ex_type must not be None for extended format")
            # Extended format: header with size=0, then ex_type byte
            _symbolic_header.encode(
                {"symbol_size": 0, "segment_type": self.TYPE},
                stream,
            )
            usint.encode(ex_type_val, stream)
            stream.write(symbol_bytes)
        else:
            # ASCII string - length encoded in segment byte
            _symbolic_header.encode(
                {"symbol_size": len(symbol_bytes), "segment_type": self.TYPE},
                stream,
            )
            stream.write(symbol_bytes)

    @classmethod
    def decode(cls, stream: BinaryIO, _padded: bool) -> SymbolicSegment:
        """Decode symbolic segment from stream."""
        header = _symbolic_header.decode(stream)

        if header["segment_type"] != cls.TYPE:
            raise TypeError(
                f"Segment type invalid for SymbolicSegment: {header['segment_type']:03b}"
            )

        symbol_size = header["symbol_size"]
        if not symbol_size:
            # Extended format
            ex_type = usint.decode(stream)
            size = ex_type & _SYMBOLIC_EX_SIZE_MASK
            _format = ex_type & _SYMBOLIC_EX_FORMAT_MASK
            symbol: str | int | bytes

            if _format == SymbolicSegmentExtendedFormat.double_byte_chars:
                symbol = Bytes(size * 2).decode(stream)
            elif _format == SymbolicSegmentExtendedFormat.triple_byte_chars:
                symbol = Bytes(size * 3).decode(stream)
            elif ex_type == SymbolicSegmentExtendedFormat.numeric_symbol_usint:
                symbol = usint.decode(stream)
            elif ex_type == SymbolicSegmentExtendedFormat.numeric_symbol_uint:
                symbol = uint.decode(stream)
            elif ex_type == SymbolicSegmentExtendedFormat.numeric_symbol_udint:
                symbol = udint.decode(stream)
            else:
                raise TypeError(f"unsupported extended string format type: {_format}")
            return cls(symbol, ex_type=ex_type)
        else:
            # ASCII string
            symbol = Bytes(symbol_size).decode(stream).decode("ascii")
            return cls(symbol)


# FUTURE: implement DataSegment?
# class DataSegmentType(IntEnum):
#     simple = 0b_00000
#     ansi_extended = 0b_10001


class ConstructedDataTypeSegment(CIPSegment):
    TYPE: ClassVar[SegmentType] = SegmentType.constructed_data_type


class ElementaryDataTypeSegment(CIPSegment):
    TYPE: ClassVar[SegmentType] = SegmentType.elementary_data_type


# ---------------------------------------------------------------------------
# CIPSegment base class (format type for segment dispatch)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CIPSegmentFmt:
    """Format type for CIP segments with automatic type dispatch.

    This format reads/writes CIP path segments, automatically dispatching
    to the appropriate segment type based on the segment type bits.

    Attributes:
        padded: Whether to use padded encoding (for PADDED_EPATH).
        size: Dynamic size (varies per segment).
    """

    padded: bool = False
    size: ClassVar[EllipsisType] = ...

    def encode(self, value: dict[str, Any], stream: BinaryIO, **_: Any) -> None:
        """Encode a CIP segment value to the stream.

        Handles both CIPSegment instances and dicts (from msgspec.to_builtins).
        Uses the 'kind' tag field for automatic type reconstruction.
        """
        segment_type = SegmentType(value["segment_type"])
        segment_cls = CIPSegment.TYPES[segment_type]

        _encode_stream(value, segment_cls.HEADER_FMT, stream, **_)
        # encode the rest of the segment
        raise NotImplementedError

    def decode(self, stream: BinaryIO, **_: Any) -> CIPSegment:
        """Decode a CIP segment from the stream, dispatching by type."""
        header_data = stream.read(1)
        segment_type = SegmentType(header_data[0] >> 5)
        segment_cls = CIPSegment.TYPES[segment_type]

        header = _decode_stream(BytesIO(header_data), segment_cls.HEADER_FMT, **_)[0]
        # decode the rest of the segment
        raise NotImplementedError


# Convenience instances
cip_segment = CIPSegmentFmt(padded=False)
cip_segment_padded = CIPSegmentFmt(padded=True)


# Convenience format instances
epath_packed = array(cip_segment)
epath_padded = array(cip_segment_padded)
# small sized
epath_padded_len = Sized(usint, epath_padded, factor=2)
# large sized
epath_padded_pad_len = Sized(uint, epath_padded, factor=2)
