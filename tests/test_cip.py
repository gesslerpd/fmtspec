"""Tests for CIP (Common Industrial Protocol) types."""

from io import BytesIO

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode
from fmtspec._core import _convert, _to_builtins
from fmtspec.types import (
    ConstructedDataTypeSegment,
    # data segment types
    DataSegment,
    DataSegmentType,
    ElementaryDataTypeSegment,
    LogicalSegment,
    # enums
    LogicalSegmentType,
    NetworkSegment,
    NetworkSegmentType,
    # segment types
    PortSegment,
    SymbolicSegment,
    SymbolicSegmentExtendedFormat,
    cip_segment,
    cip_segment_padded,
    epath_packed,
    epath_padded,
    short_sized_padded_epath,
    sized_padded_epath,
)

# ---------------------------------------------------------------------------
# LogicalSegment Tests
# ---------------------------------------------------------------------------


class TestLogicalSegment:
    """Tests for LogicalSegment encoding and decoding."""

    def test_class_id_8bit(self) -> None:
        """Test LogicalSegment with 8-bit class ID."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02)
        data = encode(segment, cip_segment)
        # 0x20 = logical segment + class ID type + 8-bit format
        assert data == b"\x20\x02"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_class_id
        assert result.value == 0x02

    def test_instance_id_8bit(self) -> None:
        """Test LogicalSegment with 8-bit instance ID."""
        segment = LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01)
        data = encode(segment, cip_segment)
        # 0x24 = logical segment + instance ID type + 8-bit format
        assert data == b"\x24\x01"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_instance_id
        assert result.value == 0x01

    def test_attribute_id_8bit(self) -> None:
        """Test LogicalSegment with 8-bit attribute ID."""
        segment = LogicalSegment(type=LogicalSegmentType.type_attribute_id, value=0x03)
        data = encode(segment, cip_segment)
        # 0x30 = logical segment + attribute ID type + 8-bit format
        assert data == b"\x30\x03"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_attribute_id
        assert result.value == 0x03

    def test_connection_point_8bit(self) -> None:
        """Test LogicalSegment with 8-bit connection point."""
        segment = LogicalSegment(type=LogicalSegmentType.type_connection_point, value=0x01)
        data = encode(segment, cip_segment)
        # 0x2C = logical segment + connection point type + 8-bit format
        assert data == b"\x2c\x01"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_connection_point

    def test_member_id_8bit(self) -> None:
        """Test LogicalSegment with 8-bit member ID."""
        segment = LogicalSegment(type=LogicalSegmentType.type_member_id, value=0x05)
        data = encode(segment, cip_segment)
        # 0x28 = logical segment + member ID type + 8-bit format
        assert data == b"\x28\x05"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_member_id
        assert result.value == 0x05

    def test_class_id_16bit(self) -> None:
        """Test LogicalSegment with 16-bit class ID for values > 255."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x0102)
        data = encode(segment, cip_segment)
        # 0x21 = logical segment + class ID type + 16-bit format
        # Followed by pad byte (0x00) and 16-bit value (little-endian)
        assert data == b"\x21\x00\x02\x01"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_class_id
        assert result.value == 0x0102

    def test_instance_id_16bit(self) -> None:
        """Test LogicalSegment with 16-bit instance ID."""
        segment = LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x1234)
        data = encode(segment, cip_segment)
        # 0x25 = logical segment + instance ID type + 16-bit format
        assert data == b"\x25\x00\x34\x12"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_instance_id
        assert result.value == 0x1234

    def test_class_id_32bit(self) -> None:
        """Test LogicalSegment with 32-bit class ID for large values."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x12345678)
        data = encode(segment, cip_segment)
        # 0x22 = logical segment + class ID type + 32-bit format
        # Followed by pad byte (0x00) and 32-bit value (little-endian)
        assert data == b"\x22\x00\x78\x56\x34\x12"

        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_class_id
        assert result.value == 0x12345678

    def test_max_8bit_value(self) -> None:
        """Test LogicalSegment with maximum 8-bit value (255)."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0xFF)
        data = encode(segment, cip_segment)
        assert data == b"\x20\xff"

        result = decode(data, cip_segment)
        assert result.value == 0xFF

    def test_min_16bit_value(self) -> None:
        """Test LogicalSegment with minimum 16-bit value (256)."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x100)
        data = encode(segment, cip_segment)
        # Should use 16-bit format
        assert data == b"\x21\x00\x00\x01"

        result = decode(data, cip_segment)
        assert result.value == 0x100

    def test_zero_value(self) -> None:
        """Test LogicalSegment with zero value."""
        segment = LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0)
        data = encode(segment, cip_segment)
        assert data == b"\x24\x00"

        result = decode(data, cip_segment)
        assert result.value == 0


# ---------------------------------------------------------------------------
# PortSegment Tests
# ---------------------------------------------------------------------------


class TestPortSegment:
    """Tests for PortSegment encoding and decoding."""

    def test_basic_port_segment(self) -> None:
        """Test basic port segment with single byte link address."""
        segment = PortSegment(port=1, link_address=0)
        data = encode(segment, cip_segment)
        # Port 1 with link address 0
        assert data == b"\x01\x00"

        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.port == 1
        assert result.link_address == 0

    def test_port_with_link_address(self) -> None:
        """Test port segment with non-zero link address."""
        segment = PortSegment(port=1, link_address=2)
        data = encode(segment, cip_segment)
        assert data == b"\x01\x02"

        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.port == 1
        assert result.link_address == 2

    def test_port_backplane(self) -> None:
        """Test port segment for backplane (port 1, link 0)."""
        segment = PortSegment(port=1, link_address=0)
        data = encode(segment, cip_segment)
        assert data == b"\x01\x00"

        result = decode(data, cip_segment)
        assert result.port == 1
        assert result.link_address == 0

    def test_port_2_to_14(self) -> None:
        """Test port segments for ports 2-14 (fit in segment byte)."""
        for port_num in range(2, 15):
            segment = PortSegment(port=port_num, link_address=0)
            data = encode(segment, cip_segment)
            # Port number is in lower nibble
            assert data[0] == port_num

            result = decode(data, cip_segment)
            assert result.port == port_num

    def test_max_single_byte_link_address(self) -> None:
        """Test port segment with max single byte link address (255)."""
        segment = PortSegment(port=1, link_address=255)
        data = encode(segment, cip_segment)
        assert data == b"\x01\xff"

        result = decode(data, cip_segment)
        assert result.link_address == 255


# ---------------------------------------------------------------------------
# SymbolicSegment Tests
# ---------------------------------------------------------------------------


class TestSymbolicSegment:
    """Tests for SymbolicSegment encoding and decoding."""

    def test_short_symbol(self) -> None:
        """Test symbolic segment with short symbol name."""
        segment = SymbolicSegment(symbol=b"Tag1")
        data = encode(segment, cip_segment)
        # 0x91 = symbolic segment with length 4
        # Symbol is "Tag1" followed by no pad (even length)
        assert data[0] == 0x91
        assert data[1] == 4  # length
        assert data[2:6] == b"Tag1"

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == b"Tag1"

    def test_odd_length_symbol(self) -> None:
        """Test symbolic segment with odd-length symbol (requires padding)."""
        segment = SymbolicSegment(symbol=b"Tag")
        data = encode(segment, cip_segment)
        # Odd length symbol should have pad byte for word alignment
        assert data[0] == 0x91
        assert data[1] == 3  # length
        assert data[2:5] == b"Tag"
        # Packed format may or may not have padding depending on implementation

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == b"Tag"

    def test_program_scoped_tag(self) -> None:
        """Test symbolic segment with program-scoped tag name."""
        segment = SymbolicSegment(symbol=b"Program:MainProgram.LocalTag")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == b"Program:MainProgram.LocalTag"

    def test_single_char_symbol(self) -> None:
        """Test symbolic segment with single character."""
        segment = SymbolicSegment(symbol=b"A")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == b"A"

    def test_numeric_tag_name(self) -> None:
        """Test symbolic segment with numeric characters in name."""
        segment = SymbolicSegment(symbol=b"Tag123")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert result.symbol == b"Tag123"

    def test_underscore_in_tag(self) -> None:
        """Test symbolic segment with underscore in name."""
        segment = SymbolicSegment(symbol=b"My_Tag_Name")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert result.symbol == b"My_Tag_Name"


# ---------------------------------------------------------------------------
# NetworkSegment Tests
# ---------------------------------------------------------------------------


class TestNetworkSegment:
    """Tests for NetworkSegment encoding and decoding."""

    def test_scheduled_segment(self) -> None:
        """Test network segment with scheduled type (1 byte data per CIP spec)."""
        segment = NetworkSegment(
            type=NetworkSegmentType.scheduled,
            data=b"\x01",
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.scheduled
        assert result.data == b"\x01"

    def test_fixed_tag_segment(self) -> None:
        """Test network segment with fixed tag type (1 byte data per CIP spec)."""
        segment = NetworkSegment(
            type=NetworkSegmentType.fixed_tag,
            data=b"\x10",
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.fixed_tag
        assert result.data == b"\x10"

    def test_production_inhibit_time_segment(self) -> None:
        """Test network segment with production inhibit time (1 byte USINT per CIP spec)."""
        segment = NetworkSegment(
            type=NetworkSegmentType.production_inhibit_time,
            data=b"\x64",  # 100ms inhibit time
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.production_inhibit_time

    def test_safety_segment(self) -> None:
        """Test network segment with safety type (data array format)."""
        segment = NetworkSegment(
            type=NetworkSegmentType.safety,
            data=b"\x01\x02\x03\x04",
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.safety

    def test_extended_network_segment(self) -> None:
        """Test extended network segment (data array format)."""
        segment = NetworkSegment(
            type=NetworkSegmentType.extended,
            data=b"\x00\x01\x02\x03",
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.extended

    def test_network_segment_single_byte_data(self) -> None:
        """Test network segment with single byte data (required for non-array types)."""
        segment = NetworkSegment(
            type=NetworkSegmentType.scheduled,
            data=b"\x00",
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.data == b"\x00"

    def test_network_segment_roundtrip(self) -> None:
        """Test roundtrip encoding/decoding of network segment."""
        segment = NetworkSegment(
            type=NetworkSegmentType.production_inhibit_time,
            data=b"\xe8",  # 232 (0xE8) - single byte per CIP spec
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result == segment

    def test_network_segment_padded(self) -> None:
        """Test padded encoding of network segment."""
        segment = NetworkSegment(
            type=NetworkSegmentType.scheduled,
            data=b"\x01",
        )
        data = encode(segment, cip_segment_padded)
        # Padded format should align to word boundary
        assert len(data) % 2 == 0
        result = decode(data, cip_segment_padded)
        assert isinstance(result, NetworkSegment)


# ---------------------------------------------------------------------------
# CIPSegmentFmt Tests (Type Protocol)
# ---------------------------------------------------------------------------
class TestCIPSegmentFmt:
    def test_unknown_segment_type_raises(self) -> None:
        """CIPSegmentFmt should raise for unknown segment types."""
        data = b"\xe0\x00"  # Reserved type
        with pytest.raises(DecodeError, match="not a valid SegmentType"):
            decode(data, cip_segment)

    def test_padded_format(self) -> None:
        """CIPSegmentFmt with padded=True should use padded encoding."""
        fmt = cip_segment_padded
        assert fmt.padded is True

    def test_padded_logical_segment(self) -> None:
        """Test padded encoding of logical segment."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02)
        data = encode(segment, cip_segment_padded)
        # Padded format should align to word boundary
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert isinstance(result, LogicalSegment)
        assert result.value == 0x02

    def test_padded_port_segment(self) -> None:
        """Test padded encoding of port segment."""
        segment = PortSegment(port=1, link_address=5)
        data = encode(segment, cip_segment_padded)
        # Padded format should align to word boundary
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert isinstance(result, PortSegment)
        assert result.port == 1
        assert result.link_address == 5

    def test_padded_symbolic_segment_odd_length(self) -> None:
        """Test padded encoding of symbolic segment with odd-length name."""
        segment = SymbolicSegment(symbol=b"Tag")
        data = encode(segment, cip_segment_padded)
        # Padded format should have pad byte after odd-length symbol
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == b"Tag"

    def test_padded_symbolic_segment_even_length(self) -> None:
        """Test padded encoding of symbolic segment with even-length name."""
        segment = SymbolicSegment(symbol=b"Tag1")
        data = encode(segment, cip_segment_padded)
        # Even-length symbol should already be aligned
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert result.symbol == b"Tag1"


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestCIPErrorHandling:
    """Tests for error handling in CIP segment encoding/decoding."""

    def test_truncated_logical_segment(self) -> None:
        """Test decoding truncated logical segment raises error."""
        # Only segment byte, missing value
        data = b"\x20"
        with pytest.raises(DecodeError):
            decode(data, cip_segment)

    def test_truncated_16bit_logical_segment(self) -> None:
        """Test decoding truncated 16-bit logical segment raises error."""
        # 16-bit format but only 2 bytes instead of 4
        data = b"\x21\x00"
        with pytest.raises(DecodeError):
            decode(data, cip_segment)

    def test_truncated_port_segment(self) -> None:
        """Test decoding truncated port segment raises error."""
        # Only segment byte, missing link address
        data = b"\x01"
        with pytest.raises(DecodeError):
            decode(data, cip_segment)

    def test_truncated_symbolic_segment(self) -> None:
        """Test decoding truncated symbolic segment raises error."""
        # Symbolic segment header with length but no data
        data = b"\x91\x04"
        with pytest.raises(DecodeError):
            decode(data, cip_segment)

    def test_empty_data_raises(self) -> None:
        """Test decoding empty data raises error."""
        data = b""
        with pytest.raises(DecodeError):
            decode(data, cip_segment)


