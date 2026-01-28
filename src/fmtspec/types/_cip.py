from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from enum import IntEnum
from io import BytesIO
from math import log
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast, override

from ._array import array

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class SegmentType(IntEnum):
    port = 0b_000_00000
    logical = 0b_001_00000
    network = 0b_010_00000
    symbolic = 0b_011_00000
    data = 0b_100_00000
    constructed_data_type = 0b_101_00000
    elementary_data_type = 0b_110_00000
    reserved = 0b_111_00000
    mask = 0b_111_00000


def _segment_type_bits(segment_type: int) -> str:
    return f"{segment_type:08b}"[:3]


class DataType:
    __encoded_value__: bytes = b""
    size: ClassVar[int] = 0

    def __new__(cls, *args: Any, **kwargs: Any):
        if super().__new__ is object.__new__:
            return super().__new__(cls)
        return super().__new__(cls, *args, **kwargs)

    def __bytes__(self) -> bytes:
        return self.__class__.encode(self)

    @classmethod
    def encode(cls: type[Self], value: Self, *args: Any, **kwargs: Any) -> bytes:
        """
        Serializes a Python object ``value`` to ``bytes``.

        .. note::
            Any subclass overriding this method must catch any exception and re-raise a :class:`DataError`
        """
        return cls._encode(value, *args, **kwargs)

    @classmethod
    def _encode(cls: type[Self], value: Self, *args: Any, **kwargs: Any) -> bytes:  # pyright: ignore[reportUnusedParameter]
        raise NotImplementedError

    @classmethod
    def decode(cls, buffer) -> Self:
        """
        Deserializes a Python object from the ``buffer`` of ``bytes``

        .. note::
            Any subclass overriding this method must catch any exception and re-raise as a :class:`DataError`.
            Except ``BufferEmptyErrors`` they must be re-raised as such, array decoding relies on this.
        """
        stream = BytesIO(buffer)
        value = cls._decode(stream)
        if isinstance(buffer, bytes) and (leftover := stream.read()):
            raise ValueError(f"Leftover data after decoding {cls.__name__}: {leftover!r}")
        return value

    @classmethod
    def _decode(cls, stream: BytesIO) -> Self:  # pyright: ignore[reportUnusedParameter]
        raise NotImplementedError

    @classmethod
    def _stream_read(cls, stream: BytesIO, size: int) -> bytes:
        """
        Reads `size` bytes from `stream`.
        Raises `BufferEmptyError` if stream returns no data.
        """
        if not (data := stream.read(size)):
            raise EOFError()
        return data

    @classmethod
    def _stream_peek(cls, stream: BytesIO, size: int) -> bytes:
        return stream.getvalue()[stream.tell() : stream.tell() + size]

    def __rich__(self) -> str:
        return self.__repr__()


class USINT(DataType):
    """
    Unsigned 8-bit integer
    """

    code: ClassVar[int] = 0xC6  #: 0xC6
    _format: ClassVar[str] = "<B"


class UINT(DataType):
    """
    Unsigned 16-bit integer
    """

    code: ClassVar[int] = 0xC7  #: 0xC7
    _format: ClassVar[str] = "<H"


class UDINT(DataType):
    """
    Unsigned 32-bit integer
    """

    code: ClassVar[int] = 0xC8  #: 0xC8
    _format: ClassVar[str] = "<I"


class ULINT(DataType):
    """
    Unsigned 64-bit integer
    """

    code: ClassVar[int] = 0xC9  #: 0xC9
    _format: ClassVar[str] = "<Q"


