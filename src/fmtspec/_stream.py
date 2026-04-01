"""Stream encoding and decoding functions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, BinaryIO

from ._utils import _group_bitfields

if TYPE_CHECKING:
    from ._protocol import Context, Format, InspectNode

# keep this file stdlib/protocol-only to avoid circular imports


# FUTURE: what should this be? use a sentinel object?
# None is used for root but could be reused as default key
# format_tree knows what the root is
DEFAULT_KEY = None


def _encode_stream(  # noqa: PLR0912
    stream: BinaryIO,
    obj: Any,
    fmt: Format,
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
            encode_fn(stream, obj, context=context)

        # perf: use type check for common case of dict
        elif fmt_type is dict or isinstance(fmt, Mapping):
            fmt = _group_bitfields(fmt)
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

            for inner_key, field_fmt in fmt.items():
                if getattr(field_fmt, "inline", False):
                    _field_fmt = field_fmt
                    context.fmt = _field_fmt
                    value = {k: obj[k] for k in field_fmt.fmt.keys()}
                else:
                    _field_fmt = field_fmt
                    context.fmt = _field_fmt
                    if getattr(field_fmt, "constant", False):
                        value = obj.get(inner_key)
                    else:
                        value = obj[inner_key]
                context.push_path(inner_key)
                _encode_stream(stream, value, _field_fmt, context=context, key=inner_key)
                context.pop_path()
            context.pop()

        # perf: use type check for common case of list/tuple
        elif fmt_type is list or fmt_type is tuple or isinstance(fmt, Iterable):
            for idx, (value, field_fmt) in enumerate(zip(obj, fmt, strict=True)):
                context.push_path(idx)
                _encode_stream(stream, value, field_fmt, context=context, key=idx)
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
            fmt = _group_bitfields(fmt)
            result = {}
            context.push(result)

            # pre-populate the node value (container)
            if node:
                node.value = result

            greedy_fmts = {}

            for inner_key, field_fmt in fmt.items():
                # use sizeof to recursively detect greedy fields?
                if getattr(field_fmt, "size", ...) is None:
                    greedy_fmts[inner_key] = field_fmt
                # detect consecutive greedy fields which would otherwise
                # consume the remainder of the stream ambiguously
                if len(greedy_fmts) > 1:
                    raise ValueError("multiple greedy items in mapping format")

                if getattr(field_fmt, "inline", False):
                    context.push_path(inner_key)
                    value = _decode_stream(stream, fmt=field_fmt, context=context, key=inner_key)[0]
                    for k, v in value.items():
                        result[k] = v
                    context.pop_path()
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