# ---------------------------------------------------------------------------
# EPathFmt Tests
# ---------------------------------------------------------------------------


class TestEPathFmt:
    """Tests for EPathFmt encoding and decoding."""

    def test_epath_with_length_prefix(self) -> None:
        """Test EPath with word count length prefix."""
        segments = [
            PortSegment(port=1, link_address=0),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=2),
        ]
        encoded = encode(segments, short_sized_padded_epath)

        # First byte is word count (4 bytes / 2 = 2 words)
        assert encoded[0] == 2
        assert encoded[1:] == b"\x01\x00\x20\x02"

        decoded = decode(encoded, short_sized_padded_epath)
        assert len(decoded) == 2

    def test_epath_with_padded_length(self) -> None:
        """Test EPath with padded length prefix."""
        segments = [PortSegment(port=1, link_address=0)]
        encoded = encode(segments, sized_padded_epath)

        # First byte is word count, second is pad
        assert encoded[0] == 1  # 2 bytes / 2 = 1 word
        assert encoded[1] == 0  # pad byte
        assert encoded[2:] == b"\x01\x00"

        decoded = decode(encoded, sized_padded_epath)
        assert len(decoded) == 1

    def test_empty_epath(self) -> None:
        """Test encoding/decoding empty EPath."""
        segments: list[PortSegment | LogicalSegment | SymbolicSegment] = []
        encoded = encode(segments, epath_packed)
        assert encoded == b""

        decoded = decode(encoded, epath_packed)
        assert len(decoded) == 0

    def test_epath_class_instance_only(self) -> None:
        """Test standard class/instance path (no port segment)."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        encoded = encode(segments, epath_packed)
        # Class 2, Instance 1
        assert encoded == b"\x20\x02\x24\x01"

        decoded = decode(encoded, epath_packed)
        assert len(decoded) == 2

    def test_epath_identity_object(self) -> None:
        """Test path to Identity Object (Class 1, Instance 1)."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        encoded = encode(segments, epath_packed)
        assert encoded == b"\x20\x01\x24\x01"

        decoded = decode(encoded, epath_packed)
        assert len(decoded) == 2

    def test_epath_message_router(self) -> None:
        """Test path to Message Router (Class 2, Instance 1)."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        encoded = encode(segments, epath_packed)

        decoded = decode(encoded, epath_packed)
        assert decoded[0].value == 0x02
        assert decoded[1].value == 0x01

    def test_epath_with_attribute(self) -> None:
        """Test path with class, instance, and attribute."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_attribute_id, value=0x01),
        ]
        encoded = encode(segments, epath_packed)
        # Class 1, Instance 1, Attribute 1
        assert encoded == b"\x20\x01\x24\x01\x30\x01"

        decoded = decode(encoded, epath_packed)
        assert len(decoded) == 3

    def test_epath_routed_path(self) -> None:
        """Test routed path through backplane to remote device."""
        segments = [
            PortSegment(port=1, link_address=2),  # Backplane, slot 2
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        encoded = encode(segments, epath_packed)

        decoded = decode(encoded, epath_packed)
        assert len(decoded) == 3
        assert isinstance(decoded[0], PortSegment)
        assert decoded[0].port == 1
        assert decoded[0].link_address == 2


# ---------------------------------------------------------------------------
# Roundtrip Tests
# ---------------------------------------------------------------------------


class TestCIPRoundtrips:
    """Integration tests for full encode/decode roundtrips."""

    def test_complex_path_roundtrip(self) -> None:
        """Test roundtrip of complex CIP path."""
        segments = [
            PortSegment(port=1, link_address=0),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_attribute_id, value=0x03),
        ]

        data = encode(segments, epath_packed)

        result = decode(data, epath_packed)

        assert len(result) == 4
        for orig, dec in zip(segments, result):
            assert type(orig) is type(dec)

    def test_symbolic_path_roundtrip(self) -> None:
        """Test roundtrip with symbolic segment."""
        segments = [
            SymbolicSegment(symbol=b"Program:MainProgram"),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=1),
        ]

        data = encode(segments, epath_packed)

        result = decode(data, epath_packed)
        assert len(result) == 2
        assert isinstance(result[0], SymbolicSegment)
        assert result[0].symbol == b"Program:MainProgram"

    def test_single_logical_segment_roundtrip(self) -> None:
        """Test roundtrip of single logical segment."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x64)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)

        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_class_id
        assert result.value == 0x64

    def test_single_port_segment_roundtrip(self) -> None:
        """Test roundtrip of single port segment."""
        segment = PortSegment(port=2, link_address=5)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)

        assert isinstance(result, PortSegment)
        assert result.port == 2
        assert result.link_address == 5

    def test_all_logical_types_roundtrip(self) -> None:
        """Test roundtrip with all logical segment types."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_member_id, value=0x03),
            LogicalSegment(type=LogicalSegmentType.type_connection_point, value=0x04),
            LogicalSegment(type=LogicalSegmentType.type_attribute_id, value=0x05),
        ]

        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 5
        for orig, dec in zip(segments, result):
            assert isinstance(dec, LogicalSegment)
            assert dec.type == orig.type
            assert dec.value == orig.value

    def test_large_values_roundtrip(self) -> None:
        """Test roundtrip with 16-bit and 32-bit values."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x1234),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0xABCD),
        ]

        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 2
        assert result[0].value == 0x1234
        assert result[1].value == 0xABCD

    def test_mixed_segment_types_roundtrip(self) -> None:
        """Test roundtrip with mixed port, logical, and symbolic segments."""
        segments = [
            PortSegment(port=1, link_address=3),
            SymbolicSegment(symbol=b"MyTag"),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=1),
        ]

        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 3
        assert isinstance(result[0], PortSegment)
        assert isinstance(result[1], SymbolicSegment)
        assert isinstance(result[2], LogicalSegment)

    def test_connection_manager_path(self) -> None:
        """Test typical Connection Manager path."""
        # Path to Connection Manager class
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x06),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]

        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert result[0].value == 0x06  # Connection Manager class
        assert result[1].value == 0x01

    def test_assembly_object_path(self) -> None:
        """Test path to Assembly Object."""
        # Assembly Object class ID is 0x04
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x04),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=100),
        ]

        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert result[0].value == 0x04
        assert result[1].value == 100


class TestBuiltinRoundtrips:
    """Tests for encoding/decoding CIP types via builtin conversion."""

    def test_port_segment(self) -> None:
        """Test encoding/decoding CIPSegment via builtin conversion."""
        segment = PortSegment(port=1, link_address=2)

        # Convert to builtins
        builtins = _to_builtins(segment, recursive=False)
        assert isinstance(builtins, dict)
        assert builtins["segment_type"] == 0
        assert builtins["port"] == 1
        assert builtins["link_address"] == 2

        data = encode(segment, cip_segment)
        assert data == b"\x01\x02"
        result = decode(data, cip_segment)
        assert result == segment

        # Convert back to CIPSegment
        converted = _convert(builtins, PortSegment, recursive=False)
        assert isinstance(converted, PortSegment)
        assert converted.port == 1
        assert converted.link_address == 2


# ---------------------------------------------------------------------------
# Extended Symbolic Segment Tests
# ---------------------------------------------------------------------------


class TestExtendedSymbolicSegment:
    """Tests for extended symbolic segment formats."""

    def test_extended_symbol_double_byte(self) -> None:
        """Test symbolic segment with double-byte extended format (length > 31)."""
        # Symbol longer than 31 characters requires extended format
        long_symbol = b"VeryLongTagNameThatExceeds31Chars"
        segment = SymbolicSegment(symbol=long_symbol)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == long_symbol

    def test_extended_symbol_max_short_length(self) -> None:
        """Test symbolic segment with maximum short format length (31 chars)."""
        symbol_31 = b"A" * 31
        segment = SymbolicSegment(symbol=symbol_31)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.symbol == symbol_31

    def test_extended_symbol_min_extended_length(self) -> None:
        """Test symbolic segment with minimum extended format length (32 chars)."""
        symbol_32 = b"B" * 32
        segment = SymbolicSegment(symbol=symbol_32)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.symbol == symbol_32

    def test_extended_symbol_very_long(self) -> None:
        """Test symbolic segment with very long name."""
        long_symbol = b"Program:MainProgram.VeryLongStructureName.NestedMember.DeepValue"
        segment = SymbolicSegment(symbol=long_symbol)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.symbol == long_symbol

    def test_symbolic_segment_extended_format_enum(self) -> None:
        """Test that SymbolicSegmentExtendedFormat enum has expected values."""
        # Verify enum exists and has typical CIP extended format values
        assert hasattr(SymbolicSegmentExtendedFormat, "double_byte_chars")
        assert hasattr(SymbolicSegmentExtendedFormat, "triple_byte_chars")


# ---------------------------------------------------------------------------
# EPath Padded Tests
# ---------------------------------------------------------------------------


class TestEPathPadded:
    """Tests for padded EPath encoding and decoding."""

    def test_epath_padded_single_segment(self) -> None:
        """Test padded EPath with single segment."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
        ]
        encoded = encode(segments, epath_padded)
        # Padded format should have even byte count
        assert len(encoded) % 2 == 0
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 1
        assert decoded[0].value == 0x02

    def test_epath_padded_multiple_segments(self) -> None:
        """Test padded EPath with multiple segments."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        encoded = encode(segments, epath_padded)
        assert len(encoded) % 2 == 0
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 2

    def test_epath_padded_with_port(self) -> None:
        """Test padded EPath with port segment."""
        segments = [
            PortSegment(port=1, link_address=2),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x04),
        ]
        encoded = encode(segments, epath_padded)
        assert len(encoded) % 2 == 0
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 2
        assert isinstance(decoded[0], PortSegment)

    def test_epath_padded_with_symbolic(self) -> None:
        """Test padded EPath with symbolic segment (odd length name)."""
        segments = [
            SymbolicSegment(symbol=b"Tag"),  # 3 bytes - odd length
        ]
        encoded = encode(segments, epath_padded)
        assert len(encoded) % 2 == 0
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 1
        assert decoded[0].symbol == b"Tag"

    def test_epath_padded_mixed_segments(self) -> None:
        """Test padded EPath with mixed segment types."""
        segments = [
            PortSegment(port=1, link_address=0),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            SymbolicSegment(symbol=b"MyTag"),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        encoded = encode(segments, epath_padded)
        assert len(encoded) % 2 == 0
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 4

    def test_epath_padded_empty(self) -> None:
        """Test encoding/decoding empty padded EPath."""
        segments: list[LogicalSegment] = []
        encoded = encode(segments, epath_padded)
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 0

    def test_epath_padded_with_network_segment(self) -> None:
        """Test padded EPath with network segment."""
        segments = [
            NetworkSegment(
                type=NetworkSegmentType.production_inhibit_time,
                data=b"\x64",  # Single byte per CIP spec
            ),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
        ]
        encoded = encode(segments, epath_padded)
        assert len(encoded) % 2 == 0
        decoded = decode(encoded, epath_padded)
        assert len(decoded) == 2
        assert isinstance(decoded[0], NetworkSegment)


# ---------------------------------------------------------------------------
# Extended Port Segment Tests
# ---------------------------------------------------------------------------


class TestExtendedPortSegment:
    """Tests for extended port segments (port number > 15)."""

    def test_extended_port_number(self) -> None:
        """Test port segment with extended port number (> 15)."""
        segment = PortSegment(port=16, link_address=0)
        data = encode(segment, cip_segment)
        # Extended port format uses 0x0F in lower nibble with extended port byte
        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.port == 16
        assert result.link_address == 0

    def test_extended_port_with_link_address(self) -> None:
        """Test extended port segment with link address."""
        segment = PortSegment(port=20, link_address=5)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.port == 20
        assert result.link_address == 5

    def test_extended_port_max_value(self) -> None:
        """Test port segment with maximum port number."""
        segment = PortSegment(port=0xFFFF, link_address=0)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.port == 0xFFFF

    def test_port_boundary_14(self) -> None:
        """Test port segment at boundary (port 14 - fits in nibble)."""
        segment = PortSegment(port=14, link_address=0)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.port == 14

    def test_port_boundary_15(self) -> None:
        """Test port segment at boundary (port 15 - reserved)."""
        # Port 15 (0x0F) is the extended indicator, actual port follows
        segment = PortSegment(port=15, link_address=0)
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.port == 15


# ---------------------------------------------------------------------------
# Logical Segment Type Special Cases Tests
# ---------------------------------------------------------------------------


class TestLogicalSegmentSpecialCases:
    """Tests for special cases in logical segments."""

    def test_service_id_segment(self) -> None:
        """Test logical segment for service ID (special use)."""
        segment = LogicalSegment(
            type=LogicalSegmentType.type_service_id,
            value=0x01,
        )
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result.type == LogicalSegmentType.type_service_id


# ---------------------------------------------------------------------------
# CIP Segment Type Values Tests
# ---------------------------------------------------------------------------


class TestCIPSegmentTypeValues:
    """Tests verifying CIP segment type enum values and formats."""

    def test_logical_segment_type_class_id_value(self) -> None:
        """Verify class ID logical segment type enum value."""
        assert LogicalSegmentType.type_class_id.value == 0

    def test_logical_segment_type_instance_id_value(self) -> None:
        """Verify instance ID logical segment type enum value."""
        assert LogicalSegmentType.type_instance_id.value == 1

    def test_logical_segment_type_member_id_value(self) -> None:
        """Verify member ID logical segment type enum value."""
        assert LogicalSegmentType.type_member_id.value == 2

    def test_logical_segment_type_connection_point_value(self) -> None:
        """Verify connection point logical segment type enum value."""
        assert LogicalSegmentType.type_connection_point.value == 3

    def test_logical_segment_type_attribute_id_value(self) -> None:
        """Verify attribute ID logical segment type enum value."""
        assert LogicalSegmentType.type_attribute_id.value == 4

    def test_network_segment_type_scheduled_value(self) -> None:
        """Verify scheduled network segment type enum value."""
        assert NetworkSegmentType.scheduled.value == 1

    def test_network_segment_type_fixed_tag_value(self) -> None:
        """Verify fixed tag network segment type enum value."""
        assert NetworkSegmentType.fixed_tag.value == 2

    def test_network_segment_type_production_inhibit_time_value(self) -> None:
        """Verify production inhibit time network segment type enum value."""
        assert NetworkSegmentType.production_inhibit_time.value == 3

    def test_network_segment_type_safety_value(self) -> None:
        """Verify safety network segment type enum value (bit 4 set for data array format)."""
        assert NetworkSegmentType.safety.value == 0x10  # 16

    def test_network_segment_type_extended_value(self) -> None:
        """Verify extended network segment type enum value."""
        assert NetworkSegmentType.extended.value == 0x1F


# ---------------------------------------------------------------------------
# Real-World CIP Path Tests
# ---------------------------------------------------------------------------


class TestRealWorldCIPPaths:
    """Tests based on real-world CIP path examples from industrial protocols."""

    def test_plc_tag_read_path(self) -> None:
        """Test typical PLC tag read path (symbolic + element)."""
        segments = [
            SymbolicSegment(symbol=b"MyDINT"),
            LogicalSegment(type=LogicalSegmentType.type_member_id, value=0),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert len(result) == 2
        assert result[0].symbol == b"MyDINT"

    def test_array_element_path(self) -> None:
        """Test path to array element."""
        segments = [
            SymbolicSegment(symbol=b"MyArray"),
            LogicalSegment(type=LogicalSegmentType.type_member_id, value=5),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert result[1].value == 5

    def test_forward_open_path(self) -> None:
        """Test typical Forward Open request path."""
        # Route through backplane to Module in slot 2
        segments = [
            PortSegment(port=1, link_address=2),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert len(result) == 3

    def test_ethernet_ip_path(self) -> None:
        """Test EtherNet/IP specific path."""
        # TCP/IP Interface Object path
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0xF5),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert result[0].value == 0xF5

    def test_io_connection_path(self) -> None:
        """Test I/O connection path with connection points."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x04),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=100),
            LogicalSegment(type=LogicalSegmentType.type_connection_point, value=0x64),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert len(result) == 3
        assert result[2].type == LogicalSegmentType.type_connection_point

    def test_get_attribute_single_path(self) -> None:
        """Test Get_Attribute_Single service path."""
        # Identity Object, Instance 1, Serial Number attribute
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            LogicalSegment(type=LogicalSegmentType.type_attribute_id, value=0x06),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert result[2].value == 0x06  # Serial Number attribute

    def test_multi_hop_route(self) -> None:
        """Test multi-hop route through multiple ports."""
        segments = [
            PortSegment(port=1, link_address=2),  # Backplane to slot 2
            PortSegment(port=2, link_address=0),  # EtherNet/IP port
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)
        assert len(result) == 4
        assert isinstance(result[0], PortSegment)
        assert isinstance(result[1], PortSegment)


