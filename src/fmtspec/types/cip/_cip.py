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
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

import msgspec

from ..._protocol import Type  # noqa: TC001 (fails in msgspec if not truly imported)
from ...stream import peek
from .._array import array
from .._bitfield import Bitfield, Bitfields
from .._int import Int, u8le, u16le, u32le, u64le
from .._sized import Sized

if TYPE_CHECKING:
    from types import EllipsisType

    from ..._protocol import Context


# sentinel key for indicating a padded segment via context store
_PADDED_SEGMENT = object()

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

    __fmt__: ClassVar[Type]  # set in all subclasses
    TYPE: ClassVar[SegmentType] = SegmentType.port
    TYPES: ClassVar[dict[int, type[CIPSegment]]] = {}

    # does not run for this base class
    def __init_subclass__(cls, *args) -> None:
        # register relevant subclass information
        SEGMENT_TYPE_MAP[cls.__name__] = int(cls.TYPE)
        cls.TYPES[cls.TYPE] = cls
        return super().__init_subclass__(*args)


EXTENDED_PORT = 0x0F


class TypePortSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, **_: Any) -> None:
        # Determine port encoding
        port_value = value["port"]
        link_addr = value["link_address"]

        # Get link address bytes
        link_bytes = _value_to_bytes(link_addr)
        ext_link = len(link_bytes) > 1

        use_extended_port = port_value >= EXTENDED_PORT

        # Write header byte
        _port_header.encode(
            {
                "port": EXTENDED_PORT if use_extended_port else port_value,
                "ext_link": ext_link,
                "segment_type": PortSegment.TYPE,
            },
            stream,
        )

        # Write extended port value if needed (16-bit port number)
        if use_extended_port:
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
    def decode(cls, stream: BinaryIO, *, context: Context) -> PortSegment:
        header = _port_header.decode(stream, context=context)
        ext_link = header["ext_link"]
        port = header["port"]

        # Extended port
        if port == EXTENDED_PORT:
            port = uint.decode(stream, context=context)

        # Link address
        if ext_link:
            link_size = usint.decode(stream, context=context)
            if not link_size:
                raise ValueError("Extended link address size is 0")
            link = stream.read(link_size)
            # Consume pad byte if odd length
            if link_size % 2:
                stream.read(1)
        else:
            link = usint.decode(stream, context=context)

        return PortSegment(port, link, bool(ext_link))


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

    TYPE = SegmentType.port
    __fmt__ = TypePortSegment

    port: int
    link_address: int | bytes
    ext_link: bool = False


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

_LOGICAL_PAD_FORMATS = {
    LogicalFormat.format_16bit,
    LogicalFormat.format_32bit,
}


class TypeLogicalSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, **_: Any) -> None:
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

        # Write header
        _logical_header.encode(
            {
                "format": fmt,
                "logical_type": type_,
                "segment_type": LogicalSegment.TYPE,
            },
            stream,
        )

        # Pad byte for 16/32-bit formats (always required per CIP spec for word alignment)
        if fmt in _LOGICAL_PAD_FORMATS:
            stream.write(b"\x00")

        stream.write(value_bytes)

    @classmethod
    def decode(cls, stream: BinaryIO, *, context: Context) -> LogicalSegment:
        header = _logical_header.decode(stream, context=context)
        _type = LogicalSegmentType(header["logical_type"])
        _format = LogicalFormat(header["format"])

        # Decode value based on type and format
        if _type == LogicalSegmentType.type_special:
            value = stream.read(6)  # Electronic key
        elif _format == LogicalFormat.format_8bit:
            value = usint.decode(stream, context=context)
        else:
            # Consume pad byte (always present for 16/32-bit formats per CIP spec)
            stream.read(1)
            if _format == LogicalFormat.format_16bit:
                value = uint.decode(stream, context=context)
            else:  # format_32bit
                value = udint.decode(stream, context=context)

        return LogicalSegment(_type, value)


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

    TYPE = SegmentType.logical
    __fmt__ = TypeLogicalSegment

    type: LogicalSegmentType
    value: int | bytes


