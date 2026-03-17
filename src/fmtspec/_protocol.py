"""Core types and context for serialization."""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Iterable, Mapping
from types import EllipsisType
from typing import Any, BinaryIO, Protocol

from msgspec import Struct, field

# keep this file stdlib-only to avoid circular imports


# FUTURE: remove gc=False optimization, higher risk for this
# FUTURE: remove kw_only=True for performance?
class InspectNode(Struct, kw_only=True, gc=False):
    """A node in the inspection tree representing a serialization step.

    Attributes:
        key: Field name (for mappings), index (for iterables), or None for root.
        fmt: The format specification used for this node.
        data: Raw bytes read/written for this node (including children).
        value: The Python value encoded/decoded.
        offset: Byte offset in the stream where this node starts.
        size: Number of bytes consumed by this node (including children).
        children: Child nodes for nested structures.
    """

    key: str | int | None
    fmt: Format
    value: Any
    # FUTURE: use start/end offsets instead of offset/size?
    offset: int
    size: int = 0
    children: deque[InspectNode] = field(default_factory=deque)
    buffer: memoryview | None = None
    _map: dict[str | int | None, InspectNode] | None = None
    _data: bytes | None = None

    @property
    def data(self) -> bytes:
        buffer = self.buffer
        if buffer is None:
            raise RuntimeError("InspectNode buffer is not attached")
        if self._data is None:
            self._data = bytes(buffer)
        return self._data

    def __getitem__(self, key: str | int | None) -> InspectNode:
        node_map = self._map
        if node_map is None:
            node_map = {child.key: child for child in self.children}
            self._map = node_map
        return node_map[key]

    def __repr__(self) -> str:
        children_repr = f", children=[...] * {len(self.children)}" if self.children else ""
        return (
            f"InspectNode(key={self.key!r}, fmt={self.fmt!r}, "
            f"offset={self.offset}, size={self.size}, value={self.value!r}{children_repr})"
        )


# FUTURE: consider allowing mutable data/value properties on InspectNode
# this causes a large nested binary backed and value sync issue.
# class ViewNode(Struct, kw_only=True, gc=False):
#     key: str | int | None
#     buffer: memoryview
#     offset: int
#     size: int
#     children: list[ViewNode]
#     fmt: Format
#     _map: dict[str | int | None, ViewNode] = field(default_factory=dict)

#     def __post_init__(self):
#         object.__setattr__(self, "_map", {child.key: child for child in self.children})

#     def __getitem__(self, key):
#         return self._map[key]

#     @property
#     def data(self) -> Any:
#         return bytes(self.buffer)

#     @data.setter
#     def data(self, value: Any) -> None:
#         self.buffer[:] = value

#     @property
#     def value(self) -> Any:
#         return decode_stream(
#             BytesIO(self.buffer),
#             self.fmt,
#         )

#     @value.setter
#     def value(self, value: Any) -> None:
#         stream = BytesIO()
#         encode_stream(value, stream, self.fmt)
#         self.buffer[:] = stream.getbuffer()


NULL_CTX = contextlib.nullcontext()


@contextlib.contextmanager
def _inspect_scope_inner(
    stream: BinaryIO,
    context: Context,
    key,
    fmt,
    value,
    /,
):
    parent_children = context.inspect_children
    children: deque[InspectNode] = deque()

    start_offset = stream.tell()
    node = InspectNode(
        key=key,
        fmt=fmt,
        value=value,
        offset=start_offset,
        children=children,
    )

    context.inspect_children = children

    yield node

    end_offset = stream.tell()
    node.size = end_offset - start_offset

    context.inspect_children = parent_children
    if parent_children is not None:
        parent_children.append(node)


