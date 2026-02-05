"""CIP (Common Industrial Protocol) types for binary serialization.

This module provides fmtspec-compatible types for CIP path segments and EPATH
structures. All types conform to the fmtspec Type protocol with encode/decode
methods that accept stream and context parameters.

CIP segments encode routing paths through industrial control networks.
Each segment type has a 3-bit type code in the high bits of its first byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Self

import msgspec

from ._array import array
from ._bitfield import Bitfield, Bitfields
from ._int import Int, u8le, u16le, u32le, u64le
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

# CIP encoding constraints
_MAX_CIP_UINT_SIZE = 4  # Maximum byte size for CIP unsigned integers (1, 2, or 4)
_BITS_PER_BYTE = 8


def _min_uint_size(value: int) -> int:
    size = 1
    while value >= (1 << (size * _BITS_PER_BYTE)):
        size *= 2

    if size > _MAX_CIP_UINT_SIZE:
        raise ValueError(
            f"Value too large for CIP encoding (requires {size} bytes, max {_MAX_CIP_UINT_SIZE})"
        )
    return size


# assert _min_uint_size(0xFF) == _min_uint_size(0x00) == 1
# assert _min_uint_size(0xFFFF) == _min_uint_size(0x100) == 2
# assert _min_uint_size(0xFFFFFFFF) == _min_uint_size(0x10000) == 4


def _value_to_bytes(value: int | bytes) -> bytes:
    if isinstance(value, int):
        size = _min_uint_size(value)
        return value.to_bytes(size, byteorder="little")
    return value


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

    # does not run for this base class
    def __init_subclass__(cls, *args) -> None:
        # register relevant subclass information
        SEGMENT_TYPE_MAP[cls.__name__] = int(cls.TYPE)
        cls.TYPES[cls.TYPE] = cls
        return super().__init_subclass__(*args)

    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, _padded: bool) -> None:
        raise NotImplementedError

    @classmethod
    def decode(cls, stream: BinaryIO, header_value: int, _padded: bool) -> Self:
        raise NotImplementedError


EXTENDED_PORT = 0x0F


class PortSegment(CIPSegment):
    """Port segment of a CIP path.

    +----+----+----+--------------------+----+----+----+----+
    | Segment Type | Extended Link Addr | Port Identifier   |
    +====+====+====+====================+====+====+====+====+
    |  7 |  6 | 5  |         4          |  3 |  2 |  1 |  0 |
    +----+----+----+--------------------+----+----+----+----+

    Attributes:
        port: Port identifier (backplane, enet, etc.) or port number.
        link_address: Link address as int or raw bytes.
    """

    TYPE: ClassVar[SegmentType] = SegmentType.port

    port: int
    link_address: int | bytes
    ext_link: bool = False

    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, _padded: bool) -> None:
        """Encode port segment to stream."""
        # Determine port encoding
        port_value = value["port"]
        link_addr = value["link_address"]

        # Get link address bytes
        link_bytes = _value_to_bytes(link_addr)
        ext_link = len(link_bytes) > 1

        # Write header byte
        _port_header.encode(
            {
                "port": port_value,
                "ext_link": ext_link,
                "segment_type": cls.TYPE,
            },
            stream,
        )

        # Extended port if needed
        if port_value == EXTENDED_PORT:
            uint.encode(port_value, stream)

        # Link address
        if ext_link:
            usint.encode(len(link_bytes), stream)
            stream.write(link_bytes)
            if len(link_bytes) % 2:
                stream.write(b"\x00")
        else:
            stream.write(link_bytes)

    @classmethod
    def decode(cls, stream: BinaryIO, header_value: int, _padded: bool) -> PortSegment:
        """Decode port segment from stream."""
        header = _port_header.decode_int(header_value)
        ext_link = header["ext_link"]
        port = header["port"]

        # Extended port
        if port == EXTENDED_PORT:
            port = uint.decode(stream)

        # Link address
        if ext_link:
            link_size = usint.decode(stream)
            if not link_size:
                raise ValueError("Extended link address size is 0")
            link = stream.read(link_size)
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


LOGICAL_FORMAT_SIZE_MAP = {
    1: LogicalFormat.format_8bit,
    2: LogicalFormat.format_16bit,
    4: LogicalFormat.format_32bit,
}


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

    type: LogicalSegmentType
    value: int | bytes

    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, padded: bool) -> None:
        """Encode logical segment to stream."""
        # Get value bytes
        val = value["value"]
        type_ = value["type"]
        value_bytes = _value_to_bytes(val)

        val_len = len(value_bytes)
        fmt = LOGICAL_FORMAT_SIZE_MAP.get(val_len)

        if fmt is None:
            raise ValueError("logical value too large")

        # Determine format
        if type_ == LogicalSegmentType.type_service_id:
            if val_len != 1:
                raise ValueError(
                    f"Invalid logical value for Service ID type, expected 1 byte, got: {val_len}"
                )
        elif type_ == LogicalSegmentType.type_special:
            raise ValueError("Logical segments with Special type are not supported")
        elif fmt == LogicalFormat.format_32bit and type_ not in (
            LogicalSegmentType.type_instance_id,
            LogicalSegmentType.type_connection_point,
        ):
            raise ValueError(
                "32-bit logical value only valid for Instance ID and Connection Point types"
            )

        # Write header
        _logical_header.encode(
            {
                "format": fmt,
                "logical_type": type_,
                "segment_type": cls.TYPE,
            },
            stream,
        )

        # Pad byte for 16/32 bit formats in padded mode
        if padded and fmt in (LogicalFormat.format_16bit, LogicalFormat.format_32bit):
            stream.write(b"\x00")

        stream.write(value_bytes)

    @classmethod
    def decode(cls, stream: BinaryIO, header_value: int, padded: bool) -> LogicalSegment:
        """Decode logical segment from stream."""
        header = _logical_header.decode_int(header_value)
        _type = LogicalSegmentType(header["logical_type"])
        _format = LogicalFormat(header["format"])

        # Validate format for specific types
        if _format == LogicalFormat.format_32bit and _type not in (
            LogicalSegmentType.type_instance_id,
            LogicalSegmentType.type_connection_point,
        ):
            raise ValueError(f"32-bit logical format on unsupported logical type: {_type:03b}")

        # Decode value based on type and format
        if _type == LogicalSegmentType.type_special:
            value = stream.read(6)  # Electronic key
        elif _format == LogicalFormat.format_8bit:
            value = usint.decode(stream)
        else:
            if padded:
                stream.read(1)  # Consume pad byte
            if _format == LogicalFormat.format_16bit:
                value = uint.decode(stream)
            else:  # format_32bit
                value = udint.decode(stream)

        return cls(_type, value)


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

    type: NetworkSegmentType
    data: bytes

    def __post_init__(self) -> None:
        NetworkSegmentType(self.type)  # validate type
        if not (self.type & _NETWORK_DATA_ARRAY_MASK) and len(self.data) != 1:
            raise ValueError(
                f"Network segment subtype {self.type:05b} requires exactly one byte of data"
            )

    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, _padded: bool) -> None:
        """Encode network segment to stream."""
        type_ = value["type"]
        data = value["data"]
        _network_header.encode(
            {"subtype": type_, "segment_type": cls.TYPE},
            stream,
        )

        if type_ & _NETWORK_DATA_ARRAY_MASK:
            data_len = len(data)
            if type_ == NetworkSegmentType.extended:
                data_len -= 2
            usint.encode(data_len, stream)
            stream.write(data)
        else:
            stream.write(data)

    @classmethod
    def decode(cls, stream: BinaryIO, header_value: int, _padded: bool) -> NetworkSegment:
        """Decode network segment from stream."""
        header = _network_header.decode_int(header_value)
        _type = NetworkSegmentType(header["subtype"])

        if _type & _NETWORK_DATA_ARRAY_MASK:
            data_len = usint.decode(stream)
            if _type == NetworkSegmentType.extended:
                data_len += 2
            data = stream.read(data_len)
        else:
            data = usint.decode(stream).to_bytes(1, byteorder="little")

        return cls(_type, data)


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


CHAR_SIZE_MAP: dict[int, int] = {
    SymbolicSegmentExtendedFormat.double_byte_chars: 2,
    SymbolicSegmentExtendedFormat.triple_byte_chars: 3,
}

_SYMBOLIC_EX_FORMAT_MASK = 0b111_00000
_SYMBOLIC_EX_SIZE_MASK = 0b000_11111
MAX_SYMBOL_SIZE = 31

EXT_TYPE_SIZE_MAP = {
    1: SymbolicSegmentExtendedFormat.numeric_symbol_usint,
    2: SymbolicSegmentExtendedFormat.numeric_symbol_uint,
    4: SymbolicSegmentExtendedFormat.numeric_symbol_udint,
}
EXT_TYPE_INT_MAP: dict[int, Int] = {
    SymbolicSegmentExtendedFormat.numeric_symbol_usint: usint,
    SymbolicSegmentExtendedFormat.numeric_symbol_uint: uint,
    SymbolicSegmentExtendedFormat.numeric_symbol_udint: udint,
}


class SymbolicSegment(CIPSegment):
    """Symbolic segment of a CIP path.

    Attributes:
        symbol: Symbol as ASCII string, numeric value, or raw bytes.
        ext_type: Extended format type (required for bytes, auto-set otherwise).
    """

    TYPE: ClassVar[SegmentType] = SegmentType.symbolic

    symbol: int | bytes
    ext_type: SymbolicSegmentExtendedFormat | int | None = None

    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, _padded: bool) -> None:
        """Encode symbolic segment to stream."""
        symbol = value["symbol"]
        ext_type = value["ext_type"]

        if isinstance(symbol, int):
            # Numeric symbol
            symbol_bytes = _value_to_bytes(symbol)
            ext_type_val = EXT_TYPE_SIZE_MAP[len(symbol_bytes)]
            _symbolic_header.encode(
                {"symbol_size": 0, "segment_type": cls.TYPE},
                stream,
            )
            usint.encode(ext_type_val, stream)
            stream.write(symbol_bytes)

        elif isinstance(symbol, bytes):
            if ext_type is None:
                # Raw bytes - treat as ASCII string if ext_type not provided
                if len(symbol) > MAX_SYMBOL_SIZE:
                    raise ValueError("symbol size too large, must be <= 31 characters")
                _symbolic_header.encode(
                    {"symbol_size": len(symbol), "segment_type": cls.TYPE},
                    stream,
                )
                stream.write(symbol)
            else:
                # Extended format with ext_type
                _format = ext_type & _SYMBOLIC_EX_FORMAT_MASK
                char_size = CHAR_SIZE_MAP.get(_format)

                if char_size:
                    if len(symbol) % char_size:
                        raise ValueError(
                            f"length of symbol with {char_size}-byte characters is not a multiple of {char_size}"
                        )
                    ext_type_val = _format | len(symbol) // char_size
                else:
                    ext_type_val = ext_type

                _symbolic_header.encode(
                    {"symbol_size": 0, "segment_type": cls.TYPE},
                    stream,
                )
                usint.encode(ext_type_val, stream)
                stream.write(symbol)
        else:
            raise TypeError(f"Unsupported symbol type: {type(symbol)}")

    @classmethod
    def decode(cls, stream: BinaryIO, header_value: int, _padded: bool) -> SymbolicSegment:
        """Decode symbolic segment from stream."""
        header = _symbolic_header.decode_int(header_value)
        symbol_size = header["symbol_size"]

        if not symbol_size:
            # Extended format
            ext_type = usint.decode(stream)
            size = ext_type & _SYMBOLIC_EX_SIZE_MASK
            _format = ext_type & _SYMBOLIC_EX_FORMAT_MASK

            char_size = CHAR_SIZE_MAP.get(_format)

            if char_size:
                symbol = stream.read(size * char_size)
            elif ext_type in EXT_TYPE_INT_MAP:
                int_type = EXT_TYPE_INT_MAP[ext_type]
                symbol = int_type.decode(stream)
            else:
                raise TypeError(f"unsupported extended string format type: {_format}")
            return cls(symbol, ext_type)
        else:
            # ASCII string - return as bytes to match encoding behavior
            return cls(stream.read(symbol_size))


# FUTURE: implement DataSegment?
# class DataSegmentType(IntEnum):
#     simple = 0b_00000
#     ansi_extended = 0b_10001


# class ConstructedDataTypeSegment(CIPSegment):
#     TYPE: ClassVar[SegmentType] = SegmentType.constructed_data_type


# class ElementaryDataTypeSegment(CIPSegment):
#     TYPE: ClassVar[SegmentType] = SegmentType.elementary_data_type


# ---------------------------------------------------------------------------
# CIPSegmentFmt (format type for segment dispatch)
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
        segment_type = SegmentType(value["segment_type"])
        segment_cls = CIPSegment.TYPES[segment_type]
        segment_cls.encode(value, stream, self.padded)

    def decode(self, stream: BinaryIO, **_: Any) -> CIPSegment:
        header_value = stream.read(1)[0]
        segment_type = SegmentType(header_value >> 5)
        segment_cls = CIPSegment.TYPES[segment_type]
        return segment_cls.decode(stream, header_value, self.padded)


# Convenience instances
cip_segment = CIPSegmentFmt(padded=False)
cip_segment_padded = CIPSegmentFmt(padded=True)


# Convenience format instances
epath_packed = array(cip_segment)
epath_padded = array(cip_segment_padded)
# small sized
short_sized_padded_epath = Sized(usint, epath_padded, factor=2)
# large sized
sized_padded_epath = Sized(uint, epath_padded, factor=2)
