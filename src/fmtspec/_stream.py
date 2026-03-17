"""Stream encoding and decoding functions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, BinaryIO

# keep this file stdlib/protocol-only to avoid circular imports

if TYPE_CHECKING:
    from ._protocol import Context, Format, InspectNode
    from .types import Bitfields


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


# FUTURE: what should this be? use a sentinel object?
# None is used for root but could be reused as default key
# format_tree knows what the root is
DEFAULT_KEY = None


def _encode_stream(  # noqa: PLR0912
    obj: Any,
    fmt: Format,
    stream: BinaryIO,
    *,
    context: Context,
    key: str | int | None = DEFAULT_KEY,
) -> InspectNode | None:
    """Encode object to stream, optionally returning inspection node."""
    context.fmt = fmt

    with context.inspect_scope(stream, key, fmt, obj) as node:
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


def _decode_stream(  # noqa: PLR0912, PLR0915
    stream: BinaryIO,
    fmt: Format,
    *,
    context: Context,
    key: str | int | None = DEFAULT_KEY,
) -> tuple[Any, InspectNode | None]:
    """Decode object from stream, optionally returning inspection node."""
    context.fmt = fmt

    with context.inspect_scope(stream, key, fmt, None) as node:
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