@dataclass
class CIPSegment(DataType):
    """
    Base type for a CIP path segment

    +----+----+----+----+----+----+----+----+
    | Segment Type | Segment Format         |
    +====+====+====+====+====+====+====+====+
    | 7  | 6  | 5  | 4  | 3  | 2  | 1  | 0  |
    +----+----+----+----+----+----+----+----+

    """

    segment_type: ClassVar[SegmentType] = SegmentType.port

    @override
    @classmethod
    def encode(cls, value: Self, padded: bool = False, *args: Any, **kwargs: Any) -> bytes:
        """
        Encodes an instance of a ``CIPSegment`` to bytes
        """
        return cls._encode(value, padded)

    @classmethod
    def _decode_segment_type(cls, buffer: BytesIO) -> USINT:
        segment_type = USINT.decode(buffer)
        if (segment_type & SegmentType.mask) != cls.segment_type:
            raise TypeError(
                f"Segment type invalid for {cls.__name__} ({_segment_type_bits(cls.segment_type)}): {_segment_type_bits(segment_type)}"
            )

        return segment_type

    @override
    @classmethod
    def decode(cls: type[Self], buffer, padded: bool = False) -> Self:
        stream = BytesIO(buffer)
        return cls._decode(stream, padded)

    @override
    @classmethod
    def _decode(cls, stream: BytesIO, padded: bool = False) -> Self:
        _peek = stream.getvalue()[stream.tell() : stream.tell() + 1]
        if not _peek:
            raise EOFError()

        segment_type = _peek[0] & SegmentType.mask
        for subcls in CIPSegment.__subclasses__():
            if subcls.segment_type == segment_type:
                return cast("Self", subcls.decode(stream, padded))

        raise TypeError(f"Unknown segment type: {_segment_type_bits(segment_type)}")


class PortIdentifier(IntEnum):
    backplane = 0b_000_0_0001
    bp = 0b_000_0_0001
    enet = 0b_000_0_0010
    a = 0b_000_0_0010
    b = 0b_000_0_0011
    a1 = 0b_000_0_0011
    a2 = 0b_000_0_0100


PORT_ALIASES: dict[str, PortIdentifier] = PortIdentifier._member_map_  # type: ignore


class PortSegmentFormat(IntEnum):
    ex_link_address = 0b_000_1_0000
    mask_port_id = 0b_000_0_1111


def _find_best_uint_type(value: int) -> USINT | UINT | UDINT:
    num_bytes = (int(log(value, 256)) + 1) if value else 1
    if value == 0 or num_bytes <= USINT.size:
        return USINT(value)
    elif num_bytes <= UINT.size:
        return UINT(value)
    elif num_bytes <= UDINT.size:
        return UDINT(value)
    else:
        raise ValueError(f"Cannot convert {value}, requires too many bytes ({num_bytes})")


