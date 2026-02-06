import inspect
import ipaddress
from collections.abc import Buffer, Iterator, Mapping
from copy import copy
from io import BytesIO
from typing import Any, BinaryIO, Literal, assert_never, cast, get_type_hints, overload

import msgspec

from ._exceptions import DecodeError, EncodeError, ShapeError
from ._protocol import Context, Format, InspectNode
from ._stream import (
    BufferingStream,
    WriteBufferingStream,
    _decode_stream,
    _encode_stream,
)
from ._utils import derive_fmt, sizeof

# types for msgspec to preserve during to_builtin / convert calls
# FUTURE: allow disabling to_builtins call so advanced users can call themselves?
BUILTIN_TYPES = (
    # disable base64 conversion for bytes-like types
    bytes,
    bytearray,
    memoryview,
    # ... add more as needed
)

# Types that should be completely preserved (not converted to dicts by msgspec)
# These are types with custom encode methods that handle their own serialization
PRESERVED_TYPES: list[type] = []


def register_builtin_type(cls: type) -> None:
    """Register a type to be preserved during to_builtins conversion.

    Types registered here won't be converted to dicts by msgspec.to_builtins.
    This is useful for custom types that implement their own encode/decode methods.

    Note: This only affects _to_builtins, not _convert. These types are preserved
    during encoding but should be handled by their own encode methods.
    """
    if cls not in PRESERVED_TYPES:
        PRESERVED_TYPES.append(cls)


INT_CONVERTIBLE_TYPES = (
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
)


def _fix_inspect_offsets(children: list[InspectNode], parent_offset: int) -> None:
    """Recursively fix offsets for children that came from sub-streams.

    Detects children whose offset is behind where the next contiguous byte
    should be (i.e. they were created against a ``BytesIO`` starting at 0)
    and shifts them so they are contiguous with preceding siblings.
    """
    next_offset = parent_offset
    for child in children:
        if child.offset < next_offset:
            shift = next_offset - child.offset
            child.offset = next_offset
            if child.children:
                _shift_children(child.children, shift)
        next_offset = child.offset + child.size
        if child.children:
            _fix_inspect_offsets(child.children, child.offset)


def _shift_children(children: list[InspectNode], shift: int) -> None:
    """Shift offsets of all nodes in a list by a fixed amount."""
    for node in children:
        node.offset += shift
        if node.children:
            _shift_children(node.children, shift)