# FUTURE: remove gc=False optimization, lower risk for this
class Context(Struct, gc=False):
    """Serialization context passed to types.

    Provides parent stack for sibling field access (e.g., Switch).

    Attributes:
        parents: Stack of parent objects for accessing sibling fields.
        fmt: Current format being processed (for error reporting).
        path: Stack tracking the current path (field names/indices) during serialization.
        store: Store options/state in dictionary for use between formats.
        inspect: Whether to build an inspection tree.
        inspect_node: Root node of the inspection tree, if enabled.
        inspect_children: Internal list for managing children during inspection.
    """

    parents: deque[Any] = field(default_factory=lambda: deque(({},)))
    path: deque[str | int] = field(default_factory=deque)
    fmt: Format | None = None
    store: dict[Any, Any] = field(default_factory=dict)
    inspect: bool = False
    inspect_node: InspectNode | None = None
    # FUTURE: is this needed? Can we just use inspect_node.children?
    inspect_children: deque[InspectNode] = field(default_factory=deque)

    def push(self, parent: Any) -> None:
        self.parents.append(parent)

    def pop(self) -> None:
        self.parents.pop()

    def push_path(self, key: str | int) -> None:
        self.path.append(key)

    def pop_path(self) -> None:
        self.path.pop()

    def inspect_leaf(
        self,
        stream: BinaryIO,
        key: str | int | None,
        fmt: Format,
        value: Any,
        start: int,
        *,
        prepend: bool = False,
    ) -> None:
        """Record a manually encoded or decoded leaf value in the inspection tree.

        This is mainly for custom ``Type`` implementations that directly call a
        child formatter's ``encode(...)`` or ``decode(...)`` method instead of
        delegating through ``fmtspec.stream.encode_stream(...)`` or
        ``fmtspec.stream.decode_stream(...)``. It is a no-op when inspection is
        disabled.

        Args:
            stream: The binary stream being read/written.
            key: Field name, index, or descriptive key for the node.
            fmt: The format specification used.
            value: The Python value encoded/decoded.
            start: Stream offset *before* the encode/decode call.
            prepend: If True, insert at position 0 instead of appending.

        Example:
            >>> from io import BytesIO
            >>> from fmtspec import Context, types
            >>> stream = BytesIO()
            >>> ctx = Context(inspect=True)
            >>> start = stream.tell()
            >>> types.u8.encode(7, stream, context=ctx)
            >>> ctx.inspect_leaf(stream, "count", types.u8, 7, start)
            >>> ctx.inspect_children[0].key
            'count'
        """
        if not self.inspect:
            return
        size = stream.tell() - start
        node = InspectNode(
            key=key,
            fmt=fmt,
            value=value,
            offset=start,
            size=size,
        )
        if prepend:
            self.inspect_children.appendleft(node)
        else:
            self.inspect_children.append(node)

    def inspect_scope(
        self,
        stream: BinaryIO,
        key,
        fmt,
        value,
        /,
    ):
        """Create an intermediate inspection node for nested custom logic.

        The returned context manager swaps ``inspect_children`` so nested work
        becomes children of the yielded node. When inspection is disabled, this
        returns a null context manager that yields ``None``.

        The yielded node's `value` attribute can be updated after creation,
        useful for decode operations where the value isn't known upfront.

        Args:
            stream: The binary stream being read/written.
            key: Field name, index, or None for root nodes.
            fmt: The format specification for this node.
            value: Initial value (can be None, updated via node.value later).

        Example:
            >>> from io import BytesIO
            >>> from fmtspec import Context, types
            >>> stream = BytesIO()
            >>> ctx = Context(inspect=True)
            >>> with ctx.inspect_scope(stream, "payload", types.bytes_, b"abc") as node:
            ...     types.bytes_.encode(b"abc", stream, context=ctx)
            >>> node.size
            3

        """
        # perf: fast no-op when inspection is disabled
        if self.inspect:
            return _inspect_scope_inner(stream, self, key, fmt, value)
        return NULL_CTX


class Type(Protocol):
    """Protocol for serializable types.

    Types receive a stream for I/O and a context for parent references.
    The context allows types like Switch to reference sibling fields.

    Attributes:
        size: The fixed byte size of this type, or None if variable/greedy.
              This is a convention, not enforced by the protocol due to
              runtime_checkable limitations with property variance.
    """

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:
        """Write ``value`` to ``stream`` using this format."""

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Read a value from ``stream`` using this format."""


class MapPrefill(Protocol):
    """Optional hook for types used inside mapping formats.

    Implement this to pre-populate sibling fields on the current parent mapping
    before ordered mapping encoding begins. This is useful when a type can
    derive a sibling value from its own field value.
    """

    def prefill(
        self,
        *,
        context: Context,
    ) -> None: ...


type Format = Type | Mapping[str, Format] | Iterable[Format]

# int: static
# EllipsisType: dynamic
# None: greedy
type Size = int | EllipsisType | None
