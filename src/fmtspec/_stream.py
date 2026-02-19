"""Stream encoding and decoding functions."""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Buffer, Iterable, Mapping
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

from ._protocol import Context, Format, InspectNode

# keep this file stdlib/protocol-only to avoid circular imports

if TYPE_CHECKING:
    from .types import Bitfields


class StreamWrapper(Protocol):
    """Protocol for stream wrappers with byte extraction."""

    def get_bytes(self, start: int, end: int) -> bytes:
        """Extract bytes from buffer at the given offsets."""
        ...


class ReadStream:
    __slots__ = (
        "_read",
        "_readinto",
    )

    def __init__(self, stream: BinaryIO) -> None:
        self._read = stream.read
        self._readinto = getattr(stream, "readinto", None)

    # perf: force positional-only to avoid unnecessary kwargs parsing overhead in hot paths
    def read_exactly(self, size: int, /) -> bytes:
        # perf: pre-allocate and fill via readinto to avoid per-chunk allocations
        out = bytearray(size)
        mv = memoryview(out)
        try:
            n = 0
            readinto = self._readinto
            if readinto is None:
                read = self._read
                while n < size:
                    chunk = read(size - n)
                    if not chunk:
                        raise EOFError(f"Expected {size} bytes, got {n}")
                    chunk_size = len(chunk)
                    n_next = n + chunk_size
                    mv[n:n_next] = chunk
                    n = n_next
            else:
                while n < size:
                    got = readinto(mv[n:])
                    if not got:
                        raise EOFError(f"Expected {size} bytes, got {n}")
                    n += got
        finally:
            mv.release()
        return out


class WriteStream:
    __slots__ = ("_write",)

    def __init__(self, stream: BinaryIO) -> None:
        self._write = stream.write

    # perf: force positional-only to avoid unnecessary kwargs parsing
    def write_all(self, data: Buffer, /) -> None:
        total = len(data)
        write = self._write
        n = write(data)
        if n < total:
            # FUTURE: optimize by only writing part of remaining data? based on the first `n` value?
            mv = memoryview(data)
            while n < total:
                written = write(mv[n:])
                n += written
            mv.release()


class ProtoBytesIO(BytesIO):
    """Fastpath stream protocol BytesIO wrapper."""

    # perf: force positional-only to avoid unnecessary kwargs parsing
    def read_exactly(self, size: int, /) -> bytes:
        data = self.read(size)
        data_size = len(data)
        if data_size != size:
            raise EOFError(f"Expected {size} bytes, got {data_size}")
        return data

    # perf: force positional-only to avoid unnecessary kwargs parsing
    def write_all(self, data: Buffer, /) -> None:
        self.write(data)


class BufferingStream:
    """Wrapper stream that buffers read bytes for inspection.

    Works with both seekable and unseekable streams by capturing
    all bytes read during inspection mode.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._buffer = bytearray()
        # Track the initial position of the underlying stream
        try:
            self._start_offset = stream.tell()
        except (AttributeError, OSError):
            self._start_offset = 0

    def read(self, size: int = -1) -> bytes:
        """Read bytes and append to buffer."""
        data = self._stream.read(size)
        self._buffer.extend(data)
        return data

    def tell(self) -> int:
        """Return the current position relative to start."""
        return self._start_offset + len(self._buffer)

    def seek(self, offset: int, whence: int = 0) -> int:
        """Seek the underlying stream when supported."""
        return self._stream.seek(offset, whence)

    def get_bytes(self, start: int, end: int) -> bytes:
        """Extract bytes from buffer at the given offsets."""
        # with memoryview(self._buffer) as mv:
        #     data = mv[start:end]
        # return bytes(data)
        # memoryview is cheap to create and avoids intermediate bytearray slice copy
        return bytes(memoryview(self._buffer)[start:end])


class WriteBufferingStream:
    """Wrapper stream that buffers written bytes for inspection.

    Works with both seekable and unseekable streams by capturing
    all bytes written during inspection mode.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._buffer = bytearray()
        # Track the initial position of the underlying stream
        try:
            self._start_offset = stream.tell()
        except (AttributeError, OSError):
            self._start_offset = 0

    def write(self, data: Buffer) -> int:
        """Write bytes to stream and append to buffer."""
        result = self._stream.write(data)
        # perf: extend avoids reallocating a new bytearray
        # perf: `.extend(data)` is slightly faster than `+= data`
        self._buffer.extend(data)  # type: ignore[arg-type]
        return result

    def tell(self) -> int:
        """Return the current position relative to start."""
        return self._start_offset + len(self._buffer)

    def get_bytes(self, start: int, end: int) -> bytes:
        """Extract bytes from buffer at the given offsets."""
        relative_start = start - self._start_offset
        relative_end = end - self._start_offset
        # with memoryview(self._buffer) as mv:
        #     data = mv[relative_start:relative_end]
        # return bytes(data)
        # memoryview is cheap to create and avoids intermediate bytearray slice copy
        return bytes(memoryview(self._buffer)[relative_start:relative_end])