# ---------------------------------------------------------------------------
# DataSegment Tests
# ---------------------------------------------------------------------------


class TestDataSegment:
    """Tests for DataSegment encoding and decoding."""

    def test_simple_data_segment(self) -> None:
        """Test DataSegment with simple data type (0x80)."""
        segment = DataSegment(type=DataSegmentType.simple, data=b"\x01\x02\x03\x04")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, DataSegment)
        assert result.type == DataSegmentType.simple
        assert result.data == b"\x01\x02\x03\x04"

    def test_simple_data_segment_single_byte(self) -> None:
        """Test DataSegment with single byte of data.

        Note: CIP data segments use word counts, so single bytes are padded
        to word boundary and decoded as 2 bytes.
        """
        segment = DataSegment(type=DataSegmentType.simple, data=b"\xff")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, DataSegment)
        # Word-aligned: single byte becomes 2 bytes with padding
        assert result.data == b"\xff\x00"

    def test_simple_data_segment_empty(self) -> None:
        """Test DataSegment with empty data."""
        segment = DataSegment(type=DataSegmentType.simple, data=b"")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, DataSegment)
        assert result.data == b""

    def test_simple_data_segment_large(self) -> None:
        """Test DataSegment with larger data payload."""
        payload = bytes(range(256))
        segment = DataSegment(type=DataSegmentType.simple, data=payload)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, DataSegment)
        assert result.data == payload

    def test_data_segment_roundtrip(self) -> None:
        """Test roundtrip encoding/decoding of data segment."""
        segment = DataSegment(type=DataSegmentType.simple, data=b"\xde\xad\xbe\xef")
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result == segment

    def test_data_segment_padded(self) -> None:
        """Test padded encoding of data segment.

        Note: CIP data segments use word counts, so odd-length data is
        padded to word boundary.
        """
        segment = DataSegment(type=DataSegmentType.simple, data=b"\x01\x02\x03")
        data = encode(segment, cip_segment_padded)
        # Padded format should align to word boundary
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert isinstance(result, DataSegment)
        # Word-aligned: 3 bytes becomes 4 bytes with padding
        assert result.data == b"\x01\x02\x03\x00"

    def test_data_segment_in_epath(self) -> None:
        """Test DataSegment as part of an EPath."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            DataSegment(type=DataSegmentType.simple, data=b"\x10\x20"),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 3
        assert isinstance(result[2], DataSegment)
        assert result[2].data == b"\x10\x20"

    def test_data_segment_word_aligned_data(self) -> None:
        """Test DataSegment with word-aligned data (even number of bytes)."""
        segment = DataSegment(type=DataSegmentType.simple, data=b"\x01\x02\x03\x04\x05\x06")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, DataSegment)
        assert result.data == b"\x01\x02\x03\x04\x05\x06"


# ---------------------------------------------------------------------------
# ElementaryDataTypeSegment Tests
# ---------------------------------------------------------------------------


class TestElementaryDataTypeSegment:
    """Tests for ElementaryDataTypeSegment encoding and decoding."""

    def test_bool_type(self) -> None:
        """Test ElementaryDataTypeSegment with BOOL type (0xC1)."""
        segment = ElementaryDataTypeSegment(type_code=0xC1)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert result == segment
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC1

    def test_sint_type(self) -> None:
        """Test ElementaryDataTypeSegment with SINT type (0xC2)."""
        segment = ElementaryDataTypeSegment(type_code=0xC2)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert result == segment
        assert result.type_code == 0xC2

    def test_int_type(self) -> None:
        """Test ElementaryDataTypeSegment with INT type (0xC3)."""
        segment = ElementaryDataTypeSegment(type_code=0xC3)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC3

    def test_dint_type(self) -> None:
        """Test ElementaryDataTypeSegment with DINT type (0xC4)."""
        segment = ElementaryDataTypeSegment(type_code=0xC4)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC4

    def test_lint_type(self) -> None:
        """Test ElementaryDataTypeSegment with LINT type (0xC5)."""
        segment = ElementaryDataTypeSegment(type_code=0xC5)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC5

    def test_usint_type(self) -> None:
        """Test ElementaryDataTypeSegment with USINT type (0xC6)."""
        segment = ElementaryDataTypeSegment(type_code=0xC6)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC6

    def test_uint_type(self) -> None:
        """Test ElementaryDataTypeSegment with UINT type (0xC7)."""
        segment = ElementaryDataTypeSegment(type_code=0xC7)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC7

    def test_udint_type(self) -> None:
        """Test ElementaryDataTypeSegment with UDINT type (0xC8)."""
        segment = ElementaryDataTypeSegment(type_code=0xC8)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC8

    def test_ulint_type(self) -> None:
        """Test ElementaryDataTypeSegment with ULINT type (0xC9)."""
        segment = ElementaryDataTypeSegment(type_code=0xC9)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC9

    def test_real_type(self) -> None:
        """Test ElementaryDataTypeSegment with REAL type (0xCA)."""
        segment = ElementaryDataTypeSegment(type_code=0xCA)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xCA

    def test_lreal_type(self) -> None:
        """Test ElementaryDataTypeSegment with LREAL type (0xCB)."""
        segment = ElementaryDataTypeSegment(type_code=0xCB)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xCB

    def test_string_type(self) -> None:
        """Test ElementaryDataTypeSegment with STRING type (0xD0)."""
        segment = ElementaryDataTypeSegment(type_code=0xD0)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xD0

    def test_byte_type(self) -> None:
        """Test ElementaryDataTypeSegment with BYTE type (0xD1)."""
        segment = ElementaryDataTypeSegment(type_code=0xD1)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xD1

    def test_word_type(self) -> None:
        """Test ElementaryDataTypeSegment with WORD type (0xD2)."""
        segment = ElementaryDataTypeSegment(type_code=0xD2)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xD2

    def test_dword_type(self) -> None:
        """Test ElementaryDataTypeSegment with DWORD type (0xD3)."""
        segment = ElementaryDataTypeSegment(type_code=0xD3)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xD3

    def test_lword_type(self) -> None:
        """Test ElementaryDataTypeSegment with LWORD type (0xD4)."""
        segment = ElementaryDataTypeSegment(type_code=0xD4)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xD4

    def test_elementary_type_roundtrip(self) -> None:
        """Test roundtrip encoding/decoding of elementary data type segment."""
        segment = ElementaryDataTypeSegment(type_code=0xC4)  # DINT
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result == segment

    def test_elementary_type_padded(self) -> None:
        """Test padded encoding of elementary data type segment."""
        segment = ElementaryDataTypeSegment(type_code=0xC3)  # INT
        data = encode(segment, cip_segment_padded)
        # Padded format should align to word boundary
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert isinstance(result, ElementaryDataTypeSegment)
        assert result.type_code == 0xC3

    def test_elementary_type_in_epath(self) -> None:
        """Test ElementaryDataTypeSegment as part of an EPath."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            ElementaryDataTypeSegment(type_code=0xC4),  # DINT
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 2
        assert isinstance(result[1], ElementaryDataTypeSegment)
        assert result[1].type_code == 0xC4


