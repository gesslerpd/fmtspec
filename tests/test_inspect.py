"""Tests for inspection functionality."""

from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import fmtspec
from fmtspec import types
from fmtspec._inspect import _decode_inspect_stream, _encode_inspect_stream


class UnseekableStream(BinaryIO):
    """A stream wrapper that doesn't support seeking."""

    def __init__(self, stream):
        self._stream = stream

    def read(self, size=-1):
        return self._stream.read(size)

    def write(self, data):
        return self._stream.write(data)

    def tell(self):
        return self._stream.tell()

    # Deliberately omit seek() to make it unseekable


class TestEncodeInspect:
    """Tests for encode_inspect function."""

    def test_simple_type(self):
        """Test inspection of a simple integer type."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        data, tree = fmtspec.encode_inspect(0x0102, fmt)

        assert data == b"\x01\x02"
        assert tree.key is None  # root node
        assert tree.offset == 0
        assert tree.size == 2
        assert tree.data == b"\x01\x02"
        assert tree.value == 0x0102
        assert tree.children == []

    def test_mapping_format(self):
        """Test inspection of a mapping (dict) format."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        obj = {"x": 0x01, "y": 0x0203}
        data, tree = fmtspec.encode_inspect(obj, fmt)

        assert data == b"\x01\x02\x03"
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.data == b"\x01\x02\x03"
        assert len(tree.children) == 2

        # First child: x
        x_node = tree.children[0]
        assert x_node.key == "x"
        assert x_node.offset == 0
        assert x_node.size == 1
        assert x_node.data == b"\x01"
        assert x_node.value == 0x01

        # Second child: y
        y_node = tree.children[1]
        assert y_node.key == "y"
        assert y_node.offset == 1
        assert y_node.size == 2
        assert y_node.data == b"\x02\x03"
        assert y_node.value == 0x0203

    def test_iterable_format(self):
        """Test inspection of an iterable (tuple) format."""
        fmt = (
            types.Int(byteorder="big", signed=False, size=1),
            types.Int(byteorder="big", signed=False, size=2),
        )
        obj = [0x01, 0x0203]
        data, tree = fmtspec.encode_inspect(obj, fmt)

        assert data == b"\x01\x02\x03"
        assert tree.key is None
        assert tree.size == 3
        assert len(tree.children) == 2

        # Children use index as name
        assert tree.children[0].key == 0
        assert tree.children[1].key == 1

    def test_nested_mapping(self):
        """Test inspection of nested structures."""
        fmt = {
            "header": {
                "version": types.Int(byteorder="big", signed=False, size=1),
                "flags": types.Int(byteorder="big", signed=False, size=1),
            },
            "data": types.Int(byteorder="big", signed=False, size=2),
        }
        obj = {"header": {"version": 1, "flags": 2}, "data": 0x0304}
        data, tree = fmtspec.encode_inspect(obj, fmt)

        assert data == b"\x01\x02\x03\x04"
        assert tree.size == 4
        assert len(tree.children) == 2

        header_node = tree.children[0]
        assert header_node.key == "header"
        assert header_node.size == 2
        assert len(header_node.children) == 2
        assert header_node.children[0].key == "version"
        assert header_node.children[1].key == "flags"


class TestDecodeInspect:
    """Tests for decode_inspect function."""

    def test_simple_type(self):
        """Test inspection of a simple integer decode."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        result, tree = fmtspec.decode_inspect(b"\x01\x02", fmt)

        assert result == 0x0102
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 2
        assert tree.data == b"\x01\x02"
        assert tree.value == 0x0102

    def test_mapping_format(self):
        """Test inspection of a mapping decode."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        result, tree = fmtspec.decode_inspect(b"\x01\x02\x03", fmt)

        assert result == {"x": 0x01, "y": 0x0203}
        assert tree.size == 3
        assert len(tree.children) == 2

        assert tree.children[0].key == "x"
        assert tree.children[0].value == 0x01

        assert tree.children[1].key == "y"
        assert tree.children[1].value == 0x0203

    def test_iterable_format(self):
        """Test inspection of an iterable (tuple) decode."""
        fmt = (
            types.Int(byteorder="big", signed=False, size=1),
            types.Int(byteorder="big", signed=False, size=2),
        )
        result, tree = fmtspec.decode_inspect(b"\x01\x02\x03", fmt)

        assert result == [0x01, 0x0203]
        assert tree.key is None
        assert tree.size == 3
        assert len(tree.children) == 2

        # Children use index as key
        assert tree.children[0].key == 0
        assert tree.children[0].value == 0x01
        assert tree.children[0].offset == 0
        assert tree.children[0].size == 1

        assert tree.children[1].key == 1
        assert tree.children[1].value == 0x0203
        assert tree.children[1].offset == 1
        assert tree.children[1].size == 2