@dataclass
class PortSegment(CIPSegment):
    """
    Port segment of a CIP path.

    +----+----+----+--------------------+----+----+----+----+
    | Segment Type | Extended Link Addr | Port Identifier   |
    +====+====+====+====================+====+====+====+====+
    |  7 |  6 | 5  |         4          |  3 |  2 |  1 |  0 |
    +----+----+----+--------------------+----+----+----+----+

    """

    segment_type: ClassVar[SegmentType] = SegmentType.port

    # don't use these fields when comparing segments, use the private versions instead
    # since they are the actual encoded values
    port: PortIdentifier | int | str = field(compare=False)
    link_address: int | str | bytes = field(compare=False)

    _port: USINT = field(init=False, repr=False)
    _link: bytes | DataType = field(init=False, repr=False)
    _ex_link: bool = field(default=False, init=False, repr=False)
    _link_addr_size: USINT = field(default=USINT(0), init=False, repr=False)
    _ex_port: UINT = field(default=UINT(0), init=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.port, str):
            if self.port.isdigit():
                self.port = USINT(int(self.port))
            else:
                self.port = PORT_ALIASES[self.port.lower()]
        if self.port > PortSegmentFormat.mask_port_id:
            self._port = USINT(PortSegmentFormat.mask_port_id)
            self._ex_port = UINT(self.port)
        else:
            self._port = USINT(self.port)

        if isinstance(self.link_address, str):
            if self.link_address.isnumeric():
                self._link = bytes(_find_best_uint_type(int(self.link_address)))
            else:
                ip = ipaddress.ip_address(self.link_address)
                self._link = str(ip).encode()
        elif isinstance(self.link_address, int):
            self._link = bytes(_find_best_uint_type(self.link_address))
        else:
            self._link = self.link_address

        if len(self._link) > 1:
            self._ex_link = True
            self._link_addr_size = USINT(len(self._link))

    @override
    @classmethod
    def _encode(cls, value: Self, padded: bool = False, *args: Any, **kwargs: Any) -> bytes:
        segment_type = cls.segment_type | value._port
        if value._ex_link:
            segment_type |= PortSegmentFormat.ex_link_address

        msg = b"".join(
            bytes(x)
            for x in (
                USINT(segment_type),
                value._ex_port if value._ex_port else b"",
                value._link_addr_size if value._ex_link else b"",
                value._link,
            )
        )
        if len(msg) % 2:
            msg += b"\x00"

        return msg

    @override
    @classmethod
    def _decode(cls, stream: BytesIO, padded: bool = False) -> Self:
        segment_type = cls._decode_segment_type(stream)
        ex_link = bool(segment_type & PortSegmentFormat.ex_link_address)
        port = segment_type & PortSegmentFormat.mask_port_id

        if port == PortSegmentFormat.mask_port_id:
            port = UINT.decode(stream)

        link: bytes | USINT
        if ex_link:
            link_addr_size = USINT.decode(stream)
            if not link_addr_size:
                raise ValueError("Extended link address size is 0")
            try:
                link = cls._stream_read(stream, link_addr_size)
            except EOFError:
                link = b""
            if len(link) != link_addr_size:
                raise ValueError(
                    f"Extended link address invalid, expected {int(link_addr_size)} byte(s), got: {len(link)}"
                )

            if link_addr_size % 2:
                try:
                    _pad = cls._stream_read(stream, 1)
                except EOFError:
                    raise ValueError("Expected a pad byte following link address")
        else:
            link = USINT.decode(stream)

        return cls(port, link)


class LogicalSegmentType(IntEnum):
    type_class_id = 0b_000_000_00
    type_instance_id = 0b_000_001_00
    type_member_id = 0b_000_010_00
    type_connection_point = 0b_000_011_00
    type_attribute_id = 0b_000_100_00
    type_special = 0b_000_101_00
    type_service_id = 0b_000_110_00
    type_reserved = 0b_000_111_00
    mask_type = 0b_000_111_00

    format_8bit = 0b_000_000_00
    format_16bit = 0b_000_000_01
    format_32bit = 0b_000_000_10
    format_reserved = 0b_000_000_11
    format_8bit_service_id = 0b_000_000_00
    format_electronic_key = 0b_000_000_00
    mask_format = 0b_000_000_11


def _logical_format_bits(fmt: int) -> str:
    return f"{fmt:08b}"[-2:]


def _logical_type_bits(fmt: int) -> str:
    return f"{fmt:08b}"[3:6]