# ---------------------------------------------------------------------------
# ConstructedDataTypeSegment Tests
# ---------------------------------------------------------------------------


class TestConstructedDataTypeSegment:
    """Tests for ConstructedDataTypeSegment encoding and decoding."""

    def test_array_type(self) -> None:
        """Test ConstructedDataTypeSegment with array type (0xA0)."""
        segment = ConstructedDataTypeSegment(type_code=0xA0, data=b"\x03\x00")  # 3 dimensions
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ConstructedDataTypeSegment)
        assert result.type_code == 0xA0
        assert result.data == b"\x03\x00"

    def test_structure_type(self) -> None:
        """Test ConstructedDataTypeSegment with structure type (0xA2)."""
        segment = ConstructedDataTypeSegment(
            type_code=0xA2, data=b"\x01\x02\x03\x04"
        )  # Structure handle
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ConstructedDataTypeSegment)
        assert result.type_code == 0xA2
        assert result.data == b"\x01\x02\x03\x04"

    def test_abbreviated_array_type(self) -> None:
        """Test ConstructedDataTypeSegment with abbreviated array type."""
        segment = ConstructedDataTypeSegment(type_code=0xA1, data=b"\x64\x00")  # Array[100]
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert result == segment
        assert isinstance(result, ConstructedDataTypeSegment)
        assert result.type_code == 0xA1

    def test_constructed_type_with_empty_data(self) -> None:
        """Test ConstructedDataTypeSegment with no additional data."""
        segment = ConstructedDataTypeSegment(type_code=0xA0, data=b"")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert result == segment
        assert isinstance(result, ConstructedDataTypeSegment)
        assert result.data == b""

    def test_constructed_type_roundtrip(self) -> None:
        """Test roundtrip encoding/decoding of constructed data type segment."""
        segment = ConstructedDataTypeSegment(type_code=0xA2, data=b"\xde\xad\xbe\xef")
        data = encode(segment, cip_segment)
        result = decode(data, cip_segment)
        assert result == segment

    def test_constructed_type_padded(self) -> None:
        """Test padded encoding of constructed data type segment."""
        segment = ConstructedDataTypeSegment(type_code=0xA0, data=b"\x01\x02\x03")
        data = encode(segment, cip_segment_padded)
        # Padded format should align to word boundary
        assert len(data) % 2 == 0

        result = decode(data, cip_segment_padded)
        assert isinstance(result, ConstructedDataTypeSegment)

    def test_constructed_type_in_epath(self) -> None:
        """Test ConstructedDataTypeSegment as part of an EPath."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            ConstructedDataTypeSegment(type_code=0xA2, data=b"\x01\x02"),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 2
        assert isinstance(result[1], ConstructedDataTypeSegment)

    def test_array_with_element_type(self) -> None:
        """Test array constructed type with element type information."""
        # Array of DINT (0xC4) with 10 elements
        segment = ConstructedDataTypeSegment(type_code=0xA0, data=b"\xc4\x0a\x00\x00\x00")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ConstructedDataTypeSegment)
        assert result.type_code == 0xA0

    def test_nested_structure_type(self) -> None:
        """Test ConstructedDataTypeSegment representing nested structure."""
        # Structure with nested type reference
        segment = ConstructedDataTypeSegment(type_code=0xA2, data=b"\x10\x00\x02\x00\x04\x00")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, ConstructedDataTypeSegment)
        assert result.type_code == 0xA2


# ---------------------------------------------------------------------------
# Mixed Data Segment EPath Tests
# ---------------------------------------------------------------------------


class TestMixedDataSegmentEPath:
    """Tests for EPaths containing mixed segment types including data segments."""

    def test_epath_with_data_and_logical_segments(self) -> None:
        """Test EPath with logical segments followed by data segment."""
        segments = [
            PortSegment(port=1, link_address=0),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            DataSegment(type=DataSegmentType.simple, data=b"\x10\x20\x30\x40"),
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 4
        assert isinstance(result[3], DataSegment)
        assert result[3].data == b"\x10\x20\x30\x40"

    def test_epath_with_elementary_type_info(self) -> None:
        """Test EPath with type information for tag read response."""
        segments = [
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            ElementaryDataTypeSegment(type_code=0xC4),  # DINT type
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 3
        assert isinstance(result[2], ElementaryDataTypeSegment)

    def test_epath_with_constructed_type_and_symbolic(self) -> None:
        """Test EPath with symbolic segment and constructed type."""
        segments = [
            SymbolicSegment(symbol=b"MyArray"),
            ConstructedDataTypeSegment(type_code=0xA0, data=b"\xc4\x64\x00"),  # Array[100] of DINT
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 2
        assert isinstance(result[0], SymbolicSegment)
        assert isinstance(result[1], ConstructedDataTypeSegment)

    def test_complex_type_path(self) -> None:
        """Test complex path with multiple segment types."""
        segments = [
            PortSegment(port=1, link_address=2),
            LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x02),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=0x01),
            ElementaryDataTypeSegment(type_code=0xCA),  # REAL type
            DataSegment(type=DataSegmentType.simple, data=b"\x00\x00\x80\x3f"),  # 1.0f
        ]
        data = encode(segments, epath_packed)
        result = decode(data, epath_packed)

        assert len(result) == 5
        assert isinstance(result[3], ElementaryDataTypeSegment)
        assert isinstance(result[4], DataSegment)


# ---------------------------------------------------------------------------
# Additional Coverage Tests
# ---------------------------------------------------------------------------


class TestPortSegmentExtendedLink:
    """Tests for port segment extended link address encoding/decoding."""

    def test_extended_link_address_16bit(self) -> None:
        """Test port segment with 16-bit link address (requires ext_link)."""
        segment = PortSegment(port=1, link_address=0x1234)
        data = encode(segment, cip_segment)
        # Should have ext_link flag set (bit 4)
        assert data[0] & 0x10  # ext_link bit

        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.port == 1
        assert result.link_address == b"\x34\x12"

    def test_extended_link_address_bytes(self) -> None:
        """Test port segment with bytes link address."""
        segment = PortSegment(port=2, link_address=b"\x01\x02\x03")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.port == 2
        assert result.link_address == b"\x01\x02\x03"

    def test_extended_link_address_even_bytes(self) -> None:
        """Test port segment with even-length bytes link address (no padding)."""
        segment = PortSegment(port=1, link_address=b"\xaa\xbb")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.link_address == b"\xaa\xbb"

    def test_extended_link_address_odd_bytes(self) -> None:
        """Test port segment with odd-length bytes link address (with padding)."""
        segment = PortSegment(port=1, link_address=b"\xaa\xbb\xcc")
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, PortSegment)
        assert result.link_address == b"\xaa\xbb\xcc"

    def test_extended_link_zero_size_error(self) -> None:
        """Test decoding port segment with zero ext_link size raises error."""
        # Craft invalid data: ext_link flag set but size is 0
        # Header: 0x11 = port 1 + ext_link flag (bit 4)
        # Size: 0x00 = invalid zero size
        data = b"\x11\x00"
        with pytest.raises(DecodeError, match="Extended link address size is 0"):
            decode(data, cip_segment)


class TestLogicalSegmentErrors:
    """Tests for error handling in logical segment encoding."""

    def test_special_type_encode_error(self) -> None:
        """Test encoding logical segment with special type raises error."""
        segment = LogicalSegment(type=LogicalSegmentType.type_special, value=0x01)
        with pytest.raises(EncodeError, match="Special type are not supported"):
            encode(segment, cip_segment)

    def test_service_id_multi_byte_error(self) -> None:
        """Test encoding service ID with value > 255 raises error."""
        segment = LogicalSegment(type=LogicalSegmentType.type_service_id, value=0x1234)
        with pytest.raises(EncodeError, match="Invalid logical value for Service ID"):
            encode(segment, cip_segment)

    def test_value_too_large_error(self) -> None:
        """Test encoding logical segment with value > 32 bits raises error."""
        segment = LogicalSegment(type=LogicalSegmentType.type_class_id, value=0x1_0000_0000)
        with pytest.raises(EncodeError, match="Value too large"):
            encode(segment, cip_segment)

    def test_value_3_bytes_error(self) -> None:
        """Test encoding logical segment with 3-byte value raises error."""
        # 3 bytes doesn't match 1, 2, or 4 byte formats in LOGICAL_FORMAT_SIZE_MAP

        stream = BytesIO()
        with pytest.raises(ValueError, match="logical value too large"):
            LogicalSegment.encode(
                {
                    "segment_type": 1,
                    "type": 0,  # class_id
                    "value": b"\x01\x02\x03",  # 3 bytes - invalid size
                },
                stream,
                False,
            )


class TestLogicalSegmentSpecialDecode:
    """Tests for decoding logical segment with special type (electronic key)."""

    def test_special_type_decode_electronic_key(self) -> None:
        """Test decoding logical segment with special type reads 6 bytes."""
        # Header bits: segment_type (5-7) = 0b001 (logical)
        #              logical_type (2-4) = 0b101 (special)
        #              format (0-1) = 0b00
        # Header: 0x34 = 0b00110100 = (0b001 << 5) | (0b101 << 2) | 0b00
        # Electronic key is 6 bytes
        data = b"\x34\x01\x02\x03\x04\x05\x06"
        result = decode(data, cip_segment)
        assert isinstance(result, LogicalSegment)
        assert result.type == LogicalSegmentType.type_special
        assert result.value == b"\x01\x02\x03\x04\x05\x06"


class TestSymbolicSegmentNumeric:
    """Tests for symbolic segment with numeric symbols."""

    def test_numeric_symbol_8bit(self) -> None:
        """Test symbolic segment with 8-bit numeric symbol."""
        segment = SymbolicSegment(symbol=0x42)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == 0x42

    def test_numeric_symbol_16bit(self) -> None:
        """Test symbolic segment with 16-bit numeric symbol."""
        segment = SymbolicSegment(symbol=0x1234)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == 0x1234

    def test_numeric_symbol_32bit(self) -> None:
        """Test symbolic segment with 32-bit numeric symbol."""
        segment = SymbolicSegment(symbol=0x12345678)
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == 0x12345678


class TestSymbolicSegmentExtendedFormats:
    """Tests for symbolic segment with extended character formats."""

    def test_double_byte_chars_encode_decode(self) -> None:
        """Test symbolic segment with double-byte characters."""
        # 4 characters in double-byte format = 8 bytes
        symbol_bytes = b"\x00A\x00B\x00C\x00D"
        segment = SymbolicSegment(
            symbol=symbol_bytes,
            ext_type=SymbolicSegmentExtendedFormat.double_byte_chars,
        )
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == symbol_bytes
        assert result.ext_type is not None

    def test_triple_byte_chars_encode_decode(self) -> None:
        """Test symbolic segment with triple-byte characters."""
        # 2 characters in triple-byte format = 6 bytes
        symbol_bytes = b"AB\x00CD\x00"
        segment = SymbolicSegment(
            symbol=symbol_bytes,
            ext_type=SymbolicSegmentExtendedFormat.triple_byte_chars,
        )
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == symbol_bytes

    def test_double_byte_invalid_length_error(self) -> None:
        """Test that double-byte char format with non-multiple length raises error."""
        # 5 bytes is not a multiple of 2
        segment = SymbolicSegment(
            symbol=b"\x00\x01\x02\x03\x04",
            ext_type=SymbolicSegmentExtendedFormat.double_byte_chars,
        )
        with pytest.raises(EncodeError, match="not a multiple"):
            encode(segment, cip_segment)

    def test_triple_byte_invalid_length_error(self) -> None:
        """Test that triple-byte char format with non-multiple length raises error."""
        # 4 bytes is not a multiple of 3
        segment = SymbolicSegment(
            symbol=b"\x00\x01\x02\x03",
            ext_type=SymbolicSegmentExtendedFormat.triple_byte_chars,
        )
        with pytest.raises(EncodeError, match="not a multiple"):
            encode(segment, cip_segment)

    def test_bytes_with_numeric_ext_type(self) -> None:
        """Test symbolic segment with bytes data and numeric extended format.

        This covers the case where ext_type is set but not a char-size format,
        so ext_type_val is used directly.
        """

        # Use numeric_symbol_usint format directly with bytes
        stream = BytesIO()
        # This exercises the `else: ext_type_val = ext_type` branch
        SymbolicSegment.encode(
            {
                "symbol": b"\x42",
                "ext_type": SymbolicSegmentExtendedFormat.numeric_symbol_usint,
            },
            stream,
            False,
        )
        # Verify something was written
        assert stream.tell() > 0

    def test_unsupported_symbol_type_error(self) -> None:
        """Test that unsupported symbol type raises error."""
        # Manually create a value dict with unsupported type

        stream = BytesIO()
        with pytest.raises(TypeError, match="Unsupported symbol type"):
            SymbolicSegment.encode({"symbol": 3.14, "ext_type": None}, stream, False)


class TestSymbolicSegmentShortAscii:
    """Tests for symbolic segment with short ASCII format (symbol_size > 0 in header)."""

    def test_short_ascii_decode(self) -> None:
        """Test decoding symbolic segment with short ASCII format.

        When symbol_size is set in the header (bits 0-4), it uses the short
        ASCII format instead of ANSI Extended Symbol (0x91).
        """
        # Header: 0x64 = symbolic segment type (0b011 in bits 5-7) + size 4 (bits 0-4)
        # 0x64 = 0b01100100 = segment_type=3, symbol_size=4
        data = b"\x64Test"
        result = decode(data, cip_segment)
        assert isinstance(result, SymbolicSegment)
        assert result.symbol == b"Test"


class TestSymbolicSegmentUnsupportedFormat:
    """Tests for error handling with unsupported symbolic segment formats."""

    def test_unsupported_extended_format_error(self) -> None:
        """Test that unsupported extended format raises TypeError."""
        # Create data with extended format but unknown format type
        # Header: 0x60 = symbolic segment type (0b011) + symbol_size=0 (extended)
        # ext_type: 0x80 = unknown format (0b100_00000 with some size)
        data = b"\x60\x80"
        with pytest.raises(DecodeError, match="unsupported extended string format"):
            decode(data, cip_segment)


class TestNetworkSegmentExtended:
    """Tests for network segment with extended type data length adjustment."""

    def test_extended_network_segment_encode_decode(self) -> None:
        """Test extended network segment with proper data_len adjustment."""
        # Extended type has data_len -= 2 on encode and += 2 on decode
        segment = NetworkSegment(
            type=NetworkSegmentType.extended,
            data=b"\x00\x01\x02\x03\x04\x05",  # 6 bytes, writes as 4
        )
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.extended
        assert result.data == b"\x00\x01\x02\x03\x04\x05"

    def test_safety_network_segment_multi_byte(self) -> None:
        """Test safety network segment with multi-byte data array."""
        segment = NetworkSegment(
            type=NetworkSegmentType.safety,
            data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        )
        data = encode(segment, cip_segment)

        result = decode(data, cip_segment)
        assert isinstance(result, NetworkSegment)
        assert result.type == NetworkSegmentType.safety
        assert result.data == b"\x01\x02\x03\x04\x05\x06\x07\x08"


class TestNetworkSegmentValidation:
    """Tests for network segment validation."""

    def test_non_array_type_wrong_data_length_error(self) -> None:
        """Test that non-array network segment type with wrong data length raises error."""
        with pytest.raises(ValueError, match="requires exactly one byte"):
            NetworkSegment(
                type=NetworkSegmentType.scheduled,
                data=b"\x01\x02",  # 2 bytes, but scheduled requires exactly 1
            )