class TestFormatTree:
    """Tests for format_tree utility function."""

    def test_simple_output(self):
        """Test that format_tree produces readable output."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=1),
        }
        _, tree = fmtspec.encode_inspect({"x": 1, "y": 2}, fmt)

        output = fmtspec.format_tree(tree)

        # Should contain key information
        assert "*" in output
        assert "[x]" in output
        assert "[y]" in output
        assert "01" in output  # hex byte
        assert "02" in output  # hex byte

    def test_without_data(self):
        """Test format_tree with show_data=False."""
        fmt = types.Int(byteorder="big", signed=False, size=1)
        _, tree = fmtspec.encode_inspect(1, fmt)

        output = fmtspec.format_tree(tree, show_data=False)

        # Should not contain hex dump
        lines = output.split("\n")
        assert not any("data:" in line for line in lines)

    def test_truncated_data(self):
        """Test that long data is truncated."""
        fmt = types.Bytes(size=32)
        _, tree = fmtspec.encode_inspect(b"\x00" * 32, fmt)

        output = fmtspec.format_tree(tree, max_data_bytes=8)

        # Should contain ellipsis indicating truncation
        assert "..." in output


class TestFormatNode:
    """Tests for FormatNode dataclass."""

    def test_repr(self):
        """Test the repr of FormatNode."""
        node = fmtspec.InspectNode(
            key="test",
            fmt=types.Int(byteorder="big", signed=False, size=1),
            data=b"\x01",
            value=1,
            offset=0,
            size=1,
            children=[],
        )
        r = repr(node)
        assert "key='test'" in r
        assert "offset=0" in r
        assert "size=1" in r

    def test_repr_with_children(self):
        """Test repr includes children indicator."""
        child = fmtspec.InspectNode(
            key="child",
            fmt=types.Int(byteorder="big", signed=False, size=1),
            data=b"\x01",
            value=1,
            offset=0,
            size=1,
            children=[],
        )
        parent = fmtspec.InspectNode(
            key=None,
            fmt={},
            data=b"\x01",
            value={"child": 1},
            offset=0,
            size=1,
            children=[child],
        )
        r = repr(parent)
        assert "children=[...]" in r


class TestRoundtrip:
    """Test that inspection doesn't affect encode/decode correctness."""

    def test_encode_inspect_matches_encode(self):
        """Verify encode_inspect produces the same bytes as encode."""
        fmt = {
            "name": types.TakeUntil(types.String(), b"\0"),
            "value": types.Int(byteorder="little", signed=False, size=4),
        }
        obj = {"name": "test", "value": 42}

        regular_data = fmtspec.encode(obj, fmt)
        inspect_data, _ = fmtspec.encode_inspect(obj, fmt)

        assert inspect_data == regular_data

    def test_decode_inspect_matches_decode(self):
        """Verify decode_inspect produces the same result as decode."""
        fmt = {
            "name": types.TakeUntil(types.String(), b"\0"),
            "value": types.Int(byteorder="little", signed=False, size=4),
        }
        data = b"test\0\x2a\x00\x00\x00"

        regular_result = fmtspec.decode(data, fmt)
        inspect_result, _ = fmtspec.decode_inspect(data, fmt)

        assert inspect_result == regular_result