class NetworkSegmentType(IntEnum):
    scheduled = 0b00001
    fixed_tag = 0b00010
    production_inhibit_time = 0b00011
    safety = 0b10000
    extended = 0b11111


# Network types with data array format (bit 4 set)
_NETWORK_DATA_ARRAY_MASK = 0b10000


class TypeNetworkSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, **_: Any) -> None:
        type_ = value["type"]
        data = value["data"]
        _network_header.encode(
            {"subtype": type_, "segment_type": NetworkSegment.TYPE},
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
    def decode(cls, stream: BinaryIO, **_: Any) -> NetworkSegment:
        header = _network_header.decode(stream, **_)
        _type = NetworkSegmentType(header["subtype"])

        if _type & _NETWORK_DATA_ARRAY_MASK:
            data_len = usint.decode(stream, **_)
            if _type == NetworkSegmentType.extended:
                data_len += 2
            data = stream.read(data_len)
        else:
            data = stream.read(1)

        return NetworkSegment(_type, data)


class NetworkSegment(CIPSegment):
    """Network segment of a CIP path.

    Attributes:
        type: Network segment subtype.
        data: Segment data bytes.
    """

    TYPE = SegmentType.network
    __fmt__ = TypeNetworkSegment

    type: NetworkSegmentType
    data: bytes

    def __post_init__(self) -> None:
        NetworkSegmentType(self.type)  # validate type
        if not (self.type & _NETWORK_DATA_ARRAY_MASK) and len(self.data) != 1:
            raise ValueError(
                f"Network segment subtype {self.type:05b} requires exactly one byte of data"
            )


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

# ANSI Extended Symbol Segment marker (0x91)
# This is the standard CIP format for ASCII symbol names
ANSI_EXTENDED_SYMBOL = 0x91


class TypeSymbolicSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, *, context: Context) -> None:
        padded = context.store.get(_PADDED_SEGMENT)

        symbol = value["symbol"]
        ext_type = value["ext_type"]

        if isinstance(symbol, int):
            # Numeric symbol
            symbol_bytes = _value_to_bytes(symbol)
            ext_type_val = EXT_TYPE_SIZE_MAP[len(symbol_bytes)]
            _symbolic_header.encode(
                {"symbol_size": 0, "segment_type": SymbolicSegment.TYPE},
                stream,
            )
            usint.encode(ext_type_val, stream)
            stream.write(symbol_bytes)

        elif isinstance(symbol, bytes):
            if ext_type is None:
                # Use ANSI Extended Symbol format (0x91 + length + symbol)
                # This is the standard CIP format for ASCII symbol names
                stream.write(bytes([ANSI_EXTENDED_SYMBOL]))
                usint.encode(len(symbol), stream)
                stream.write(symbol)
                # Add padding byte for word alignment in padded mode
                if padded and len(symbol) % 2:
                    stream.write(b"\x00")
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
                    {"symbol_size": 0, "segment_type": SymbolicSegment.TYPE},
                    stream,
                )
                usint.encode(ext_type_val, stream)
                stream.write(symbol)
        else:
            raise TypeError(f"Unsupported symbol type: {type(symbol)}")

    @classmethod
    def decode(cls, stream: BinaryIO, *, context: Context) -> SymbolicSegment:
        padded = context.store.get(_PADDED_SEGMENT)
        header_value = stream.read(1)[0]

        # Check for ANSI Extended Symbol format (0x91)
        if header_value == ANSI_EXTENDED_SYMBOL:
            symbol_size = usint.decode(stream)
            symbol = stream.read(symbol_size)
            # Check for truncated data
            if len(symbol) < symbol_size:
                raise ValueError(
                    f"Truncated symbolic segment: expected {symbol_size} bytes, got {len(symbol)}"
                )
            # Consume padding byte for word alignment in padded mode
            if padded and symbol_size % 2:
                stream.read(1)
            return SymbolicSegment(symbol)

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
            return SymbolicSegment(symbol, ext_type)
        else:
            # ASCII string - return as bytes to match encoding behavior
            return SymbolicSegment(stream.read(symbol_size))


