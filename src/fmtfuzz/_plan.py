"""Validated, reusable plans compiled from fmtspec format objects."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fmtspec.types import (
    Array,
    Bitfield,
    Bitfields,
    Bytes,
    Float,
    Int,
    Lazy,
    Literal,
    Null,
    Optional,
    Ref,
    Sized,
    Str,
    Switch,
    TaggedUnion,
    TakeUntil,
)

from ._metadata import FormatNode, describe_format

if TYPE_CHECKING:
    from types import EllipsisType

type FormatPath = tuple[str | int, ...]
type DependencyKind = str
type _Scope = tuple[FormatPath, Mapping[Any, Any]]
_DEFAULT_MAX_DEPTH = 64
_MAX_HINT_WEIGHT = 32


class FormatPlanError(TypeError):
    """Raised when a format cannot be represented by a reusable fuzz plan."""


@dataclass(frozen=True, slots=True)
class FieldHint:
    """Preferred values for a scalar field, sampled alongside ordinary values."""

    values: tuple[Any, ...]
    weight: int = 1

    def __post_init__(self) -> None:
        values = tuple(self.values)
        if not values:
            raise ValueError("FieldHint requires at least one value")
        if not 1 <= self.weight <= _MAX_HINT_WEIGHT:
            raise ValueError(f"FieldHint weight must be between 1 and {_MAX_HINT_WEIGHT}")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class FormatDependency:
    """A field dependency discovered while compiling a format."""

    source_path: FormatPath
    target_path: FormatPath
    relation: DependencyKind
    parent: int


@dataclass(frozen=True, slots=True)
class FormatPlanNode:
    """One planned format node with its value path and semantic children."""

    path: FormatPath
    key: Any
    role: str
    kind: str
    fmt: Any
    size: int | EllipsisType | None
    choices: tuple[Any, ...] = ()
    children: tuple[FormatPlanNode, ...] = ()
    recursive: bool = False


@dataclass(frozen=True, slots=True, eq=False)
class FormatPlan:
    """Reusable structural view and dependency graph for an fmtspec format.

    The source format must not be mutated after compilation. Plans are explicit
    snapshots of its structure and do not use a hidden identity-based cache.
    """

    fmt: Any
    root: FormatPlanNode
    dependencies: tuple[FormatDependency, ...]
    field_hints: tuple[tuple[FormatPath, FieldHint], ...] = ()

    def nodes(self):
        """Yield this plan's nodes in depth-first wire order."""
        yield from _walk_nodes(self.root)

    def hint_for(self, path: FormatPath) -> FieldHint | None:
        return next((hint for hint_path, hint in self.field_hints if hint_path == path), None)


def _walk_nodes(node: FormatPlanNode):
    yield node
    for child in node.children:
        yield from _walk_nodes(child)


def _kind(fmt: Any) -> str:  # noqa: PLR0911, PLR0912
    if isinstance(fmt, Mapping):
        return "mapping"
    if isinstance(fmt, (list, tuple)):
        return "sequence"
    if isinstance(fmt, Int):
        return "integer"
    if isinstance(fmt, Float):
        return "float"
    if isinstance(fmt, Bytes):
        return "bytes"
    if isinstance(fmt, Str):
        return "string"
    if isinstance(fmt, Literal):
        return "literal"
    if isinstance(fmt, Null):
        return "null"
    if isinstance(fmt, Optional):
        return "optional"
    if isinstance(fmt, Bitfield):
        return "bitfield"
    if isinstance(fmt, Bitfields):
        return "bitfields"
    if isinstance(fmt, Array):
        return "array"
    if isinstance(fmt, Sized):
        return "sized"
    if isinstance(fmt, Switch):
        return "switch"
    if isinstance(fmt, TaggedUnion):
        return "tagged_union"
    if isinstance(fmt, TakeUntil):
        return "take_until"
    if isinstance(fmt, Lazy):
        return "lazy"
    if isinstance(fmt, Iterable):
        return "sequence"
    return f"{type(fmt).__module__}.{type(fmt).__qualname__}"


def _choices(fmt: Any) -> tuple[Any, ...]:
    if isinstance(fmt, Int) and fmt.enum is not None:
        return tuple(fmt.enum)
    if isinstance(fmt, Literal):
        return (fmt.value,)
    if isinstance(fmt, Switch):
        return tuple(fmt.cases)
    if isinstance(fmt, TaggedUnion):
        return tuple(fmt.fmt_by_tag)
    return ()


def _child_path(path: FormatPath, child: FormatNode) -> FormatPath:
    if child.role in ("field", "item"):
        return (*path, child.key)
    if child.role == "element":
        return (*path, "*")
    return path