@dataclass
class LogicalSegment(CIPSegment):
    """
    Logical segment of a CIP path

    +----+----+----+----+----+----+-------+--------+
    | Segment Type | Logical Type | Logical Format |
    +====+====+====+====+====+====+=======+========+
    |  7 |  6 |  5 | 4  |  3 |  2 |   1   |    0   |
    +----+----+----+----+----+----+-------+--------+
    """

    segment_type: ClassVar[SegmentType] = SegmentType.logical
    type: LogicalSegmentType
    value: int | bytes

    _value: bytes = field(default=b"", init=False, repr=False)
    _format: LogicalSegmentType = field(default=LogicalSegmentType.format_8bit, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.value, int):
            self._value = bytes(_find_best_uint_type(self.value))
        else:
            self._value = self.value

        _val_len = len(self._value)

        if self.type == LogicalSegmentType.type_service_id:
            if _val_len != 1:
                raise ValueError(
                    f"Invalid logical value for Service ID type, expected 1 byte, got: {_val_len}"
                )
            self._format = LogicalSegmentType.format_8bit_service_id
        elif self.type == LogicalSegmentType.type_special:
            self._format = LogicalSegmentType.format_electronic_key
            # FUTURE: support electronic key
            raise ValueError("Logical segments with Special type are not supported")
        elif _val_len == 1:
            self._format = LogicalSegmentType.format_8bit
        elif _val_len == 2:
            self._format = LogicalSegmentType.format_16bit
        elif _val_len == 4:
            if self.type not in (
                LogicalSegmentType.type_instance_id,
                LogicalSegmentType.type_connection_point,
            ):
                raise ValueError(
                    "32-bit logical value only valid for Instance ID and Connection Point types"
                )
            self._format = LogicalSegmentType.format_32bit
        else:
            raise ValueError("logical value too large")

    @override
    @classmethod
    def _encode(cls, value: Self, padded: bool = False, *args: Any, **kwargs: Any) -> bytes:
        segment_type = bytes(USINT(cls.segment_type | value.type | value._format))
        if padded and value._format in (
            LogicalSegmentType.format_16bit,
            LogicalSegmentType.format_32bit,
        ):
            segment_type += b"\x00"

        return segment_type + value._value

    @override
    @classmethod
    def _decode(cls, stream: BytesIO, padded: bool = False) -> Self:
        segment_type = cls._decode_segment_type(stream)
        _type = segment_type & LogicalSegmentType.mask_type
        _format = segment_type & LogicalSegmentType.mask_format

        if _type == LogicalSegmentType.type_reserved:
            raise ValueError("Unsupported logical type: Reserved")

        if _format == LogicalSegmentType.format_reserved:
            raise ValueError("Unsupported logical format: Reserved")
        elif _format == LogicalSegmentType.format_32bit and _type not in (
            LogicalSegmentType.type_instance_id,
            LogicalSegmentType.type_connection_point,
        ):
            raise ValueError(
                f"32-bit logical format on unsupported logical type: {_logical_type_bits(_type)}"
            )

        value: int | bytes
        if _type == LogicalSegmentType.type_special:
            if _format != LogicalSegmentType.format_electronic_key:
                raise ValueError(
                    f"Unsupported logical format for Special type (00): {_logical_format_bits(_format)}"
                )
            value = cls._stream_read(stream, 6)  # FUTURE: support electronic key
        elif _type == LogicalSegmentType.type_service_id:
            if _format != LogicalSegmentType.format_8bit_service_id:
                raise ValueError(
                    f"Unsupported logical format for Service ID type (00): {_logical_format_bits(_format)}"
                )
            value = USINT.decode(stream)
        elif _format == LogicalSegmentType.format_8bit:
            value = USINT.decode(stream)
        else:
            if padded:
                _ = stream.read(1)
            if _format == LogicalSegmentType.format_16bit:
                value = UINT.decode(stream)
            else:
                value = UDINT.decode(stream)

        return cls(LogicalSegmentType(_type & LogicalSegmentType.mask_type), value)


class NetworkSegmentType(IntEnum):
    scheduled = 0b_000_00001
    fixed_tag = 0b_000_00010
    production_inhibit_time = 0b_000_00011
    safety = 0b_000_10000
    extended = 0b_000_11111

    mask_type = 0b_000_11111
    mask_data_array = 0b_000_10000


_supported_network_segment_types = {
    NetworkSegmentType.scheduled,
    NetworkSegmentType.fixed_tag,
    NetworkSegmentType.production_inhibit_time,
    NetworkSegmentType.safety,
    NetworkSegmentType.extended,
}


def _network_type_bits(typ: int) -> str:
    return f"{typ:08b}"[3:]


