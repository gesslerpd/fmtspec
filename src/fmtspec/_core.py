import inspect
from collections.abc import Buffer, Iterator, Mapping
from io import BytesIO
from typing import Any, BinaryIO, assert_never, get_type_hints, overload

import msgspec

from ._exceptions import DecodeError, EncodeError
from ._protocol import Context, Format
from ._stream import _decode_stream, _encode_stream
from ._utils import derive_fmt

# types for msgspec to preserve during to_builtin / convert calls
# FUTURE: allow disabling to_builtins call so advanced users can call themselves?
BUILTIN_TYPES = (
    # disable base64 conversion for bytes-like types
    bytes,
    bytearray,
    memoryview,
    # ... add more as needed
)


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


def _to_builtins(obj: Any, recursive: bool = True) -> Any:
    try:
        return msgspec.to_builtins(obj, builtin_types=BUILTIN_TYPES)
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


def _convert[T](obj: Any, shape: type[T], recursive: bool = True) -> T:
    try:
        return msgspec.convert(obj, shape, builtin_types=BUILTIN_TYPES)
    except msgspec.ValidationError:
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


def encode_stream(obj: Any, stream: BinaryIO, fmt: Format | None = None) -> None:
    """Encode formatted object into a binary stream.

    If `fmt` is None, attempt to derive the format from the object's class
    using `derive_fmt`.
    """
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
    ctx = Context()
    try:
        _encode_stream(obj, fmt, stream, context=ctx)
    except EncodeError as e:  # pragma: no cover
        assert_never(e)  # type: ignore
        raise
    except Exception as e:
        raise EncodeError(
            message=f"Error encoding: {e}",
            fmt=ctx.fmt,
            context=ctx.parents[-1],
            cause=e,
            path=tuple(ctx.path),
            inspect_node=None,
        ) from e


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
    # derive format from the provided shape when not given
    if fmt is None:
        if shape is None:
            raise TypeError("Either fmt or shape must be provided for decoding.")
        fmt = derive_fmt(shape)
    # FUTURE: reenable generic Annotated formats?
    # else:
    #     fmt = _normalize_format(fmt)

    ctx = Context()
    try:
        result, _ = _decode_stream(stream, fmt, context=ctx)
    except DecodeError as e:  # pragma: no cover
        assert_never(e)  # type: ignore
        raise
    except Exception as e:
        raise DecodeError(
            message=f"Error decoding: {e}",
            fmt=ctx.fmt,
            context=ctx.parents[-1],
            cause=e,
            path=tuple(ctx.path),
            inspect_node=None,
        ) from e
    # perf: only recursively convert once as post-process operation
    if shape is not None:
        # FUTURE: enable recursive to support standard classes?
        result = _convert(result, shape, recursive=False)
    return result


def encode(obj: Any, fmt: Format | None = None) -> bytes:
    """Encode formatted object into bytes."""
    stream = BytesIO()
    encode_stream(obj, stream, fmt=fmt)
    return stream.getvalue()


@overload
def decode[T](data: Buffer, fmt: Format | None = None, *, shape: type[T]) -> T: ...


@overload
def decode(data: Buffer, fmt: Format | None = None, *, shape: None = None) -> Any: ...


def decode[T](data: Buffer, fmt: Format | None = None, *, shape: type[T] | None = None) -> T | Any:
    """Decode bytes into formatted object."""
    return decode_stream(BytesIO(data), fmt=fmt, shape=shape)