class SymbolicSegment(CIPSegment):
    """Symbolic segment of a CIP path.

    Attributes:
        symbol: Symbol as ASCII string, numeric value, or raw bytes.
        ext_type: Extended format type (required for bytes, auto-set otherwise).
    """

    TYPE = SegmentType.symbolic
    __fmt__ = TypeSymbolicSegment

    symbol: int | bytes
    ext_type: int | None = None


# Data segment header byte:
# Bits 0-4: Data Segment Subtype
# Bits 5-7: Segment Type (0b100 for data)
_data_header = Bitfields(
    size=1,
    fields={
        "subtype": Bitfield(bits=5),
        "segment_type": Bitfield(bits=3),
    },
)


class DataSegmentType(IntEnum):
    simple = 0b_00000

    # Note: 0x91 (ansi_extended = 0b_10001) is handled by SymbolicSegment
    # as ANSI Extended Symbol format for ASCII tag names
    # ansi_extended = 0b_10001


class TypeDataSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, **_: Any) -> None:
        type_ = value["type"]
        data = value["data"]

        _data_header.encode(
            {"subtype": type_, "segment_type": DataSegment.TYPE},
            stream,
        )

        # Word count (number of 16-bit words, rounded up)
        word_count = (len(data) + 1) // 2
        usint.encode(word_count, stream)

        # Write data
        stream.write(data)

        # Pad to word boundary if odd length
        if len(data) % 2:
            stream.write(b"\x00")

    @classmethod
    def decode(cls, stream: BinaryIO, **_: Any) -> DataSegment:
        header = _data_header.decode(stream, **_)
        type_ = DataSegmentType(header["subtype"])

        # Read word count
        word_count = usint.decode(stream, **_)

        # Read data (word_count * 2 bytes)
        byte_count = word_count * 2
        data = stream.read(byte_count)

        # Note: We preserve exact byte count; caller should handle trailing padding
        # For simple, the actual data length may be less than word_count * 2
        # but we can't know the exact length without additional context
        return DataSegment(type_, data)


class DataSegment(CIPSegment):
    """Data segment of a CIP path.

    +----+----+----+----+----+----+----+----+
    | Segment Type | Data Segment Subtype   |
    +====+====+====+====+====+====+====+====+
    |  7 |  6 |  5 |  4 |  3 |  2 |  1 |  0 |
    +----+----+----+----+----+----+----+----+

    For simple subtype (0x00):
    - Followed by word count (USINT) specifying number of 16-bit words
    - Then data words

    Attributes:
        type: Data segment subtype.
        data: Data bytes.
    """

    TYPE = SegmentType.data
    __fmt__ = TypeDataSegment

    type: DataSegmentType
    data: bytes


# Elementary data type segment header byte:
# Bits 0-4: Type-specific encoding
# Bits 5-7: Segment Type (0b110 for elementary data type)
_elementary_header = Bitfields(
    size=1,
    fields={
        "type_lower": Bitfield(bits=5),
        "segment_type": Bitfield(bits=3),
    },
)


class TypeElementaryDataSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, *, context: Context) -> None:
        padded = context.store.get(_PADDED_SEGMENT)

        type_code = value["type_code"]

        # Write the type code directly - high 3 bits are segment type
        # For type codes >= 0xC0, the high bits are already 0b110
        stream.write(bytes([type_code]))

        # Add padding for word alignment in padded mode
        if padded:
            stream.write(b"\x00")

    @classmethod
    def decode(cls, stream: BinaryIO, *, context: Context) -> ElementaryDataTypeSegment:
        padded = context.store.get(_PADDED_SEGMENT)

        # The header_value IS the type_code (segment type in bits 5-7)
        type_code = stream.read(1)[0]

        # Consume padding byte in padded mode
        if padded:
            stream.read(1)

        return ElementaryDataTypeSegment(type_code)