def _references(fmt: Any) -> tuple[tuple[str, Ref], ...]:
    references: list[tuple[str, Ref]] = []
    if isinstance(fmt, Sized) and isinstance(fmt.length, Ref):
        references.append(("length", fmt.length))
    if isinstance(fmt, Array):
        references.extend(("dimension", dim) for dim in fmt.dims if isinstance(dim, Ref))
    if isinstance(fmt, Switch) and isinstance(fmt.key, Ref):
        references.append(("switch", fmt.key))
    if isinstance(fmt, TaggedUnion) and isinstance(fmt.tag, Ref):
        references.append(("tag", fmt.tag))
    return tuple(references)


def _compile_node(
    node: FormatNode,
    path: FormatPath,
    scopes: tuple[_Scope, ...],
    dependencies: list[FormatDependency],
) -> FormatPlanNode:
    fmt = node.fmt
    next_scopes = (*scopes, (path, fmt)) if isinstance(fmt, Mapping) else scopes
    for relation, ref in _references(fmt):
        if ref.parent < 1 or ref.parent > len(next_scopes):
            raise FormatPlanError(
                f"{relation} reference {ref!r} at {path!r} has no enclosing mapping scope"
            )
        target_scope_path, target_scope = next_scopes[-ref.parent]
        if ref.key not in target_scope:
            raise FormatPlanError(
                f"{relation} reference {ref!r} at {path!r} targets no field "
                f"in mapping {target_scope_path!r}"
            )
        dependencies.append(
            FormatDependency(
                source_path=path,
                target_path=(*target_scope_path, ref.key),
                relation=relation,
                parent=ref.parent,
            )
        )

    children = tuple(
        _compile_node(
            child,
            _child_path(path, child),
            next_scopes,
            dependencies,
        )
        for child in node.children
    )
    return FormatPlanNode(
        path=path,
        key=node.key,
        role=node.role,
        kind=_kind(fmt),
        fmt=fmt,
        size=node.size,
        choices=_choices(fmt),
        children=children,
        recursive=node.recursive,
    )


def _valid_hint(fmt: Any, value: Any) -> bool:  # noqa: PLR0911
    if isinstance(fmt, Int):
        bits = fmt.size * 8
        minimum = -(1 << (bits - 1)) if fmt.signed else 0
        maximum = (1 << (bits - (1 if fmt.signed else 0))) - 1
        if not isinstance(value, int) or not minimum <= value <= maximum:
            return False
        return fmt.enum is None or any(int(member) == value for member in fmt.enum)
    if isinstance(fmt, Float):
        return isinstance(value, float) and math.isfinite(value)
    if isinstance(fmt, Bytes):
        return isinstance(value, bytes) and (fmt.size is None or len(value) == fmt.size)
    if isinstance(fmt, Str):
        if not isinstance(value, str):
            return False
        try:
            return fmt.size is None or len(value.encode(fmt.encoding)) == fmt.size
        except (LookupError, UnicodeEncodeError):
            return False
    if isinstance(fmt, Literal):
        return value == fmt.value
    if isinstance(fmt, Null):
        return value is None
    if isinstance(fmt, Bitfield):
        return isinstance(value, (bool, int)) and 0 <= int(value) <= fmt.mask
    return False


def compile_format(
    fmt: Any,
    *,
    field_hints: Mapping[FormatPath, FieldHint | tuple[Any, ...]] | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> FormatPlan:
    """Compile an fmtspec format into a reusable, validated structural plan."""
    if isinstance(fmt, FormatPlan):
        if field_hints is None and max_depth == _DEFAULT_MAX_DEPTH:
            return fmt
        fmt = fmt.fmt

    metadata = describe_format(fmt, max_depth=max_depth)
    dependencies: list[FormatDependency] = []
    root = _compile_node(metadata, (), (), dependencies)
    normalized_hints: list[tuple[FormatPath, FieldHint]] = []
    if field_hints is not None:
        field_nodes = {
            node.path: node for node in _walk_nodes(root) if node.role in ("field", "item")
        }
        for path, hint in field_hints.items():
            if not isinstance(path, tuple):
                raise TypeError("field hint paths must be tuples")
            try:
                node = field_nodes[path]
            except KeyError as exc:
                raise FormatPlanError(
                    f"Field hint path {path!r} does not identify a field"
                ) from exc
            normalized = hint if isinstance(hint, FieldHint) else FieldHint(tuple(hint))
            invalid = [value for value in normalized.values if not _valid_hint(node.fmt, value)]
            if invalid:
                raise FormatPlanError(
                    f"Field hint values {invalid!r} are invalid for {node.kind} field {path!r}"
                )
            normalized_hints.append((path, normalized))

    return FormatPlan(
        fmt=fmt,
        root=root,
        dependencies=tuple(dependencies),
        field_hints=tuple(normalized_hints),
    )