class TestEncodeInspectStream:
    """Tests for encode_inspect_stream function."""

    def test_simple_type(self):
        """Test stream inspection of a simple integer type."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        stream = BytesIO()
        tree = _encode_inspect_stream(0x0102, stream, fmt)

        # Verify stream contains encoded data
        assert stream.getvalue() == b"\x01\x02"

        # Verify tree structure
        assert tree.key is None  # root node
        assert tree.offset == 0
        assert tree.size == 2
        assert tree.data == b"\x01\x02"
        assert tree.value == 0x0102
        assert tree.children == []

    def test_mapping_format(self):
        """Test stream inspection of a mapping (dict) format."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        obj = {"x": 0x01, "y": 0x0203}
        stream = BytesIO()
        tree = _encode_inspect_stream(obj, stream, fmt)

        assert stream.getvalue() == b"\x01\x02\x03"
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.data == b"\x01\x02\x03"
        assert len(tree.children) == 2

        # First child: x
        x_node = tree.children[0]
        assert x_node.key == "x"
        assert x_node.offset == 0
        assert x_node.size == 1
        assert x_node.data == b"\x01"
        assert x_node.value == 0x01

        # Second child: y
        y_node = tree.children[1]
        assert y_node.key == "y"
        assert y_node.offset == 1
        assert y_node.size == 2
        assert y_node.data == b"\x02\x03"
        assert y_node.value == 0x0203

    def test_nested_structure(self):
        """Test stream inspection of nested structures."""
        fmt = {
            "header": {
                "version": types.Int(byteorder="big", signed=False, size=1),
                "flags": types.Int(byteorder="big", signed=False, size=1),
            },
            "data": types.Int(byteorder="big", signed=False, size=2),
        }
        obj = {"header": {"version": 1, "flags": 2}, "data": 0x0304}
        stream = BytesIO()
        tree = _encode_inspect_stream(obj, stream, fmt)

        assert stream.getvalue() == b"\x01\x02\x03\x04"
        assert tree.size == 4
        assert len(tree.children) == 2

        header_node = tree.children[0]
        assert header_node.key == "header"
        assert header_node.size == 2
        assert len(header_node.children) == 2

    def test_stream_position_preserved(self):
        """Test that stream position is correct after encoding."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        stream = BytesIO()
        stream.write(b"\xff\xff")  # Write some initial data
        start_pos = stream.tell()

        tree = _encode_inspect_stream(0x0102, stream, fmt)

        # Stream should be positioned after the written data
        assert stream.tell() == start_pos + 2
        assert stream.getvalue() == b"\xff\xff\x01\x02"
        # Tree offsets are absolute positions in the stream
        assert tree.offset == start_pos
        assert tree.size == 2

    def test_matches_encode_inspect(self):
        """Verify encode_inspect_stream produces same result as encode_inspect."""
        fmt = {
            "a": types.Int(byteorder="big", signed=False, size=1),
            "b": types.Int(byteorder="big", signed=False, size=1),
        }
        obj = {"a": 1, "b": 2}

        # Using encode_inspect
        data_bytes, tree1 = fmtspec.encode_inspect(obj, fmt)

        # Using encode_inspect_stream
        stream = BytesIO()
        tree2 = _encode_inspect_stream(obj, stream, fmt)

        assert stream.getvalue() == data_bytes
        assert tree1.offset == tree2.offset
        assert tree1.size == tree2.size
        assert tree1.value == tree2.value
        assert tree1.data == tree2.data


class TestDecodeInspectStream:
    """Tests for decode_inspect_stream function."""

    def test_simple_type(self):
        """Test stream inspection of a simple integer decode."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        stream = BytesIO(b"\x01\x02")
        result, tree = _decode_inspect_stream(stream, fmt)

        assert result == 0x0102
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 2
        assert tree.data == b"\x01\x02"
        assert tree.value == 0x0102

    def test_mapping_format(self):
        """Test stream inspection of a mapping decode."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        stream = BytesIO(b"\x01\x02\x03")
        result, tree = _decode_inspect_stream(stream, fmt)

        assert result == {"x": 0x01, "y": 0x0203}
        assert tree.size == 3
        assert len(tree.children) == 2

        assert tree.children[0].key == "x"
        assert tree.children[0].value == 0x01

        assert tree.children[1].key == "y"
        assert tree.children[1].value == 0x0203

    def test_nested_structure(self):
        """Test stream inspection of nested structures."""
        fmt = {
            "header": {
                "version": types.Int(byteorder="big", signed=False, size=1),
                "flags": types.Int(byteorder="big", signed=False, size=1),
            },
            "data": types.Int(byteorder="big", signed=False, size=2),
        }
        stream = BytesIO(b"\x01\x02\x03\x04")
        result, tree = _decode_inspect_stream(stream, fmt)

        assert result == {"header": {"version": 1, "flags": 2}, "data": 0x0304}
        assert tree.size == 4
        assert len(tree.children) == 2

        header_node = tree.children[0]
        assert header_node.key == "header"
        assert header_node.size == 2

    def test_stream_position_preserved(self):
        """Test that stream position is correct after decoding."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        stream = BytesIO(b"\x01\x02\xff\xff")
        result, tree = _decode_inspect_stream(stream, fmt)

        # Stream should be positioned after the decoded data
        assert stream.tell() == 2
        assert result == 0x0102
        assert tree.size == 2

        # Can continue reading
        remaining = stream.read()
        assert remaining == b"\xff\xff"

    def test_matches_decode_inspect(self):
        """Verify decode_inspect_stream produces same result as decode_inspect."""
        fmt = {
            "a": types.Int(byteorder="big", signed=False, size=1),
            "b": types.Int(byteorder="big", signed=False, size=1),
        }
        data = b"\x01\x02"

        # Using decode_inspect
        result1, tree1 = fmtspec.decode_inspect(data, fmt)

        # Using decode_inspect_stream
        stream = BytesIO(data)
        result2, tree2 = _decode_inspect_stream(stream, fmt)

        assert result1 == result2
        assert tree1.offset == tree2.offset
        assert tree1.size == tree2.size
        assert tree1.value == tree2.value
        assert tree1.data == tree2.data

    def test_with_shape_parameter(self):
        """Test decode_inspect_stream with shape parameter."""

        @dataclass
        class Point:
            x: int
            y: int

        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=1),
        }
        stream = BytesIO(b"\x01\x02")
        result, tree = _decode_inspect_stream(stream, fmt, shape=Point)

        assert isinstance(result, Point)
        assert result.x == 1
        assert result.y == 2
        assert tree.value == {"x": 1, "y": 2}  # Tree still has dict value