def _collect_bitfield_groups(fmt: Mapping) -> dict[str | int, Bitfields]:
    """Collect contiguous Bitfield groups from a mapping format.

    Returns a mapping `groups` from the group's start key to a `Bitfields`
    instance.
    """
    # import locally to avoid circular import at module load
    # TODO: refactor to avoid circular imports
    from .types import Bitfield, Bitfields  # noqa: PLC0415

    groups = {}

    items_iter = iter(fmt.items())
    pending: tuple[str, object] | None = None

    while True:
        # obtain next (key, fmt) pair, using pending if present
        if pending is not None:
            key, field_fmt = pending
            pending = None
        else:
            try:
                key, field_fmt = next(items_iter)
            except StopIteration:
                break

        if not isinstance(field_fmt, Bitfield):
            continue

        # start a new group at this Bitfield
        start = key
        group: dict = {key: field_fmt}
        if field_fmt.align:
            forced_size = field_fmt.align
        else:
            forced_size = 0

        # consume following items until we hit a Bitfield that specifies align
        while True:
            try:
                k, f = next(items_iter)
            except StopIteration:
                break

            if isinstance(f, Bitfield) and f.align is None:
                group[k] = f
                continue

            # not part of this group; save for next loop iteration
            pending = (k, f)
            break

        groups[start] = Bitfields(fields=group, size=forced_size)

    return groups


def _get_stream_bytes(stream: BinaryIO, start: int, end: int) -> bytes:
    get_bytes = getattr(stream, "get_bytes", None)
    if get_bytes:
        return get_bytes(start, end)
    if type(stream) is BytesIO:
        return bytes(stream.getbuffer()[start:end])  # type: ignore
    raise TypeError(f"Cannot extract bytes from {type(stream)}")


def _inspect_leaf(
    stream: BinaryIO,
    context: Context,
    key: str | int | None,
    fmt: Format,
    value: Any,
    start: int,
    *,
    prepend: bool = False,
) -> None:
    """Create a leaf InspectNode and append it to the current children list.

    Useful when a Type manually calls ``fmt.encode()`` / ``fmt.decode()``
    (bypassing ``_encode_stream`` / ``_decode_stream``) but still needs an
    inspection entry.  No-op when inspection is disabled.

    Args:
        stream: The binary stream being read/written.
        context: Serialization context with inspect state.
        key: Field name, index, or descriptive key for the node.
        fmt: The format specification used.
        value: The Python value encoded/decoded.
        start: Stream offset *before* the encode/decode call.
        prepend: If True, insert at position 0 instead of appending.
    """
    if not context.inspect:
        return
    data = _get_stream_bytes(stream, start, stream.tell())
    node = InspectNode(
        key=key,
        fmt=fmt,
        data=data,
        value=value,
        offset=start,
    )
    if prepend:
        context.inspect_children.appendleft(node)
    else:
        context.inspect_children.append(node)


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
        data=b"",
        value=value,
        offset=start_offset,
        children=children,
    )

    context.inspect_children = children

    yield node

    end_offset = stream.tell()
    data = _get_stream_bytes(stream, start_offset, end_offset)
    node.data = data
    node.size = len(data)

    context.inspect_children = parent_children
    if parent_children is not None:
        parent_children.append(node)


def _inspect_scope(
    stream: BinaryIO,
    context: Context,
    key,
    fmt,
    value,
    /,
):
    """Full-featured context manager for InspectNode lifecycle management.

    Fast no-op when context.inspect is False. Handles:
    - Node creation with data/size population
    - Children scope management (context.inspect_children)
    - Auto-append to parent's children list
    - Optional root node tracking (context.inspect_node)

    The yielded node's `value` attribute can be updated after creation,
    useful for decode operations where the value isn't known upfront.

    Args:
        stream: The binary stream being read/written.
        context: Serialization context with inspect state.
        key: Field name, index, or None for root nodes.
        fmt: The format specification for this node.
        value: Initial value (can be None, updated via node.value later).
        track_root: If True and context.inspect_node is None, sets it to this node.

    Usage (Type classes - intermediate nodes):
        with _inspect_scope(stream, context, i, self, value) as node:
            # recursive encode/decode...
            if node:
                node.value = decoded_result

    """
    # perf: fast no-op when inspection is disabled
    if context.inspect:
        return _inspect_scope_inner(stream, context, key, fmt, value)
    return NULL_CTX


# FUTURE: what should this be? use a sentinel object?
# None is used for root but could be reused as default key
# format_tree knows what the root is
DEFAULT_KEY = None


