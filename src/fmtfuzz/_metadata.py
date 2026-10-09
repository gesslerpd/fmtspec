"""Structure metadata helpers for fmtspec formats."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import EllipsisType
from typing import Any, Protocol

from msgspec import Struct

from fmtspec.types import (
    Array,
    Bitfields,
    Lazy,
    Optional,
    Ref,
    Sized,
    Switch,
    TaggedUnion,
    TakeUntil,
)
from fmtspec.types._converter import Converter

type Size = int | EllipsisType | None


class FormatChild(Struct, frozen=True, kw_only=True, gc=False):
    """A child format exposed by a composite format type."""

    key: Any
    role: str
    fmt: Any


class FormatMetadata(Protocol):
    """Optional metadata hook for composite formats inspected by fmtfuzz."""

    def __fmtfuzz_children__(self) -> Iterable[FormatChild]:
        """Return the child formats exposed by this format."""


class FormatNode(Struct, frozen=True, kw_only=True, gc=False):
    """A format and its statically inspectable child formats."""

    key: Any
    role: str
    fmt: Any
    size: Size
    children: tuple[FormatNode, ...] = ()
    recursive: bool = False


def _format_children(fmt: Any) -> tuple[FormatChild, ...]:  # noqa: PLR0911, PLR0912
    metadata_method = getattr(fmt, "__fmtfuzz_children__", None)
    if callable(metadata_method):
        children = tuple(metadata_method())
        if any(not isinstance(child, FormatChild) for child in children):
            raise TypeError("__fmtfuzz_children__ must return FormatChild instances")
        return children

    if isinstance(fmt, Mapping):
        return tuple(FormatChild(key=key, role="field", fmt=child) for key, child in fmt.items())
    if isinstance(fmt, (str, bytes)):
        raise TypeError(f"Unsupported format type: {type(fmt)}")
    if isinstance(fmt, Iterable) and not callable(getattr(fmt, "encode", None)):
        return tuple(
            FormatChild(key=index, role="item", fmt=child) for index, child in enumerate(fmt)
        )
    if isinstance(fmt, Array):
        children = [
            FormatChild(key=index, role="dimension", fmt=dimension)
            for index, dimension in enumerate(fmt.dims)
            if not isinstance(dimension, (int, Ref))
        ]
        children.append(FormatChild(key=None, role="element", fmt=fmt.element_fmt))
        return tuple(children)
    if isinstance(fmt, Sized):
        children = []
        if not isinstance(fmt.length, (int, Ref)):
            children.append(FormatChild(key=None, role="length", fmt=fmt.length))
        children.append(FormatChild(key=None, role="inner", fmt=fmt.fmt))
        return tuple(children)
    if isinstance(fmt, (Optional, TakeUntil)):
        return (FormatChild(key=None, role="inner", fmt=fmt.fmt),)
    if isinstance(fmt, Switch):
        children = [
            FormatChild(key=key, role="case", fmt=child) for key, child in fmt.cases.items()
        ]
        if fmt.default is not None:
            children.append(FormatChild(key=None, role="default", fmt=fmt.default))
        return tuple(children)
    if isinstance(fmt, TaggedUnion):
        children = []
        if not isinstance(fmt.tag, Ref):
            children.append(FormatChild(key=None, role="tag", fmt=fmt.tag))
        children.extend(
            FormatChild(key=tag, role="case", fmt=child) for tag, child in fmt.fmt_by_tag.items()
        )
        return tuple(children)
    if isinstance(fmt, Bitfields):
        return (FormatChild(key=None, role="fields", fmt=fmt.fmt),)
    if isinstance(fmt, Converter) and not isinstance(fmt.fmt, Ref):
        return (FormatChild(key=None, role="inner", fmt=fmt.fmt),)
    if isinstance(fmt, Lazy):
        return (FormatChild(key=None, role="inner", fmt=fmt.get_format()),)
    return ()


def _format_size(current: Any, children: tuple[FormatNode, ...]) -> Size:
    encode_fn = getattr(current, "encode", None)
    decode_fn = getattr(current, "decode", None)
    if isinstance(current, Mapping) or (isinstance(current, Iterable) and not callable(encode_fn)):
        total = 0
        for child in children:
            if child.size is None or child.size is ...:
                return child.size
            total += child.size
        return total
    if callable(encode_fn) and callable(decode_fn):
        return getattr(current, "size", ...)
    raise TypeError(f"Unsupported format type for describe_format: {type(current)}")


def _build_format_node(
    node: FormatChild,
    ancestors: frozenset[int],
    depth: int,
    max_depth: int,
) -> FormatNode:
    current = node.fmt
    if id(current) in ancestors:
        return FormatNode(
            key=node.key,
            role=node.role,
            fmt=current,
            size=getattr(current, "size", ...),
            recursive=True,
        )

    encode_fn = getattr(current, "encode", None)
    metadata_method = getattr(current, "__fmtfuzz_children__", None)
    if isinstance(current, Iterator) and not callable(encode_fn) and not callable(metadata_method):
        raise TypeError("describe_format requires reusable iterable format specifications")
    child_formats = _format_children(current)
    if depth >= max_depth and child_formats:
        raise ValueError(f"Format nesting exceeds max_depth={max_depth}")
    next_ancestors = ancestors | {id(current)}
    children = tuple(
        _build_format_node(child, next_ancestors, depth + 1, max_depth) for child in child_formats
    )
    return FormatNode(
        key=node.key,
        role=node.role,
        fmt=current,
        size=_format_size(current, children),
        children=children,
    )


def describe_format(fmt: Any, *, max_depth: int = 64) -> FormatNode:
    """Describe an fmtspec format as a cycle-aware metadata tree.

    Built-in composite types expose semantic child roles such as ``field``,
    ``element``, ``dimension``, and ``case``. Custom composite ``Type``
    implementations can implement ``__fmtfuzz_children__`` and return
    ``FormatChild`` values. A recursive reference is represented by a node
    with ``recursive=True`` and no expanded children.
    """
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    root = FormatChild(key=None, role="root", fmt=fmt)
    return _build_format_node(root, frozenset(), 0, max_depth)
