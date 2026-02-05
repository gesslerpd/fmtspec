"""Tests for CIP (Common Industrial Protocol) types."""

import pytest

from fmtspec import DecodeError, decode, encode
from fmtspec._core import _convert, _to_builtins
from fmtspec.types import (
    LogicalSegment,
    LogicalSegmentType,
    PortSegment,
    SymbolicSegment,
    cip_segment,
    cip_segment_padded,
    epath_packed,
    short_sized_padded_epath,
    sized_padded_epath,
)

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
        fmt = cip_segment_padded
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
