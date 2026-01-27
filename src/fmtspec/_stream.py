"""Stream encoding and decoding functions."""

from __future__ import annotations

import contextlib
from collections.abc import Buffer, Iterable, Mapping
from io import BytesIO
from typing import Any, BinaryIO, Protocol

from ._protocol import Context, Format, InspectNode


class StreamWrapper(Protocol):
    """Protocol for stream wrappers with byte extraction."""

    def get_bytes(self, start: int, end: int) -> bytes:
        """Extract bytes from buffer at the given offsets."""
        ...


class BufferingStream:
    """Wrapper stream that buffers read bytes for inspection.

    Works with both seekable and unseekable streams by capturing
    all bytes read during inspection mode.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._buffer = bytearray()

    def read(self, size: int = -1) -> bytes:
        """Read bytes and append to buffer."""
        data = self._stream.read(size)
        self._buffer.extend(data)
        return data

    def tell(self) -> int:
        """Return the current position relative to start."""
        return len(self._buffer)

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


def _collect_bitfield_groups(fmt: dict):
    """Collect contiguous Bitfield groups from a mapping format.

    Returns a mapping `groups` from the group's start key to a `Bitfields`
    instance.
    """
    # import locally to avoid circular import at module load
    # TODO: refactor to avoid circular imports
    from .types import Bitfield, Bitfields  # noqa: PLC0415

    groups: dict = {}

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


@contextlib.contextmanager
def _populate_inspect_node(stream: BinaryIO, key, fmt, value, children):
    start_offset = stream.tell()
    node = InspectNode(
        key=key,
        fmt=fmt,
        data=b"",
        value=value,
        offset=start_offset,
        children=children,
    )
    yield node
    end_offset = stream.tell()
    # inline extraction of bytes for performance
    get_bytes = getattr(stream, "get_bytes", None)
    stream_type = type(stream)
    if get_bytes:
        data = get_bytes(start_offset, end_offset)
    elif stream_type is BytesIO:
        data = bytes(stream.getbuffer()[start_offset:end_offset])  # type: ignore
    else:
        raise TypeError(f"Cannot extract bytes from {stream_type}")
    node.data = data
    node.size = len(data)


def _encode_stream(  # noqa: PLR0912
    obj: Any,
    fmt: Format,
    stream: BinaryIO,
    *,
    context: Context,
    name: str | int | None = None,
) -> InspectNode | None:
    """Encode object to stream, optionally returning inspection node."""
    context.fmt = fmt
    children = []

    if context.inspect:
        inspect_ctx_manager = _populate_inspect_node(
            stream,
            key=name,
            fmt=fmt,
            value=obj,
            children=children,
        )
    else:
        inspect_ctx_manager = contextlib.nullcontext()

    with inspect_ctx_manager as node:
        if node and not context.inspect_node:
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

            # preprocess to autodetect Bitfield inlays and build a member->group map
            bitfields = _collect_bitfield_groups(fmt)
            bitfields_remaining = 0

            for key, field_fmt in fmt.items():
                # if this key is part of a bitfield group
                if key in bitfields:
                    _field_fmt = bitfields[key]
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
                        value = obj.get(key)
                    else:
                        value = obj[key]
                context.push_path(key)

                child = _encode_stream(value, _field_fmt, stream, context=context, name=key)
                if node:
                    children.append(child)
                context.pop_path()
            context.pop()

        # perf: use type check for common case of list/tuple
        elif fmt_type is list or fmt_type is tuple or isinstance(fmt, Iterable):
            for idx, (value, field_fmt) in enumerate(zip(obj, fmt, strict=True)):
                context.push_path(idx)
                child = _encode_stream(value, field_fmt, stream, context=context, name=idx)
                if node:
                    children.append(child)
                context.pop_path()

        else:
            raise TypeError(f"Unsupported format type: {fmt_type}")

    return node


def _decode_stream(  # noqa: PLR0912, PLR0915
    stream: BinaryIO,
    fmt: Format,
    *,
    context: Context,
    name: str | int | None = None,
) -> tuple[Any, InspectNode | None]:
    """Decode object from stream, optionally returning inspection node."""
    context.fmt = fmt
    children = []

    if context.inspect:
        inspect_ctx_manager = _populate_inspect_node(
            stream,
            key=name,
            fmt=fmt,
            value=None,
            children=children,
        )
    else:
        inspect_ctx_manager = contextlib.nullcontext()

    with inspect_ctx_manager as node:
        if node and not context.inspect_node:
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

            for key, field_fmt in fmt.items():
                # use sizeof to recursively detect greedy fields?
                if getattr(field_fmt, "size", ...) is None:
                    greedy_fmts[key] = field_fmt
                # detect consecutive greedy fields which would otherwise
                # consume the remainder of the stream ambiguously
                if len(greedy_fmts) > 1:
                    raise ValueError("multiple greedy items in mapping format")

                # if this key is part of a bitfield group
                if key in bitfields:
                    bitfields_fmt = bitfields[key]
                    bitfields_remaining = len(bitfields_fmt.fields) - 1
                    # decode the combined group and distribute values
                    context.push_path(key)
                    value, child = _decode_stream(
                        stream, fmt=bitfields_fmt, context=context, name=key
                    )
                    if node:
                        children.append(child)
                    # value is a mapping of the group's member values
                    for k, v in value.items():
                        result[k] = v
                    context.pop_path()
                elif bitfields_remaining:
                    bitfields_remaining -= 1
                    # member already decoded as part of its group; skip
                    continue
                else:
                    context.push_path(key)
                    value, child = _decode_stream(stream, fmt=field_fmt, context=context, name=key)
                    if node:
                        children.append(child)
                    result[key] = value
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
                value, child = _decode_stream(stream, fmt=field_fmt, context=context, name=idx)
                if node:
                    children.append(child)
                result.append(value)
                context.pop_path()

        else:
            raise TypeError(f"Unsupported format type: {fmt_type}")

    return result, node