def _create_new_instance[T](cls: type[T], data: dict[str, Any]) -> T:
    instance = cls.__new__(cls)

    # copy input so we can pop keys used for __init__
    remaining = dict(data)

    sig = inspect.signature(cls)
    # collect parameter names excluding 'self' and var-args
    init_param_names = [
        name
        for name, param in sig.parameters.items()
        if name != "self"
        and param.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    init_kwargs: dict[str, Any] = {}
    for name in init_param_names:
        if name in remaining:
            init_kwargs[name] = remaining.pop(name)

    # Call __init__ with the subset of provided data
    if init_kwargs:
        cls.__init__(instance, **init_kwargs)
    else:
        # If no kwargs matched, still attempt a no-arg __init__
        cls.__init__(instance)

    # Set any leftover items as attributes (handles renamed/mismatched names)
    for key, value in remaining.items():
        object.__setattr__(instance, key, value)

    return instance


def _msgspec_encode_hook(obj: Any) -> Any:
    if hasattr(obj, "to_builtins") and callable(obj.to_builtins):
        obj = obj.to_builtins()
    elif hasattr(obj, "__int__") and callable(obj.__int__):
        # generically support types convertable to int? use INT_CONVERTIBLE_TYPES?
        # if isinstance(obj, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        obj = int(obj)
    else:
        raise TypeError(f"Unsupported type for encoding hook: {type(obj)} ({obj})")
    return obj


def _msgspec_decode_hook(cls: type, obj: Any) -> Any:
    if hasattr(cls, "from_builtins") and callable(cls.from_builtins):
        obj = cls.from_builtins(obj)
    elif hasattr(cls, "__int__") and callable(cls.__int__) and isinstance(obj, int):
        # generically support types constructible from int? use INT_CONVERTIBLE_TYPES?
        # if issubclass(cls, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        obj = cls(obj)
    else:
        raise TypeError(f"Unsupported type for decoding hook: {cls} ({obj})")
    return obj


# def _preserve_types(obj: Any) -> Any:
#     """Recursively preserve registered types in collections.

#     This function walks through lists/tuples and replaces items that would
#     otherwise be converted to dicts by msgspec.to_builtins.
#     """
#     if not PRESERVED_TYPES:
#         return obj

#     preserved_tuple = tuple(PRESERVED_TYPES)

#     if isinstance(obj, preserved_tuple):
#         # Already a preserved type, return as-is
#         return obj
#     elif isinstance(obj, list):
#         # Check if any items are preserved types
#         result = []
#         for item in obj:
#             if isinstance(item, preserved_tuple):
#                 result.append(item)
#             else:
#                 result.append(_preserve_types(item))
#         return result
#     elif isinstance(obj, tuple):
#         return tuple(_preserve_types(item) for item in obj)
#     elif isinstance(obj, dict):
#         return {k: _preserve_types(v) for k, v in obj.items()}
#     return obj


def _to_builtins(obj: Any, recursive: bool) -> Any:
    # First, extract any preserved types from collections
    # These will be kept as-is while the rest is converted
    # preserved_items: list[tuple[list[int], Any]] = []

    # def extract_preserved(o: Any, path: list[int]) -> Any:
    #     """Extract preserved types from nested structure, replacing with placeholders."""
    #     if not PRESERVED_TYPES:
    #         return o

    #     preserved_tuple = tuple(PRESERVED_TYPES)

    #     if isinstance(o, preserved_tuple):
    #         # Mark this position for later restoration
    #         preserved_items.append((list(path), o))
    #         # Return a placeholder dict that won't cause issues
    #         return {"__preserved_index__": len(preserved_items) - 1}
    #     elif isinstance(o, list):
    #         return [extract_preserved(item, [*path, i]) for i, item in enumerate(o)]
    #     elif isinstance(o, tuple):
    #         return tuple(extract_preserved(item, [*path, i]) for i, item in enumerate(o))
    #     elif isinstance(o, dict):
    #         return {k: extract_preserved(v, path) for k, v in o.items()}
    #     return o

    # def restore_preserved(o: Any) -> Any:
    #     """Restore preserved types from placeholders."""
    #     if isinstance(o, dict) and "__preserved_index__" in o:
    #         idx = o["__preserved_index__"]
    #         return preserved_items[idx][1]
    #     elif isinstance(o, list):
    #         return [restore_preserved(item) for item in o]
    #     elif isinstance(o, tuple):
    #         return tuple(restore_preserved(item) for item in o)
    #     elif isinstance(o, dict):
    #         return {k: restore_preserved(v) for k, v in o.items()}
    #     return o

    # # Extract preserved types before conversion
    # obj_with_placeholders = extract_preserved(obj, [])

    try:
        result = msgspec.to_builtins(
            obj,
            builtin_types=BUILTIN_TYPES,
            enc_hook=None if recursive else _msgspec_encode_hook,
        )
        return result
        # Restore preserved types after conversion
        # return restore_preserved(result)
    except TypeError:
        if not recursive:
            raise
        types = get_type_hints(type(obj))
        if types:
            result = {}
            for k in types:
                result[k] = _to_builtins(getattr(obj, k), recursive=recursive)
            return result
    return obj


def _convert[T](obj: Any, shape: type[T], recursive: bool) -> T:
    try:
        return msgspec.convert(
            obj,
            shape,
            builtin_types=BUILTIN_TYPES,
            dec_hook=None if recursive else _msgspec_decode_hook,
        )
    except msgspec.DecodeError:
        if not recursive:
            raise
        # handle (fmt, shape) pairs that have mismatched types?
        # `strict=False` doesn't work, fallback to manual construction
        if isinstance(obj, Mapping):
            result = {}
            for k, y in obj.items():
                types = get_type_hints(shape)
                result[k] = _convert(y, types[k], recursive=recursive)
            return _create_new_instance(shape, result)
    return obj


@overload
def _encode_stream_impl(
    obj: Any, stream: BinaryIO, fmt: Format | None, *, inspect: Literal[False] = False
) -> None: ...


@overload
def _encode_stream_impl(
    obj: Any, stream: BinaryIO, fmt: Format | None, *, inspect: Literal[True]
) -> InspectNode: ...


def _encode_stream_impl(
    obj: Any, stream: BinaryIO, fmt: Format | None = None, *, inspect: bool = False
) -> InspectNode | None:
    # Convert iterators to lists first since msgspec.to_builtins doesn't support them
    if isinstance(obj, Iterator):
        obj = tuple(obj)

    if fmt is None:
        fmt = derive_fmt(type(obj))
    # FUTURE: reenable generic Annotated formats?
    # else:
    #     fmt = _normalize_format(fmt)

    # FUTURE: preprocess unsupported types with msgspec.convert(from_attributes=True)?

    # perf: only recursively convert once as pre-process operation
    # FUTURE: enable recursive to support standard classes?
    obj = _to_builtins(obj, recursive=False)

    ctx = Context(inspect=inspect)

    # Wrap stream to capture bytes for inspection
    if inspect:
        buffering_stream = WriteBufferingStream(stream)
        write_stream = cast("BinaryIO", buffering_stream)
    else:
        write_stream = stream

    try:
        # specify key=None for root node
        tree = _encode_stream(obj, fmt, write_stream, context=ctx, key=None)
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

    if tree:
        # FUTURE: do this for exceptions inspect_node too?
        _fix_inspect_offsets(tree.children, tree.offset)

    return tree


def encode_stream(obj: Any, stream: BinaryIO, fmt: Format | None = None) -> None:
    """Encode formatted object into a binary stream.

    If `fmt` is None, attempt to derive the format from the object's class
    using `derive_fmt`.
    """
    _encode_stream_impl(obj, stream, fmt, inspect=False)


@overload
def _decode_stream_impl[T](
    stream: BinaryIO, fmt: Format | None = None, *, shape: type[T], inspect: Literal[False] = False
) -> tuple[T, None]: ...


@overload
def _decode_stream_impl(
    stream: BinaryIO,
    fmt: Format | None = None,
    *,
    shape: None = None,
    inspect: Literal[False] = False,
) -> tuple[Any, None]: ...


@overload
def _decode_stream_impl[T](
    stream: BinaryIO, fmt: Format | None = None, *, shape: type[T], inspect: Literal[True]
) -> tuple[T, InspectNode]: ...


@overload
def _decode_stream_impl(
    stream: BinaryIO, fmt: Format | None = None, *, shape: None = None, inspect: Literal[True]
) -> tuple[Any, InspectNode]: ...


def _decode_stream_impl[T](
    stream: BinaryIO,
    fmt: Format | None = None,
    *,
    shape: type[T] | None = None,
    inspect: bool = False,
) -> tuple[T, InspectNode | None] | tuple[Any, InspectNode | None]:
    # derive format from the provided shape when not given
    if fmt is None:
        if shape is None:
            raise ValueError("Either fmt or shape must be provided for decoding.")
        fmt = derive_fmt(shape)

    # FUTURE: reenable generic Annotated formats?
    # else:
    #     fmt = _normalize_format(fmt)

    ctx = Context(inspect=inspect)

    # Wrap stream to capture bytes for inspection
    if inspect:
        buffering_stream = BufferingStream(stream)
        read_stream: BinaryIO = cast("BinaryIO", buffering_stream)
    else:
        read_stream = stream

    try:
        # specify key=None for root node
        result, tree = _decode_stream(read_stream, fmt, context=ctx, key=None)
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
    # perf: only recursively convert once as post-process operation
    if shape is not None:
        # FUTURE: enable recursive to support standard classes?
        try:
            result = _convert(result, shape, recursive=False)
        except msgspec.DecodeError as e:
            # FUTURE: rename ConvertError?
            raise ShapeError(
                message=f"Decoded object does not conform to expected shape {shape}: {e}",
                obj=result,
                stream=stream,
                fmt=fmt,
                # context empty here?
                context=result,
                cause=e,
                path=(),
                inspect_node=ctx.inspect_node,
            ) from e

    if tree:
        # FUTURE: do this for exceptions inspect_node too?
        _fix_inspect_offsets(tree.children, tree.offset)

    return result, tree


@overload
def decode_stream[T](stream: BinaryIO, fmt: Format | None = None, *, shape: type[T]) -> T: ...


@overload
def decode_stream(stream: BinaryIO, fmt: Format | None = None, *, shape: None = None) -> Any: ...


def decode_stream[T](
    stream: BinaryIO, fmt: Format | None = None, *, shape: type[T] | None = None
) -> T | Any:
    """Decode a binary stream into formatted object.

    If `fmt` is None, attempt to derive the format from `shape`.
    """
    return _decode_stream_impl(stream, fmt, shape=shape)[0]


def encode(obj: Any, fmt: Format | None = None) -> bytes:
    """Encode formatted object into bytes."""
    stream = BytesIO()
    encode_stream(obj, stream, fmt=fmt)
    return stream.getvalue()


@overload
def decode[T](
    data: Buffer, fmt: Format | None = None, *, shape: type[T], strict: bool = False
) -> T: ...


@overload
def decode(
    data: Buffer, fmt: Format | None = None, *, shape: None = None, strict: bool = False
) -> Any: ...


def decode[T](
    data: Buffer, fmt: Format | None = None, *, shape: type[T] | None = None, strict: bool = False
) -> T | Any:
    """Decode bytes into formatted object."""
    # do this here for greedy field preprocessing
    if fmt is None:
        if shape is None:
            raise ValueError("Either fmt or shape must be provided for decoding.")
        fmt = derive_fmt(shape)

    # if isinstance(fmt, Mapping):
    #     # preprocess to detect greedy field and wrap in Sized with fixed length
    #     fmt = _preprocess_greedy_fmt(data, fmt)
    stream = BytesIO(data)
    result = decode_stream(stream, fmt=fmt, shape=shape)
    # If requested, check for any trailing data after successful decode
    if strict:
        cur = stream.tell()
        end = stream.seek(0, 2)
        stream.seek(cur)
        remaining = end - cur
        if remaining:
            raise DecodeError(
                message=f"Excess data after decoding ({remaining} bytes)",
                obj=result,
                stream=stream,
                fmt=fmt,
                # context empty here?
                context=result,
                cause=None,
                path=(),
                inspect_node=None,
            )
    return result


def _preprocess_greedy_fmt(data, fmt):
    greedy_fmt_key = None
    pre_size = 0
    post_size = 0

    for key, field_fmt in fmt.items():
        size = sizeof(field_fmt)

        if isinstance(size, int):
            if greedy_fmt_key is None:
                pre_size += size
            else:
                post_size += size
        elif size is None:
            # FUTURE: both greedy / dynamic formats can be wrapped in Sized to limit their size?
            if greedy_fmt_key is not None:
                # clear so we know there's multiple greedy fields
                greedy_fmt_key = None
                break
            greedy_fmt_key = key
        else:
            # for now, give up if there's a dynamic size format
            # dynamic size - cannot preprocess
            greedy_fmt_key = None
            break

    if greedy_fmt_key is not None:
        from .types import Sized  # noqa: PLC0415

        fmt = copy(fmt)
        fixed_size = len(data) - pre_size - post_size
        if fixed_size < 0:
            raise ValueError("Data is smaller than expected fixed-size fields")
        fmt[greedy_fmt_key] = Sized(fixed_size, fmt[greedy_fmt_key])
    return fmt