@dataclass
class NetworkSegment(CIPSegment):
    segment_type: ClassVar[SegmentType] = SegmentType.network
    type: NetworkSegmentType
    data: bytes

    # unsure of how extended segment subtypes work, for now treated as first 2 bytes of data

    def __post_init__(self):
        if self.type not in _supported_network_segment_types:
            raise ValueError(
                f"Network segment subtype unsupported: {_network_type_bits(self.type)}"
            )
        if not (self.type & NetworkSegmentType.mask_data_array) and len(self.data) != 1:
            raise ValueError(
                f"Network segment subtype {_network_type_bits(self.type)} requires exactly one byte of data"
            )

    @override
    @classmethod
    def _encode(cls, value: Self, *args: Any, **kwargs: Any) -> bytes:
        _segment_type = bytes(USINT(value.segment_type | value.type))
        if value.type & NetworkSegmentType.mask_data_array:
            _len = len(value.data)
            if value.type == NetworkSegmentType.extended:
                _len -= 2
            return b"".join([_segment_type, bytes(USINT(_len)), value.data])
        else:
            return _segment_type + value.data

    @override
    @classmethod
    def _decode(cls, stream: BytesIO, padded: bool = False) -> Self:
        segment_type = cls._decode_segment_type(stream)
        _type = segment_type & NetworkSegmentType.mask_type
        if _type not in _supported_network_segment_types:
            raise ValueError(f"Network segment subtype unsupported: {_network_type_bits(_type)}")

        if _type & NetworkSegmentType.mask_data_array:
            _len = USINT.decode(stream)
            if _type == NetworkSegmentType.extended:
                _len += 2
            data = stream.read(_len)
        else:
            data = bytes(USINT.decode(stream))

        return cls(NetworkSegmentType(_type), data)


class SymbolicSegmentType(IntEnum):
    mask_symbol_size = 0b_000_11111


class SymbolicSegmentExtendedFormat(IntEnum):
    double_byte_chars = 0b_001_00000
    triple_byte_chars = 0b_010_00000

    _numeric_format = 0b_110_00000
    _numeric_usint = 0b_000_00110
    _numeric_uint = 0b_000_00111
    _numeric_udint = 0b_000_01000

    numeric_symbol_usint = _numeric_format | _numeric_usint
    numeric_symbol_uint = _numeric_format | _numeric_uint
    numeric_symbol_udint = _numeric_format | _numeric_udint

    mask_format = 0b_111_00000
    mask_size = 0b_000_11111


MAX_SYMBOL_SIZE = 31


