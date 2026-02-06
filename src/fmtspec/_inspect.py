"""Inspection utilities for encode/decode operations.

Provides functions to capture a tree of serialization information
including field names, formats, raw bytes, and values.
"""

from __future__ import annotations

from collections.abc import Buffer, Iterable, Iterator, Mapping
from io import BytesIO
from typing import TYPE_CHECKING, Any, overload

from ._core import _decode_stream_impl, _encode_stream_impl

if TYPE_CHECKING:
    from ._dataview import ViewNode
    from ._protocol import Format, InspectNode


def encode_inspect(obj: Any, fmt: Format) -> tuple[bytes, InspectNode]:
    """Encode formatted object into bytes with inspection.

    Returns a tuple of (encoded_bytes, inspection_tree).

    Args:
        obj: The Python object to encode.
        fmt: The format specification.

    Returns:
        A tuple containing:
        - bytes: The encoded binary data.
        - FormatNode: A tree capturing the serialization structure.

    Example:
        >>> data, tree = encode_inspect({"x": 1, "y": 2}, {"x": u1, "y": u1})
        >>> print(format_tree(tree))
    """
    stream = BytesIO()
    tree = _encode_stream_impl(obj, stream, fmt, inspect=True)
    return stream.getvalue(), tree


@overload
def decode_inspect[T](data: Buffer, fmt: Format, *, shape: type[T]) -> tuple[T, InspectNode]: ...


@overload
def decode_inspect(data: Buffer, fmt: Format, *, shape: None = None) -> tuple[Any, InspectNode]: ...


def decode_inspect[T](
    data: Buffer, fmt: Format, *, shape: type[T] | None = None
) -> tuple[T | Any, InspectNode]:
    """Decode bytes into formatted object with inspection.

    Returns a tuple of (decoded_object, inspection_tree).

    Args:
        data: The binary data to decode.
        fmt: The format specification.
        shape: Optional type to convert the result to (using msgspec).

    Returns:
        A tuple containing:
        - Any: The decoded Python object.
        - FormatNode: A tree capturing the deserialization structure.

    Example:
        >>> result, tree = decode_inspect(b"\\x01\\x02", {"x": u1, "y": u1})
        >>> print(format_tree(tree))
    """
    stream = BytesIO(data)
    return _decode_stream_impl(stream, fmt, shape=shape, inspect=True)


def format_tree(  # noqa: PLR0913
    node: InspectNode | ViewNode,
    *,
    indent: str = "  ",
    show_data: bool = True,
    max_data_bytes: int = 24,
    only_leaf: bool = True,
    max_depth: int = -1,
) -> str:
    """Format an inspection tree as a human-readable string.

    Args:
        node: The root FormatNode to format.
        indent: String used for each indentation level.
        show_data: Whether to include raw bytes in the output.
        max_data_bytes: Maximum number of bytes to show (truncated with ...).
        only_leaf: Whether to show values/data for only leaf nodes.
        max_depth: Maximum depth to display. If -1, display all levels.

    Returns:
        A formatted string representation of the tree.

    Example:
        >>> data, tree = encode_inspect({"x": 1, "y": 2}, {"x": u1, "y": u1})
        >>> print(format_tree(tree))
        [root] @ 0-2 (2 bytes)
          ├─ [x] @ 0-1 (1 bytes)
          │    value: 1
          │    data: 01
          └─ [y] @ 1-2 (1 bytes)
                value: 2
                data: 02
    """
    is_root = node.key is None
    return "\n".join(
        _format_node(
            node,
            # add subtree prefix for non-root nodes
            prefix="" if is_root else "... ",
            is_last=False,
            is_root=is_root,
            indent=indent,
            show_data=show_data,
            max_data_bytes=max_data_bytes,
            only_leaf=only_leaf,
            max_depth=max_depth,
        )
    )


def _format_node(  # noqa: PLR0913
    node: InspectNode | ViewNode,
    prefix: str,
    is_last: bool,
    is_root: bool,
    indent: str,
    show_data: bool,
    max_data_bytes: int,
    only_leaf: bool,
    max_depth: int,
) -> Iterator[str]:
    """Recursively format a node and its children."""
    # FUTURE: if not is_root and not node.key is None
    # should we flatten those nodes? and have them not contribute to depth?

    # Determine the name display
    if is_root:
        lookup_key = "*"
    else:
        lookup_key = f"[{node.key}]"

    # Format type name
    fmt_name = _get_format_name(node.fmt)

    # Build the header line
    end_offset = node.offset + node.size
    length = f" ({len(node.children)} items)" if node.children else ""
    header = f"{lookup_key} {fmt_name} @ [{node.offset}:{end_offset}] ({node.size} bytes){length}"

    if is_root:
        yield f"{prefix}{header}"
        child_prefix = prefix
    else:
        connector = "└─ " if is_last else "├─ "
        yield f"{prefix}{connector}{header}"
        child_prefix = prefix + ("   " if is_last else "│  ")

    depth_limit = max_depth == 0

    if not node.children or not only_leaf or depth_limit:
        sub_indent = indent
        if node.children:
            sub_indent = "│" + indent[1:]
        # Add value line
        value_repr = _format_repr(repr(node.value), limit=64)
        yield f"{child_prefix}{sub_indent}value: {value_repr}"

        # Add data line if requested
        if show_data and node.data:
            data_hex = _format_hex(node.data, limit=max_data_bytes)
            yield f"{child_prefix}{sub_indent}data: {data_hex}"

    if depth_limit and node.children:
        # collapsed due to depth limit
        yield f"{child_prefix}└─ ..."
        yield child_prefix
    else:
        # Recurse into children
        last_index = len(node.children) - 1
        for i, child in enumerate(node.children):
            yield from _format_node(
                child,
                prefix=child_prefix,
                is_last=i == last_index,
                is_root=False,
                indent=indent,
                show_data=show_data,
                max_data_bytes=max_data_bytes,
                only_leaf=only_leaf,
                max_depth=max_depth - 1,
            )


def _get_format_name(fmt: Format) -> str:
    """Get a short display name for a format."""
    if isinstance(fmt, Mapping):
        return "Mapping"
    elif isinstance(fmt, Iterable):
        return "Iterable"
    return type(fmt).__name__


def _format_hex(data: bytes, limit: int) -> str:
    """Format bytes as hex string, truncating if necessary."""
    if len(data) <= limit:
        return data.hex(b" ")
    truncated = data[:limit]
    return truncated.hex(b" ") + " ... (truncated)"


def _format_repr(s: str, limit: int) -> str:
    """Truncate a string representation if too long."""
    if len(s) <= limit:
        return s
    return s[:limit] + " ... (truncated)"
