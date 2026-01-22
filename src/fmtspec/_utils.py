from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, get_args, get_origin, get_type_hints

if TYPE_CHECKING:
    from ._protocol import Format, Size


def sizeof(fmt: Format) -> Size:
    """Calculate the total byte size of a format.

    Args:
        fmt: A Type, Mapping (dict), or Iterable (tuple/list) format.

    Returns:
        The total fixed byte size, or None if the format is variable/greedy.

    Examples:
        >>> sizeof(Int(byteorder="big", signed=False, size=2))
        2
        >>> sizeof({"a": u1, "b": u2})  # 1 + 2 = 3
        3
        >>> sizeof(Bytes())  # greedy
        None
    """
    if hasattr(fmt, "size") and getattr(fmt, "encode", None) and getattr(fmt, "decode", None):
        return fmt.size  # type: ignore[attr-defined]

    if isinstance(fmt, Mapping):
        items = fmt.values()
    elif isinstance(fmt, Iterable):
        items = fmt
    else:
        raise TypeError(f"Unsupported format type for sizeof: {type(fmt)}")

    total = 0
    for item in items:
        item_size = sizeof(item)
        if item_size is None or item_size is ...:
            return item_size
        total += item_size
    return total


@cache
def derive_fmt(cls: type) -> dict[str, Format]:
    """Derive format specification from a class with Annotated fields.

    Args:
        cls: A class (dataclass or standard class) with fields annotated using typing.Annotated.

    Returns:
        A dictionary mapping field names to their format specifications.

    Examples:
        >>> @dataclass
        ... class Example:
        ...     name: Annotated[str, TerminatedString(b"\\0", encoding="utf-8")]
        ...     age: Annotated[int, Int(byteorder="little", signed=False, size=4)]
        >>> derive_fmt(Example)
        {'name': TerminatedString(...), 'age': Int(...)}
    """
    type_hints = get_type_hints(cls, include_extras=True)
    result: dict[str, Format] = {}

    for field_name, field_type in type_hints.items():
        origin = get_origin(field_type)

        # skip ClassVar fields
        if origin is ClassVar:
            continue

        # Handle Annotated types
        if origin is Annotated:
            args = get_args(field_type)
            fmt = _extract_format(args)
            if fmt is None:
                # No format found in annotations, recursively derive from the type
                result[field_name] = derive_fmt(args[0])
            else:
                result[field_name] = fmt
        else:
            # Recursively derive format for nested class types. If recursion
            # returns an empty mapping then the field has no associated
            # format (e.g. a plain `str`/`int` without Annotated metadata),
            # which is an error for deriving formats for composite types.
            nested = derive_fmt(field_type)
            if not nested:
                raise TypeError(
                    f"Cannot derive format for field '{field_name}' without an associated format type"
                )
            result[field_name] = nested

    return result


def _extract_format(metadata: tuple) -> Format | None:  # noqa: PLR0911
    """Extract format from metadata tuple, handling nested Annotated types.

    Args:
        metadata: Tuple of metadata items from Annotated type.

    Returns:
        The first valid Format found, or None if no format is found.
    """
    for item in metadata:
        # Check if item is a Type (has 'size' attribute)
        if callable(getattr(item, "encode", None)) and callable(getattr(item, "decode", None)):
            return item
        # Check if item is a Mapping (dict format)
        if isinstance(item, Mapping):
            return item
        # Check if item is a tuple/list format
        if isinstance(item, (Iterable, Iterator)) and not isinstance(item, str):
            return item
        # Check if item is itself an Annotated type (nested)
        # raise TypeError(f"Unsupported format type in Annotated metadata {item}")
        if get_origin(item) is Annotated:
            nested_args = get_args(item)
            nested_fmt = _extract_format(nested_args)
            if nested_fmt is not None:
                return nested_fmt
    return None


def _normalize_format(f: Any) -> Format:  # noqa: PLR0911
    """Normalize typing.Annotated and PEP 585 generics into runtime formats.

    Args:
        fmt: A format specification which may include typing.Annotated or PEP 585 generics.
    """
    origin = get_origin(f)
    # Annotated[T, metadata...]
    if origin is Annotated:
        args = get_args(f)
        extracted = _extract_format(args)
        if extracted is None:
            # fallback to the base type
            return _normalize_format(args[0])
        return extracted
    # PEP 585 generics like list[T], tuple[T, ...]
    if origin is list or origin is tuple:
        return [_normalize_format(a) for a in get_args(f)]
    if origin is dict:
        # dict[K, V] -> mapping style {k: v}
        args = get_args(f)
        if args:
            # represent as a single-item mapping to describe value format
            return {args[0]: _normalize_format(args[1])}
    return f