class TestUnseekableStreams:
    """Tests for unseekable stream handling."""

    def test_encode_unseekable_stream(self):
        """Test encode_inspect_stream with an unseekable stream."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        obj = {"x": 0x01, "y": 0x0203}

        # Use unseekable stream
        backing = BytesIO()
        stream = UnseekableStream(backing)
        tree = _encode_inspect_stream(obj, stream, fmt)

        # Verify data was written
        assert backing.getvalue() == b"\x01\x02\x03"

        # Tree structure should be valid
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.value == {"x": 0x01, "y": 0x0203}
        assert len(tree.children) == 2

        # captures data even for unseekable streams
        assert tree.data == b"\x01\x02\x03"
        assert tree.children[0].data == b"\x01"
        assert tree.children[1].data == b"\x02\x03"

    def test_decode_unseekable_stream(self):
        """Test decode_inspect_stream with an unseekable stream."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }

        # Use unseekable stream
        backing = BytesIO(b"\x01\x02\x03")
        stream = UnseekableStream(backing)
        result, tree = _decode_inspect_stream(stream, fmt)

        # Result should be correct
        assert result == {"x": 0x01, "y": 0x0203}

        # Tree structure should be valid
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.value == {"x": 0x01, "y": 0x0203}
        assert len(tree.children) == 2

        # captures data even for unseekable streams
        assert tree.data == b"\x01\x02\x03"
        assert tree.children[0].data == b"\x01"
        assert tree.children[1].data == b"\x02\x03"

    def test_unseekable_nested_structure(self):
        """Test unseekable stream with nested structures."""
        fmt = {
            "header": {
                "version": types.Int(byteorder="big", signed=False, size=1),
                "flags": types.Int(byteorder="big", signed=False, size=1),
            },
            "data": types.Int(byteorder="big", signed=False, size=2),
        }

        # Encode with unseekable
        obj = {"header": {"version": 1, "flags": 2}, "data": 0x0304}
        backing = BytesIO()
        stream = UnseekableStream(backing)
        tree = _encode_inspect_stream(obj, stream, fmt)

        # captures data even for nested unseekable streams
        assert tree.size == 4
        assert tree.data == b"\x01\x02\x03\x04"
        assert len(tree.children) == 2
        assert tree.children[0].key == "header"
        assert len(tree.children[0].children) == 2
        assert tree.children[0].data == b"\x01\x02"