def _encode_stream(
    obj: Any,
    fmt: Format,
    stream: BinaryIO,
    *,
    context: Context,
    key: str | int | None = DEFAULT_KEY,
) -> InspectNode | None:
    """Encode object to stream, optionally returning inspection node."""
    context.fmt = fmt

    with _inspect_scope(stream, context, key, fmt, obj) as node:
        if context.inspect and not context.inspect_node:
            # track root node if not already set
            context.inspect_node = node

        fmt_type = type(fmt)

        # type guard for str.encode / bytes.encode (also iterable)
        if fmt_type is bytes or fmt_type is str:
            raise TypeError(f"Unsupported format type: {fmt_type}")

        # perf: prefer attribute/type checks over `isinstance` against Protocol
        encode_fn = getattr(fmt, "encode", None)
        if encode_fn:
            encode_fn(obj, stream, context=context)

        # perf: use type check for common case of dict
        elif fmt_type is dict or isinstance(fmt, Mapping):
            context.push(obj)

            # support MapPrefill protocol for auto-populating sibling fields
            for prefill_key, prefill_fmt in fmt.items():
                prefill_fn = getattr(prefill_fmt, "prefill", None)
                if prefill_fn:
                    context.push_path(prefill_key)
                    try:
                        prefill_fn(context=context)
                    finally:
                        context.pop_path()

            # preprocess to autodetect Bitfield inlays and build a member->group map
            bitfields = _collect_bitfield_groups(fmt)
            bitfields_remaining = 0

            for inner_key, field_fmt in fmt.items():
                # if this key is part of a bitfield group
                if inner_key in bitfields:
                    _field_fmt = bitfields[inner_key]
                    bitfields_remaining = len(_field_fmt.fields) - 1
                    value = {k: obj[k] for k in _field_fmt.fields}
                elif bitfields_remaining:
                    bitfields_remaining -= 1
                    # this member was encoded with its group; skip
                    continue
                else:
                    _field_fmt = field_fmt
                    context.fmt = _field_fmt
                    if getattr(field_fmt, "constant", False):
                        value = obj.get(inner_key)
                    else:
                        value = obj[inner_key]
                context.push_path(inner_key)
                _encode_stream(value, _field_fmt, stream, context=context, key=inner_key)
                context.pop_path()
            context.pop()

        # perf: use type check for common case of list/tuple
        elif fmt_type is list or fmt_type is tuple or isinstance(fmt, Iterable):
            for idx, (value, field_fmt) in enumerate(zip(obj, fmt, strict=True)):
                context.push_path(idx)
                _encode_stream(value, field_fmt, stream, context=context, key=idx)
                context.pop_path()

        else:
            raise TypeError(f"Unsupported format type: {fmt_type}")

    return node


def _decode_stream(  # noqa: PLR0912
    stream: BinaryIO,
    fmt: Format,
    *,
    context: Context,
    key: str | int | None = DEFAULT_KEY,
) -> tuple[Any, InspectNode | None]:
    """Decode object from stream, optionally returning inspection node."""
    context.fmt = fmt

    with _inspect_scope(stream, context, key, fmt, None) as node:
        if context.inspect and not context.inspect_node:
            # track root node if not already set
            context.inspect_node = node

        fmt_type = type(fmt)

        # type guard for str.encode / bytes.encode (also iterable)
        if fmt_type is bytes or fmt_type is str:
            raise TypeError(f"Unsupported format type: {fmt_type}")

        # perf: prefer attribute/type checks over `isinstance` against Protocol
        decode_fn = getattr(fmt, "decode", None)
        if decode_fn:
            result = decode_fn(stream, context=context)
            # post-populate the node value
            if node:
                node.value = result

        # perf: use type check for common case of dict
        elif fmt_type is dict or isinstance(fmt, Mapping):
            result = {}
            context.push(result)

            # pre-populate the node value (container)
            if node:
                node.value = result

            # preprocess to autodetect Bitfield inlays and build member->group map
            bitfields = _collect_bitfield_groups(fmt)
            bitfields_remaining = 0
            greedy_fmts = {}

            for inner_key, field_fmt in fmt.items():
                # use sizeof to recursively detect greedy fields?
                if getattr(field_fmt, "size", ...) is None:
                    greedy_fmts[inner_key] = field_fmt
                # detect consecutive greedy fields which would otherwise
                # consume the remainder of the stream ambiguously
                if len(greedy_fmts) > 1:
                    raise ValueError("multiple greedy items in mapping format")

                # if this key is part of a bitfield group
                if inner_key in bitfields:
                    bitfields_fmt = bitfields[inner_key]
                    bitfields_remaining = len(bitfields_fmt.fields) - 1
                    # decode the combined group and distribute values
                    context.push_path(inner_key)
                    value = _decode_stream(
                        stream, fmt=bitfields_fmt, context=context, key=inner_key
                    )[0]
                    # value is a mapping of the group's member values
                    for k, v in value.items():
                        result[k] = v
                    context.pop_path()
                elif bitfields_remaining:
                    bitfields_remaining -= 1
                    # member already decoded as part of its group; skip
                    continue
                else:
                    context.push_path(inner_key)
                    value = _decode_stream(stream, fmt=field_fmt, context=context, key=inner_key)[0]
                    result[inner_key] = value
                    context.pop_path()

            context.pop()

        # perf: use type check for common case of list/tuple
        elif fmt_type is list or fmt_type is tuple or isinstance(fmt, Iterable):
            result = []

            # pre-populate the node value (container)
            if node:
                node.value = result

            for idx, field_fmt in enumerate(fmt):
                context.push_path(idx)
                value = _decode_stream(stream, fmt=field_fmt, context=context, key=idx)[0]
                result.append(value)
                context.pop_path()

        else:
            raise TypeError(f"Unsupported format type: {fmt_type}")

    return result, node
