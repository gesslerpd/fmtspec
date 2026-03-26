"""Tests for inspection functionality."""

from collections import deque
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import pytest

import fmtspec
from fmtspec import format_tree, types
from fmtspec._core import _decode_stream_impl, _encode_stream_impl


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
        assert not tree.children

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
        buffer = memoryview(bytearray(b"\x01"))
        node = fmtspec.InspectNode(
            key="test",
            fmt=types.Int(byteorder="big", signed=False, size=1),
            value=1,
            offset=0,
            size=1,
            children=deque(),
            buffer=buffer,
        )
        r = repr(node)
        assert "key='test'" in r
        assert "offset=0" in r
        assert "size=1" in r

    def test_repr_with_children(self):
        """Test repr includes children indicator."""
        buffer = memoryview(bytearray(b"\x01"))
        child = fmtspec.InspectNode(
            key="child",
            fmt=types.Int(byteorder="big", signed=False, size=1),
            value=1,
            offset=0,
            size=1,
            children=deque(),
            buffer=buffer,
        )
        parent = fmtspec.InspectNode(
            key=None,
            fmt={},
            value={"child": 1},
            offset=0,
            size=1,
            children=deque((child,)),
            buffer=buffer,
        )
        r = repr(parent)
        assert "children=[...]" in r

    def test_data_requires_attached_buffer(self):
        node = fmtspec.InspectNode(
            key="test",
            fmt=types.Int(byteorder="big", signed=False, size=1),
            value=1,
            offset=0,
            size=1,
            children=deque(),
        )

        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = node.data


class TestInspectNodeViews:
    """Tests for direct view behavior on inspection nodes."""

    def test_encode_inspect_returns_view_backed_tree(self):
        fmt = {
            "header": {
                "version": types.Int(byteorder="big", signed=False, size=1),
                "flags": types.Int(byteorder="big", signed=False, size=1),
            },
            "data": types.Int(byteorder="big", signed=False, size=2),
        }
        _, tree = fmtspec.encode_inspect(
            {"header": {"version": 1, "flags": 2}, "data": 0x0304}, fmt
        )

        assert tree.buffer is not None
        assert tree["header"].buffer is not None
        assert tree["header"]["version"].buffer is not None
        assert tree["header"]["version"].value == 1

        assert tree["header"]["version"].data == b"\x01"
        assert tree["data"].data == b"\x03\x04"

    # def test_encode_inspect_tree_updates_bytes_and_values(self):
    #     fmt = {
    #         "header": {
    #             "version": types.Int(byteorder="big", signed=False, size=1),
    #             "flags": types.Int(byteorder="big", signed=False, size=1),
    #         },
    #         "data": types.Int(byteorder="big", signed=False, size=2),
    #     }
    #     _, tree = fmtspec.encode_inspect(
    #         {"header": {"version": 1, "flags": 2}, "data": 0x0304}, fmt
    #     )

    #     tree["data"].data = b"\x05\x06"

    #     assert tree["data"].value == 0x0506
    #     assert tree.data == b"\x01\x02\x05\x06"
    #     assert tree.value == {"header": {"version": 1, "flags": 2}, "data": 0x0506}

    #     tree["header"].value = {"version": 9, "flags": 10}

    #     assert tree.data == b"\x09\x0a\x05\x06"
    #     assert tree["header"]["flags"].value == 10

    #     output = format_tree(tree)
    #     assert "09" in output
    #     assert "0a" in output
    #     assert "05 06" in output

    # def test_decode_inspect_tree_updates_bytes_and_values(self):
    #     fmt = {
    #         "x": types.Int(byteorder="big", signed=False, size=1),
    #         "y": types.Int(byteorder="big", signed=False, size=2),
    #     }
    #     _, tree = fmtspec.decode_inspect(b"\x01\x02\x03", fmt)

    #     assert tree.buffer is not None
    #     assert tree["y"].data == b"\x02\x03"

    #     tree["y"].value = 0x0A0B

    #     assert tree["y"].data == b"\x0a\x0b"
    #     assert tree.data == b"\x01\x0a\x0b"
    #     assert tree.value == {"x": 1, "y": 0x0A0B}

    # def test_subtree_nodes_are_view_backed_without_conversion(self):
    #     fmt = {
    #         "prefix": types.Int(byteorder="big", signed=False, size=1),
    #         "payload": types.Int(byteorder="big", signed=False, size=2),
    #     }
    #     _, tree = fmtspec.encode_inspect({"prefix": 1, "payload": 0x0203}, fmt)

    #     payload = tree["payload"]

    #     assert payload.buffer is not None
    #     assert payload.data == b"\x02\x03"

    #     payload.value = 0x0A0B

    #     assert payload.data == b"\x0a\x0b"
    #     assert payload.value == 0x0A0B


