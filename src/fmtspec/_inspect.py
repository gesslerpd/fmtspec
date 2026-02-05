"""Inspection utilities for encode/decode operations.

Provides functions to capture a tree of serialization information
including field names, formats, raw bytes, and values.
"""

from __future__ import annotations

from collections.abc import Buffer, Iterable, Iterator, Mapping
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, assert_never, cast, overload

import msgspec

from ._core import _convert, _to_builtins
from ._exceptions import DecodeError, EncodeError
from ._protocol import Context, Format, InspectNode
from ._stream import BufferingStream, WriteBufferingStream, _decode_stream, _encode_stream

if TYPE_CHECKING:
    from ._dataview import ViewNode

# FUTURE: refactor to remove lots of duplication with _core encode/decode functions?


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
    tree = _encode_inspect_stream(obj, stream, fmt)
    return stream.getvalue(), tree


def _encode_inspect_stream(obj: Any, stream: BinaryIO, fmt: Format) -> InspectNode:
    # Convert iterators to lists first since msgspec.to_builtins doesn't support them
    if isinstance(obj, Iterator):
        obj = tuple(obj)

    # FUTURE: enable recursive to support standard classes?
    obj = _to_builtins(obj, recursive=False)

    # Wrap stream to capture bytes for inspection
    buffering_stream = WriteBufferingStream(stream)
    ctx = Context(inspect=True)
    try:
        tree = _encode_stream(obj, fmt, cast("BinaryIO", buffering_stream), context=ctx)
    except EncodeError as e:  # pragma: no cover
        assert_never(e)  # type: ignore
        raise
    except Exception as e:
        raise EncodeError(
            message=repr(e),
            obj=obj,
            stream=stream,
            fmt=ctx.fmt,
            context=ctx.parents[-1],
            cause=e,
            path=tuple(ctx.path),
            inspect_node=ctx.inspect_node,
        ) from e

    assert tree is not None  # inspect=True guarantees a return value
    return tree


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
    return _decode_inspect_stream(stream, fmt, shape=shape)


@overload
def _decode_inspect_stream[T](
    stream: BinaryIO, fmt: Format, *, shape: type[T]
) -> tuple[T, InspectNode]: ...


@overload
def _decode_inspect_stream(
    stream: BinaryIO, fmt: Format, *, shape: None = None
) -> tuple[Any, InspectNode]: ...


def _decode_inspect_stream[T](
    stream: BinaryIO, fmt: Format, *, shape: type[T] | None = None
) -> tuple[T | Any, InspectNode]:
    # Wrap stream to capture bytes for inspection
    buffering_stream = BufferingStream(stream)
    ctx = Context(inspect=True)
    try:
        result, tree = _decode_stream(cast("BinaryIO", buffering_stream), fmt, context=ctx)
    except DecodeError as e:  # pragma: no cover
        assert_never(e)  # type: ignore
        raise
    except Exception as e:
        # FUTURE: set to None and add deferred conversion attempt as method on DecodeError?
        context = ctx.parents[-1]
        obj = context
        if shape is not None:
            try:
                obj = _convert(context, shape, recursive=False)
            except msgspec.DecodeError:
                pass
        raise DecodeError(
            message=repr(e),
            obj=obj,
            stream=stream,
            fmt=ctx.fmt,
            context=context,
            cause=e,
            path=tuple(ctx.path),
            inspect_node=ctx.inspect_node,
        ) from e

    # narrow type
    assert tree is not None

    if shape is not None:
        # FUTURE: enable recursive to support standard classes?
        result = _convert(result, shape, recursive=False)

    return result, tree


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
    # Determine the name display
    if is_root:
        lookup_key = "*"
    elif isinstance(node.key, int):
        lookup_key = f"[{node.key}]"
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
