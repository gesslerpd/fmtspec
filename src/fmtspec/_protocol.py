"""Core types and context for serialization."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from types import EllipsisType
from typing import Any, BinaryIO, Protocol

from msgspec import Struct, field


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
    data: bytes
    value: Any
    offset: int
    size: int = 0
    children: list[InspectNode] = field(default_factory=list)

    def __post_init__(self):
        if not self.size:
            self.size = len(self.data)

    def __repr__(self) -> str:
        children_repr = f", children=[...] * {len(self.children)}" if self.children else ""
        return (
            f"FormatNode(key={self.key!r}, fmt={self.fmt!r}, "
            f"offset={self.offset}, size={self.size}, value={self.value!r}{children_repr})"
        )


# FUTURE: remove gc=False optimization, lower risk for this
class Context(Struct, gc=False):
    """Serialization context passed to types.

    Provides parent stack for sibling field access (e.g., Switch).

    Attributes:
        parents: Stack of parent objects for accessing sibling fields.
        fmt: Current format being processed (for error reporting).
        path: Stack tracking the current path (field names/indices) during serialization.
        inspect: Whether to build an inspection tree.
        inspect_node: Root node of the inspection tree, if enabled.
        inspect_children: Internal list for managing children during inspection.
    """

    parents: deque[Any] = field(default_factory=lambda: deque(({},)))
    path: deque[str | int] = field(default_factory=deque)
    fmt: Format | None = None
    inspect: bool = False
    inspect_node: InspectNode | None = None
    # FUTURE: is this needed? Can we just use inspect_node.children?
    inspect_children: list[InspectNode] | None = None

    def push(self, parent: Any) -> None:
        self.parents.append(parent)

    def pop(self) -> None:
        self.parents.pop()

    def push_path(self, key: str | int) -> None:
        self.path.append(key)

    def pop_path(self) -> None:
        self.path.pop()


class Type(Protocol):
    """Protocol for serializable types.

    Types receive a stream for I/O and a context for parent references.
    The context allows types like Switch to reference sibling fields.

    Attributes:
        size: The fixed byte size of this type, or None if variable/greedy.
              This is a convention, not enforced by the protocol due to
              runtime_checkable limitations with property variance.
    """

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None: ...
    def decode(self, stream: BinaryIO, *, context: Context) -> Any: ...


type Format = Type | Mapping[str, Format] | Iterable[Format]

# int: static
# EllipsisType: dynamic
# None: greedy
type Size = int | EllipsisType | None