class TestContextInspectHelpers:
    """Tests for public Context inspection helpers."""

    def test_inspect_leaf_noop_when_disabled(self):
        context = fmtspec.Context()
        stream = BytesIO()

        stream.write(b"\x01")
        context.inspect_leaf(
            stream,
            "field",
            types.Int(byteorder="big", signed=False, size=1),
            1,
            0,
        )

        assert not context.inspect_children

    def test_inspect_leaf_prepend(self):
        context = fmtspec.Context(inspect=True)
        stream = BytesIO()
        fmt = types.Int(byteorder="big", signed=False, size=1)

        stream.write(b"\x01")
        context.inspect_leaf(stream, "value", fmt, 1, 0)

        start = stream.tell()
        stream.write(b"\x02")
        context.inspect_leaf(stream, "--prefix--", fmt, 2, start, prepend=True)

        assert [child.key for child in context.inspect_children] == ["--prefix--", "value"]

    def test_inspect_scope_restores_parent_children(self):
        context = fmtspec.Context(inspect=True)
        stream = BytesIO()

        with context.inspect_scope(stream, "payload", types.Bytes(2), None) as node:
            stream.write(b"\x01")
            context.inspect_leaf(
                stream, "tag", types.Int(byteorder="big", signed=False, size=1), 1, 0
            )
            stream.write(b"\x02")
            if node:
                node.value = b"\x01\x02"

        assert len(context.inspect_children) == 1
        payload = context.inspect_children[0]
        assert payload.key == "payload"
        assert payload.size == 2
        assert payload.value == b"\x01\x02"
        assert [child.key for child in payload.children] == ["tag"]

    def test_inspect_scope_nests_child_nodes(self):
        context = fmtspec.Context(inspect=True)
        stream = BytesIO()

        with context.inspect_scope(stream, "outer", types.Bytes(2), None) as outer:
            stream.write(b"\x01")
            with context.inspect_scope(stream, "inner", types.Bytes(1), None) as inner:
                stream.write(b"\x02")
                if inner:
                    inner.value = 2
            if outer:
                outer.value = [2]

        outer_node = context.inspect_children[0]
        inner_node = outer_node.children[0]

        assert outer_node.key == "outer"
        assert outer_node.value == [2]
        assert inner_node.key == "inner"
        assert inner_node.value == 2

    def test_inspect_scope_noop_when_disabled(self):
        context = fmtspec.Context()
        stream = BytesIO()

        with context.inspect_scope(stream, "payload", types.Bytes(1), None) as node:
            stream.write(b"\x01")
            assert node is None

        assert not context.inspect_children