@dataclass
class SymbolicSegment(CIPSegment):
    segment_type: ClassVar[SegmentType] = SegmentType.symbolic
    symbol: str | USINT | UINT | UDINT | bytes

    #: Extended symbol type, only required when ``symbol`` is of type ``bytes``, else set automatically
    #: If using double/triple byte extended format, this value will be mutated to include the string length
    ex_type: SymbolicSegmentExtendedFormat | int | None = None

    def __post_init__(self):
        if isinstance(self.symbol, bytes):
            if self.ex_type is None:
                raise ValueError("symbol of type bytes requires 'type' to be provided")
            else:
                _format = self.ex_type & SymbolicSegmentExtendedFormat.mask_format
                if _format == SymbolicSegmentExtendedFormat.double_byte_chars:
                    if len(self.symbol) % 2:
                        raise ValueError(
                            "length of symbol with double-byte characters is not a multiple of 2"
                        )
                    else:
                        self.ex_type = (
                            SymbolicSegmentExtendedFormat.double_byte_chars | len(self.symbol) // 2
                        )
                elif _format == SymbolicSegmentExtendedFormat.triple_byte_chars:
                    if len(self.symbol) % 3:
                        raise ValueError(
                            "length of symbol with triple-byte characters is not a multiple of 3"
                        )
                    else:
                        self.ex_type = (
                            SymbolicSegmentExtendedFormat.triple_byte_chars | len(self.symbol) // 3
                        )

        elif isinstance(self.symbol, str):
            if len(self.symbol) > MAX_SYMBOL_SIZE:
                raise ValueError("symbol size too large, must be <= 31 characters")

        elif isinstance(self.symbol, USINT):
            self.ex_type = SymbolicSegmentExtendedFormat.numeric_symbol_usint
        elif isinstance(self.symbol, UINT):
            self.ex_type = SymbolicSegmentExtendedFormat.numeric_symbol_uint
        else:
            self.ex_type = SymbolicSegmentExtendedFormat.numeric_symbol_udint

    @override
    @classmethod
    def _encode(cls, value: Self, *args: Any, **kwargs: Any) -> bytes:
        if isinstance(value.symbol, str):
            _type = bytes(USINT(cls.segment_type | len(value.symbol)))
            data = value.symbol.encode("ascii")
        else:
            if value.ex_type is None:
                raise ValueError("symbol ex_type must not be None")
            _type = bytes(USINT(cls.segment_type)) + bytes(USINT(value.ex_type))
            data = bytes(value.symbol)

        return _type + data

    @override
    @classmethod
    def _decode(cls, stream: BytesIO, padded: bool = False) -> Self:
        segment_type = USINT.decode(stream)
        _type = segment_type & SymbolicSegmentType.mask_symbol_size
        if not _type:
            ex_type = USINT.decode(stream)
            size = ex_type & SymbolicSegmentExtendedFormat.mask_size
            _format = ex_type & SymbolicSegmentExtendedFormat.mask_format
            symbol: str | USINT | UINT | UDINT | bytes

            if _format == SymbolicSegmentExtendedFormat.double_byte_chars:
                symbol = cls._stream_read(stream, size * 2)
            elif _format == SymbolicSegmentExtendedFormat.triple_byte_chars:
                symbol = cls._stream_read(stream, size * 3)
            elif ex_type == SymbolicSegmentExtendedFormat.numeric_symbol_usint:
                symbol = USINT.decode(stream)
            elif ex_type == SymbolicSegmentExtendedFormat.numeric_symbol_uint:
                symbol = UINT.decode(stream)
            elif ex_type == SymbolicSegmentExtendedFormat.numeric_symbol_udint:
                symbol = UDINT.decode(stream)
            else:
                raise TypeError(f"unsupported extended string format type: {_format}")
        else:
            ex_type = None
            symbol = cls._stream_read(stream, _type).decode("ascii")

        return cls(symbol, ex_type=ex_type)


class DataSegmentType(IntEnum):
    simple = 0b_000_00000
    ansi_extended = 0b_000_10001


# @dataclass
# class DataSegment(CIPSegment):
#     """
#     +----+----+----+---+---+---+---+---+
#     | Segment Type | Segment Sub-Type  |
#     +====+====+====+===+===+===+===+===+
#     |  7 |  6 | 5  | 4 | 3 | 2 | 1 | 0 |
#     +----+----+----+---+---+---+---+---+
#     """

#     segment_type: ClassVar[SegmentType] = SegmentType.data

#     data: str | bytes
#     _type: DataSegmentType = field(default=DataSegmentType.simple, init=False, repr=False)

#     def __post_init__(self) -> None:
#         self._type = (
#             DataSegmentType.simple
#             if isinstance(self.data, bytes)
#             else DataSegmentType.ansi_extended
#         )

#     @override
#     @classmethod
#     def _encode(cls, value: Self, padded: bool = False, *args: Any, **kwargs: Any) -> bytes:
#         segment_type = cls.segment_type | value._type
#         if value._type == DataSegmentType.simple:
#             if not isinstance(value.data, bytes):
#                 raise TypeError("data must be bytes")
#             data = bytes(USINT(len(value.data) // 2)) + value.data
#         else:
#             if isinstance(value.data, bytes):
#                 raise TypeError("data must be a string")
#             data = bytes(SHORT_STRING(value.data))
#             if padded and len(value.data) % 2:
#                 data += b"\x00"