class ElementaryDataTypeSegment(CIPSegment):
    """Elementary data type segment of a CIP path.

    +----+----+----+----+----+----+----+----+
    | Segment Type | Type Code (lower 5)    |
    +====+====+====+====+====+====+====+====+
    |  7 |  6 |  5 |  4 |  3 |  2 |  1 |  0 |
    +----+----+----+----+----+----+----+----+

    CIP Elementary Data Types:
    - BOOL (0xC1), SINT (0xC2), INT (0xC3), DINT (0xC4), LINT (0xC5)
    - USINT (0xC6), UINT (0xC7), UDINT (0xC8), ULINT (0xC9)
    - REAL (0xCA), LREAL (0xCB)
    - STRING (0xD0), BYTE (0xD1), WORD (0xD2), DWORD (0xD3), LWORD (0xD4)

    Attributes:
        type_code: CIP elementary type code (e.g., 0xC1 for BOOL).
    """

    TYPE = SegmentType.elementary_data_type
    __fmt__ = TypeElementaryDataSegment

    type_code: int


# Constructed data type segment header byte:
# Bits 0-4: Type-specific encoding
# Bits 5-7: Segment Type (0b101 for constructed data type)
_constructed_header = Bitfields(
    size=1,
    fields={
        "type_lower": Bitfield(bits=5),
        "segment_type": Bitfield(bits=3),
    },
)


class TypeConstructedDataTypeSegment:
    @classmethod
    def encode(cls, value: dict[str, Any], stream: BinaryIO, **_: Any) -> None:
        type_code = value["type_code"]
        data = value["data"]

        # Write the type code directly - high 3 bits are segment type
        stream.write(bytes([type_code]))

        # Write word count (number of 16-bit words)
        word_count = (len(data) + 1) // 2
        usint.encode(word_count, stream)

        # Write data
        stream.write(data)

        # Pad to word boundary if odd length
        if len(data) % 2:
            stream.write(b"\x00")

    @classmethod
    def decode(cls, stream: BinaryIO, **_: Any) -> ConstructedDataTypeSegment:
        type_code = stream.read(1)[0]

        # Read word count
        word_count = usint.decode(stream, **_)

        # Read data (word_count * 2 bytes)
        byte_count = word_count * 2
        data = stream.read(byte_count)

        return ConstructedDataTypeSegment(type_code, data)


class ConstructedDataTypeSegment(CIPSegment):
    """Constructed data type segment of a CIP path.

    +----+----+----+----+----+----+----+----+
    | Segment Type | Type Code (lower 5)    |
    +====+====+====+====+====+====+====+====+
    |  7 |  6 |  5 |  4 |  3 |  2 |  1 |  0 |
    +----+----+----+----+----+----+----+----+

    CIP Constructed Data Types:
    - Array (0xA0), Abbreviated Array (0xA1)
    - Structure (0xA2), Abbreviated Structure (0xA3)

    Attributes:
        type_code: CIP constructed type code (e.g., 0xA0 for array).
        data: Additional type definition data.
    """

    TYPE = SegmentType.constructed_data_type
    __fmt__ = TypeConstructedDataTypeSegment

    type_code: int
    data: bytes


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

    def encode(self, value: dict[str, Any], stream: BinaryIO, *, context: Context) -> None:
        # set padding context for segment encoding
        context.store[_PADDED_SEGMENT] = self.padded

        segment_type = SegmentType(value["segment_type"])
        segment_cls = CIPSegment.TYPES[segment_type]
        # _encode_stream(value, segment_cls.__fmt__, stream, context=context)
        segment_cls.__fmt__.encode(value, stream, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> CIPSegment:
        # set padding context for segment decoding
        context.store[_PADDED_SEGMENT] = self.padded

        header_value = peek(stream, 1)[0]

        # Special case: ANSI Extended Symbol format (0x91)
        # This marker has segment type bits = 0b100 (data) but is actually
        # a symbolic segment in CIP
        if header_value == ANSI_EXTENDED_SYMBOL:
            segment_cls = CIPSegment.TYPES[SymbolicSegment.TYPE]
        else:
            segment_type = SegmentType(header_value >> 5)
            segment_cls = CIPSegment.TYPES[segment_type]

        # return _decode_stream(stream, segment_cls.__fmt__, context=context)[0]
        return segment_cls.__fmt__.decode(stream, context=context)


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
