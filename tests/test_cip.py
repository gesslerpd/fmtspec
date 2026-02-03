"""Tests for CIP (Common Industrial Protocol) types."""

import pytest

from fmtspec import DecodeError, decode, encode
from fmtspec._core import _convert, _to_builtins
from fmtspec.types import (
    # Segment value classes
    CIPSegmentFmt,
    LogicalSegment,
    LogicalSegmentType,
    PortSegment,
    # Enums
    SegmentType,
    SymbolicSegment,
    cip_segment,
    epath_packed,
    epath_padded_len,
    epath_padded_pad_len,
    # CIP integer type aliases
    udint,
    uint,
    ulint,
    usint,
)

# ---------------------------------------------------------------------------
# CIP Integer Aliases
# ---------------------------------------------------------------------------


class TestCIPIntegerAliases:
    """Test that CIP integer aliases map to correct fmtspec types."""

    def test_usint_is_u8le(self) -> None:
        assert usint.size == 1
        assert usint.byteorder == "little"
        assert usint.signed is False

    def test_uint_is_u16le(self) -> None:
        assert uint.size == 2
        assert uint.byteorder == "little"
        assert uint.signed is False

    def test_udint_is_u32le(self) -> None:
        assert udint.size == 4
        assert udint.byteorder == "little"
        assert udint.signed is False

    def test_ulint_is_u64le(self) -> None:
        assert ulint.size == 8
        assert ulint.byteorder == "little"
        assert ulint.signed is False

    def test_usint_encode_decode(self) -> None:
        data = encode(0x42, usint)
        assert data == b"\x42"
        assert decode(data, usint) == 0x42

    def test_uint_encode_decode(self) -> None:
        data = encode(0x1234, uint)
        # Little-endian: LSB first
        assert data == b"\x34\x12"
        assert decode(data, uint) == 0x1234


# ---------------------------------------------------------------------------
# LogicalSegment Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NetworkSegment Tests
# ---------------------------------------------------------------------------


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
        fmt = CIPSegmentFmt(padded=True)
        assert fmt.padded is True


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
        encoded = encode(segments, epath_padded_len)

        # First byte is word count (4 bytes / 2 = 2 words)
        assert encoded[0] == 2
        assert encoded[1:] == b"\x01\x00\x20\x02"

        decoded = decode(encoded, epath_padded_len)
        assert len(decoded) == 2

    def test_epath_with_padded_length(self) -> None:
        """Test EPath with padded length prefix."""
        segments = [PortSegment(port=1, link_address=0)]
        encoded = encode(segments, epath_padded_pad_len)

        # First byte is word count, second is pad
        assert encoded[0] == 1  # 2 bytes / 2 = 1 word
        assert encoded[1] == 0  # pad byte
        assert encoded[2:] == b"\x01\x00"

        decoded = decode(encoded, epath_padded_pad_len)
        assert len(decoded) == 1


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
            SymbolicSegment(symbol="Program:MainProgram"),
            LogicalSegment(type=LogicalSegmentType.type_instance_id, value=1),
        ]

        data = encode(segments, epath_packed)

        result = decode(data, epath_packed)
        assert len(result) == 2
        assert isinstance(result[0], SymbolicSegment)
        assert result[0].symbol == "Program:MainProgram"


class TestBuiltinRoundtrips:
    """Tests for encoding/decoding CIP types via builtin conversion."""

    def test_port_segment(self) -> None:
        """Test encoding/decoding CIPSegment via builtin conversion."""
        segment = PortSegment(port=1, link_address=2)

        # Convert to builtins
        builtins = _to_builtins(segment, recursive=False)
        assert isinstance(builtins, dict)
        assert builtins["segment_type"] == SegmentType.port
        assert builtins["port"] == 1
        assert builtins["link_address"] == 2

        data = encode(segment, cip_segment)
        assert data == b"\x01\x02"
        result = decode(data, cip_segment)
        assert result == segment

        # Convert back to CIPSegment
        converted = _convert(builtins, PortSegment, recursive=False)
        assert isinstance(converted, PortSegment)
        assert converted.TYPE == SegmentType.port
        assert converted.port == 1
        assert converted.link_address == 2