#         return bytes(USINT(segment_type)) + data


class ConstructedDataTypeSegment(CIPSegment):
    segment_type: ClassVar[SegmentType] = SegmentType.constructed_data_type


class ElementaryDataTypeSegment(CIPSegment):
    segment_type: ClassVar[SegmentType] = SegmentType.elementary_data_type


__EPATH_TYPE_CACHE__: dict[tuple[bool, bool, bool, int | None], type[EPATH]] = {}


@dataclass
class EPATH(DataType):
    """
    CIP path segments
    """

    code: ClassVar[int] = 0xDC  #: 0xDC
    padded: ClassVar[bool] = False
    with_len: ClassVar[bool] = False
    pad_len: ClassVar[bool] = False
    length: ClassVar[int | None] = None

    segments: Sequence[CIPSegment]

    def __post_init__(self) -> None:
        if any(not isinstance(x, CIPSegment) for x in self.segments):
            raise TypeError("segments all must be instances of CIPSegment")
        if self.length is not None and len(self.segments) != self.length:
            raise ValueError(
                f"length mismatch, require {self.length} segments, got {len(self.segments)}"
            )
        self.segments = [s for s in self.segments]

    @override
    @classmethod
    def _encode(cls, value: Self, *args: Any, **kwargs: Any) -> bytes:
        path = b"".join(segment.encode(segment, padded=cls.padded) for segment in value.segments)
        if cls.with_len:
            _len = USINT.encode(len(path) // 2)
            if cls.pad_len:
                _len += b"\x00"
            path = _len + path
        return path

    @override
    @classmethod
    def _decode(cls, stream: BytesIO) -> Self:
        if cls.with_len:
            _len = USINT.decode(stream)
            if cls.pad_len:
                _ = USINT.decode(stream)
            data = cls._stream_read(stream, _len * 2)
            ary_type = array(CIPSegment)  # greedy
            segments = [s for s in ary_type.decode(data, padded=cls.padded)]
        else:
            if cls.length is None:
                ary_type = array(CIPSegment)  # greedy
            else:
                ary_type = array(CIPSegment, cls.length)

            segments = [s for s in ary_type.decode(stream, padded=cls.padded)]
        return cls(segments)

    def __truediv__(self, other: CIPSegment | Sequence[CIPSegment]) -> Self:
        new_segments = [other] if isinstance(other, CIPSegment) else [o for o in other]
        return self.__class__([*self.segments, *new_segments])

    def __class_getitem__(cls, item: int) -> type[Self]:
        if not isinstance(item, int):
            raise ValueError("must be int to create fixed-size EPATH")  # pyright: ignore[reportUnreachable]
        key = (cls.padded, cls.with_len, cls.pad_len, item)
        if key not in __EPATH_TYPE_CACHE__:
            klass = type(
                f"{cls.__name__}x{item}",
                (cls,),
                {
                    "padded": cls.padded,
                    "with_len": cls.with_len,
                    "pad_len": cls.pad_len,
                    "length": item,
                },
            )
            __EPATH_TYPE_CACHE__[key] = klass
        return cast("type[Self]", __EPATH_TYPE_CACHE__[key])

    def __iter__(self) -> Iterator[CIPSegment]:
        yield from self.segments


class PADDED_EPATH(EPATH):
    padded: ClassVar[bool] = True


class PACKED_EPATH(EPATH):
    padded: ClassVar[bool] = False


class PADDED_EPATH_LEN(PADDED_EPATH):
    with_len: ClassVar[bool] = True


class PADDED_EPATH_PAD_LEN(PADDED_EPATH):
    with_len: ClassVar[bool] = True
    pad_len: ClassVar[bool] = True
