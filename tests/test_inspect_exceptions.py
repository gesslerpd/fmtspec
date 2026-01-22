"""Tests for partial inspection trees in exceptions."""

import pytest

from fmtspec import DecodeError, EncodeError, decode_inspect, encode_inspect, format_tree, types


class TestEncodeInspectExceptions:
    """Test that encode_inspect includes partial trees in exceptions."""

    def test_encode_error_includes_tree(self):
        """Encode errors should include a inspection tree."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=1),
        }
        # Missing required key 'y'
        obj = {"x": 1}

        with pytest.raises(EncodeError) as exc_info:
            encode_inspect(obj, fmt)

        assert exc_info.value.inspect_node is not None
        assert exc_info.value.inspect_node.key is None  # root node
        assert exc_info.value.inspect_node.offset == 0

    def test_encode_error_tree_shows_progress(self):
        """Tree should show what was successfully encoded before the error."""
        fmt = {
            "a": types.Int(byteorder="big", signed=False, size=1),
            "b": types.Int(byteorder="big", signed=False, size=1),
            "c": types.Int(byteorder="big", signed=False, size=1),
        }
        # Missing required key 'c'
        obj = {"a": 10, "b": 20}

        with pytest.raises(EncodeError) as exc_info:
            encode_inspect(obj, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None

        # print("Should have encoded 2 bytes before hitting missing field 'c'")
        # print(format_tree(tree))

    def test_encode_nested_error_includes_tree(self):
        """Nested encoding errors should include an inspection tree."""

        class BadType:
            """A type that raises an error during encoding."""

            @property
            def size(self):
                return None

            def encode(self, _value, _stream, *, context):  # noqa: ARG002
                raise ValueError("Intentional encoding error")

            def decode(self, _stream, *, context):
                pass

        fmt = {"x": types.Int(byteorder="big", signed=False, size=1), "y": BadType()}
        obj = {"x": 1, "y": 2}

        with pytest.raises(EncodeError) as exc_info:
            encode_inspect(obj, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None

        # print("Should have encoded the first field successfully")
        # print(format_tree(tree))

    def test_encode_iterable_error_includes_tree(self):
        """Iterable encoding errors should include an inspection tree."""
        fmt = (
            types.Int(byteorder="big", signed=False, size=1),
            types.Int(byteorder="big", signed=False, size=1),
            types.Int(byteorder="big", signed=False, size=1),
        )
        # Only 2 elements, but format expects 3
        obj = [10, 20]

        with pytest.raises(EncodeError) as exc_info:
            encode_inspect(obj, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None
        assert tree.offset == 0
        # Should have encoded 2 bytes before hitting the error
        assert len(tree.children) == 2
        assert tree.children[0].key == 0
        assert tree.children[1].key == 1


class TestDecodeInspectExceptions:
    """Test that decode_inspect includes inspection trees in exceptions."""

    def test_decode_error_includes_tree(self):
        """Decode errors should include an inspection tree."""
        fmt = {
            "x": types.Int(byteorder="big", signed=False, size=1),
            "y": types.Int(byteorder="big", signed=False, size=1),
        }
        # Only 1 byte, but format expects 2
        data = b"\x01"

        with pytest.raises(DecodeError) as exc_info:
            decode_inspect(data, fmt)

        assert exc_info.value.inspect_node is not None
        assert exc_info.value.inspect_node.key is None  # root node
        assert exc_info.value.inspect_node.offset == 0

    def test_decode_error_tree_shows_progress(self):
        """Tree should show what was successfully decoded before the error."""
        fmt = {
            "a": types.Int(byteorder="big", signed=False, size=1),
            "b": types.Int(byteorder="big", signed=False, size=1),
            "c": types.Int(byteorder="big", signed=False, size=1),
        }
        # Only 2 bytes, but format expects 3
        data = b"\x0a\x14"

        with pytest.raises(DecodeError) as exc_info:
            decode_inspect(data, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None

        # print("Should have decoded 2 bytes before hitting end of stream")
        # print(format_tree(tree))

    def test_decode_nested_error_includes_tree(self):
        """Nested decoding errors should include an inspection tree."""

        class BadType:
            """A type that raises an error during decoding."""

            @property
            def size(self):
                return None

            def encode(self, _value, _stream, *, context):
                pass

            def decode(self, _stream, *, context):  # noqa: ARG002
                raise ValueError("Intentional decoding error")

        fmt = {"x": types.Int(byteorder="big", signed=False, size=1), "y": BadType()}
        data = b"\x01\x02"

        with pytest.raises(DecodeError) as exc_info:
            decode_inspect(data, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None

        # print("Should have decoded the first field successfully")
        # print(format_tree(tree))

    def test_decode_iterable_error_includes_tree(self):
        """Iterable decoding errors should include an inspection tree."""
        fmt = (
            types.Int(byteorder="big", signed=False, size=1),
            types.Int(byteorder="big", signed=False, size=1),
            types.Int(byteorder="big", signed=False, size=1),
        )
        # Only 2 bytes, but format expects 3
        data = b"\x0a\x14"

        with pytest.raises(DecodeError) as exc_info:
            decode_inspect(data, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None
        assert tree.offset == 0
        # Should have decoded 2 bytes before hitting end of stream
        assert len(tree.children) == 2
        assert tree.children[0].key == 0
        assert tree.children[0].value == 10
        assert tree.children[1].key == 1
        assert tree.children[1].value == 20


class TestInspectionTreeFormatting:
    """Test that inspection trees can be formatted properly."""

    def test_format_tree_from_encode_error(self):
        """Inspection trees from encode errors should be formattable."""
        fmt = {
            "a": types.Int(byteorder="big", signed=False, size=1),
            "b": types.Int(byteorder="big", signed=False, size=1),
            "c": types.Int(byteorder="big", signed=False, size=1),
        }
        obj = {"a": 10, "b": 20}

        with pytest.raises(EncodeError) as exc_info:
            encode_inspect(obj, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None

        # print("Should have encoded 2 bytes before hitting missing field 'c'")
        # print(format_tree(tree))

        # Should be able to format the inspection tree
        formatted = format_tree(tree)
        assert formatted is not None
        assert len(formatted) > 0
        # Should show the format used
        assert "Mapping" in formatted

    def test_format_tree_from_decode_error(self):
        """Trees from decode errors should be formattable."""
        fmt = {
            "a": types.Int(byteorder="big", signed=False, size=2),
            "b": types.Int(byteorder="big", signed=False, size=2),
        }
        # Only 2 bytes, but format expects 4
        data = b"\x00\x01"

        with pytest.raises(DecodeError) as exc_info:
            decode_inspect(data, fmt)

        tree = exc_info.value.inspect_node
        assert tree is not None

        # print("Should have decoded 2 bytes before hitting end of stream")
        # print(format_tree(tree))

        formatted = format_tree(tree)
        assert formatted is not None
        assert len(formatted) > 0
        assert "Mapping" in formatted