class TestRoundtrip:
    """Test that inspection doesn't affect encode/decode correctness."""

    def test_encode_inspect_matches_encode(self):
        """Verify encode_inspect produces the same bytes as encode."""
        fmt = {
            "name": types.TakeUntil(types.Str(), b"\0"),
            "value": types.Int(byteorder="little", signed=False, size=4),
        }
        obj = {"name": "test", "value": 42}

        regular_data = fmtspec.encode(obj, fmt)
        inspect_data, _ = fmtspec.encode_inspect(obj, fmt)

        assert inspect_data == regular_data

    def test_decode_inspect_matches_decode(self):
        """Verify decode_inspect produces the same result as decode."""
        fmt = {
            "name": types.TakeUntil(types.Str(), b"\0"),
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
        tree = _encode_stream_impl(stream, 0x0102, fmt, inspect=True)

        # Verify stream contains encoded data
        assert stream.getvalue() == b"\x01\x02"

        # Verify tree structure
        assert tree.key is None  # root node
        assert tree.offset == 0
        assert tree.size == 2
        assert tree.value == 0x0102
        assert not tree.children

    def test_mapping_format(self):
        """Test stream inspection of a mapping (dict) format."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        obj = {"x": 0x01, "y": 0x0203}
        stream = BytesIO()
        tree = _encode_stream_impl(stream, obj, fmt, inspect=True)

        assert stream.getvalue() == b"\x01\x02\x03"
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 3
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.data
        assert len(tree.children) == 2

        # First child: x
        x_node = tree.children[0]
        assert x_node.key == "x"
        assert x_node.offset == 0
        assert x_node.size == 1
        assert x_node.value == 0x01
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = x_node.data

        # Second child: y
        y_node = tree.children[1]
        assert y_node.key == "y"
        assert y_node.offset == 1
        assert y_node.size == 2
        assert y_node.value == 0x0203
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = y_node.data

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
        tree = _encode_stream_impl(stream, obj, fmt, inspect=True)

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

        tree = _encode_stream_impl(stream, 0x0102, fmt, inspect=True)

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

        # Using _encode_stream_impl
        stream = BytesIO()
        tree2 = _encode_stream_impl(stream, obj, fmt, inspect=True)

        assert stream.getvalue() == data_bytes
        assert tree1.offset == tree2.offset
        assert tree1.size == tree2.size
        assert tree1.value == tree2.value


class TestDecodeInspectStream:
    """Tests for decode_inspect_stream function."""

    def test_simple_type(self):
        """Test stream inspection of a simple integer decode."""
        fmt = types.Int(byteorder="big", signed=False, size=2)
        stream = BytesIO(b"\x01\x02")
        result, tree = _decode_stream_impl(stream, fmt, inspect=True)

        assert result == 0x0102
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 2
        assert tree.value == 0x0102

    def test_mapping_format(self):
        """Test stream inspection of a mapping decode."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }
        stream = BytesIO(b"\x01\x02\x03")
        result, tree = _decode_stream_impl(stream, fmt, inspect=True)

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
        result, tree = _decode_stream_impl(stream, fmt, inspect=True)

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
        result, tree = _decode_stream_impl(stream, fmt, inspect=True)

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

        # Using decode_stream_inspect
        stream = BytesIO(data)
        result2, tree2 = _decode_stream_impl(stream, fmt, inspect=True)

        assert result1 == result2
        assert tree1.offset == tree2.offset
        assert tree1.size == tree2.size
        assert tree1.value == tree2.value
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree2.data

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
        result, tree = _decode_stream_impl(stream, fmt, inspect=True, shape=Point)

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
        tree = _encode_stream_impl(stream, obj, fmt, inspect=True)

        # Verify data was written
        assert backing.getvalue() == b"\x01\x02\x03"

        # Tree structure should be valid
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.value == {"x": 0x01, "y": 0x0203}
        assert len(tree.children) == 2

        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.data
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.children[0].data
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.children[1].data

    def test_decode_unseekable_stream(self):
        """Test decode_inspect_stream with an unseekable stream."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=2),
        }

        # Use unseekable stream
        backing = BytesIO(b"\x01\x02\x03")
        stream = UnseekableStream(backing)
        result, tree = _decode_stream_impl(stream, fmt, inspect=True)

        # Result should be correct
        assert result == {"x": 0x01, "y": 0x0203}

        # Tree structure should be valid
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.value == {"x": 0x01, "y": 0x0203}
        assert len(tree.children) == 2

        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.data
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.children[0].data
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.children[1].data

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
        tree = _encode_stream_impl(stream, obj, fmt, inspect=True)

        assert tree.size == 4
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.data
        assert len(tree.children) == 2
        assert tree.children[0].key == "header"
        assert len(tree.children[0].children) == 2
        with pytest.raises(RuntimeError, match="buffer is not attached"):
            _ = tree.children[0].data


class TestArrayInspect:
    """Tests for array inspection functionality."""

    def test_1d_array_encode_inspect(self):
        """Test inspection of a 1D array encode."""
        arr_fmt = types.array(types.u8, dims=3)
        obj = [1, 2, 3]
        data, tree = fmtspec.encode_inspect(obj, arr_fmt)

        assert data == b"\x01\x02\x03"
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 3
        assert tree.data == b"\x01\x02\x03"
        # Array should have 3 children (one per element)
        assert len(tree.children) == 3

        # Check individual element nodes
        assert tree.children[0].key == 0
        assert tree.children[0].value == 1
        assert tree.children[0].data == b"\x01"
        assert tree.children[0].offset == 0

        assert tree.children[1].key == 1
        assert tree.children[1].value == 2
        assert tree.children[1].data == b"\x02"
        assert tree.children[1].offset == 1

        assert tree.children[2].key == 2
        assert tree.children[2].value == 3
        assert tree.children[2].data == b"\x03"
        assert tree.children[2].offset == 2

    def test_1d_array_decode_inspect(self):
        """Test inspection of a 1D array decode."""
        arr_fmt = types.array(types.u8, dims=3)
        result, tree = fmtspec.decode_inspect(b"\x01\x02\x03", arr_fmt)

        assert result == [1, 2, 3]
        assert tree.key is None
        assert tree.offset == 0
        assert tree.size == 3
        # Array should have 3 children (one per element)
        assert len(tree.children) == 3

        # Check individual element nodes
        assert tree.children[0].key == 0
        assert tree.children[0].value == 1
        assert tree.children[0].data == b"\x01"

        assert tree.children[1].key == 1
        assert tree.children[1].value == 2
        assert tree.children[1].data == b"\x02"

        assert tree.children[2].key == 2
        assert tree.children[2].value == 3
        assert tree.children[2].data == b"\x03"

    def test_2d_array_encode_inspect(self):
        """Test inspection of a 2D array encode."""
        arr_fmt = types.array(types.u8, dims=(2, 3))
        obj = [[1, 2, 3], [4, 5, 6]]
        data, tree = fmtspec.encode_inspect(obj, arr_fmt)

        print(format_tree(tree))

        assert data == b"\x01\x02\x03\x04\x05\x06"
        assert tree.size == 6
        # 2D array with (2,3) dims should have 2 row children
        assert len(tree.children) == 2

        # First row [1, 2, 3]
        row0 = tree.children[0]
        assert row0.key == 0
        assert len(row0.children) == 3
        assert [c.value for c in row0.children] == [1, 2, 3]
        assert [c.key for c in row0.children] == [0, 1, 2]

        # Second row [4, 5, 6]
        row1 = tree.children[1]
        assert row1.key == 1
        assert len(row1.children) == 3
        assert [c.value for c in row1.children] == [4, 5, 6]
        assert [c.key for c in row1.children] == [0, 1, 2]

    def test_2d_array_decode_inspect(self):
        """Test inspection of a 2D array decode."""
        arr_fmt = types.array(types.u8, dims=(2, 3))
        result, tree = fmtspec.decode_inspect(b"\x01\x02\x03\x04\x05\x06", arr_fmt)

        assert result == [[1, 2, 3], [4, 5, 6]]
        assert tree.size == 6
        # 2D array should have 2 row children with 3 element children each
        assert len(tree.children) == 2
        assert len(tree.children[0].children) == 3
        assert len(tree.children[1].children) == 3

    def test_greedy_array_encode_inspect(self):
        """Test inspection of a greedy array (no dims) encode."""
        arr_fmt = types.array(types.u8)  # greedy array
        obj = [1, 2, 3, 4]
        data, tree = fmtspec.encode_inspect(obj, arr_fmt)

        assert data == b"\x01\x02\x03\x04"
        assert len(tree.children) == 4

        for i, child in enumerate(tree.children):
            assert child.key == i
            assert child.value == i + 1

    def test_greedy_array_decode_inspect(self):
        """Test inspection of a greedy array (no dims) decode."""
        arr_fmt = types.array(types.u8)  # greedy array
        result, tree = fmtspec.decode_inspect(b"\x01\x02\x03\x04", arr_fmt)

        assert result == [1, 2, 3, 4]
        assert len(tree.children) == 4

        for i, child in enumerate(tree.children):
            assert child.key == i
            assert child.value == i + 1

    def test_array_in_mapping_encode_inspect(self):
        """Test inspection of array nested in a mapping."""
        fmt = {
            "count": types.u8,
            "data": types.array(types.u16be, dims=2),
        }
        obj = {"count": 2, "data": [0x0102, 0x0304]}
        data, tree = fmtspec.encode_inspect(obj, fmt)

        assert data == b"\x02\x01\x02\x03\x04"
        assert len(tree.children) == 2

        # First child is the count field
        assert tree.children[0].key == "count"
        assert tree.children[0].value == 2

        # Second child is the array
        data_node = tree.children[1]
        assert data_node.key == "data"
        assert len(data_node.children) == 2
        assert data_node.children[0].key == 0
        assert data_node.children[0].value == 0x0102
        assert data_node.children[1].key == 1
        assert data_node.children[1].value == 0x0304

    def test_array_in_mapping_decode_inspect(self):
        """Test inspection of array nested in a mapping decode."""
        fmt = {
            "count": types.u8,
            "data": types.array(types.u16be, dims=2),
        }
        result, tree = fmtspec.decode_inspect(b"\x02\x01\x02\x03\x04", fmt)

        assert result == {"count": 2, "data": [0x0102, 0x0304]}
        assert len(tree.children) == 2

        data_node = tree.children[1]
        assert data_node.key == "data"
        assert len(data_node.children) == 2
        assert data_node.children[0].value == 0x0102
        assert data_node.children[1].value == 0x0304

    def test_array_format_tree_output(self):
        """Test format_tree output with array."""
        arr_fmt = types.array(types.u8, dims=3)
        _, tree = fmtspec.encode_inspect([1, 2, 3], arr_fmt)
        output = fmtspec.format_tree(tree)

        # Should contain element entries
        assert "[0]" in output
        assert "[1]" in output
        assert "[2]" in output
        # Should show values
        assert "value: 1" in output
        assert "value: 2" in output
        assert "value: 3" in output
