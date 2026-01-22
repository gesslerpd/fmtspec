from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any

from msgspec import Struct, field

from ._core import decode_stream, encode_stream

if TYPE_CHECKING:
    from ._protocol import Format, InspectNode


class ViewNode(Struct, kw_only=True, gc=False):
    key: str | int | None
    buffer: memoryview
    offset: int
    size: int
    children: list[ViewNode]
    fmt: Format
    _map: dict[str | int | None, ViewNode] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "_map", {child.key: child for child in self.children})

    def __getitem__(self, key):
        return self._map[key]

    @property
    def data(self) -> Any:
        return bytes(self.buffer)

    @data.setter
    def data(self, value: Any) -> None:
        self.buffer[:] = value

    @property
    def value(self) -> Any:
        return decode_stream(
            BytesIO(self.buffer),
            self.fmt,
        )

    @value.setter
    def value(self, value: Any) -> None:
        stream = BytesIO()
        encode_stream(value, stream, self.fmt)
        self.buffer[:] = stream.getbuffer()


def dataview(node: InspectNode) -> ViewNode:
    """Get a memoryview for the data of an inspection node.

    Args:
        node: The inspection node to get the view for.
    """
    data = node.data
    data = bytearray(data)  # enable mutable buffer
    buffer = memoryview(data)
    return _dataview(node, buffer)


# FUTURE: InspectNode is very similar to ViewNode, consider merging them (keeping the mutable behavior of ViewNode)
def _dataview(node: InspectNode, buffer: memoryview) -> ViewNode:
    return ViewNode(
        key=node.key,
        buffer=buffer[node.offset : node.offset + node.size],
        offset=node.offset,
        size=node.size,
        children=[_dataview(child, buffer) for child in node.children],
        fmt=node.fmt,
    )
