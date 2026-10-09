"""Validated, reusable plans compiled from fmtspec format objects."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
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
_MAX_ENUM_WEIGHT = 32


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
class FieldRange:
    """Inclusive hard bounds for values generated at one integer field."""

    min_value: int | None = None
    max_value: int | None = None

    def __post_init__(self) -> None:
        for name, value in (("min_value", self.min_value), ("max_value", self.max_value)):
            if value is not None and type(value) is not int:
                raise TypeError(f"{name} must be an integer or None")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("FieldRange minimum cannot exceed its maximum")

    def contains(self, value: Any) -> bool:
        return (
            isinstance(value, int)
            and (self.min_value is None or value >= self.min_value)
            and (self.max_value is None or value <= self.max_value)
        )


@dataclass(frozen=True, slots=True)
class EnumPolicy:
    """Relative sampling weights for declared and undefined enum values."""

    known_weight: int = 1
    unknown_weight: int = 1

    def __post_init__(self) -> None:
        for name, weight in (
            ("known_weight", self.known_weight),
            ("unknown_weight", self.unknown_weight),
        ):
            if type(weight) is not int or not 0 <= weight <= _MAX_ENUM_WEIGHT:
                raise ValueError(f"{name} must be between 0 and {_MAX_ENUM_WEIGHT}")
        if not self.known_weight and not self.unknown_weight:
            raise ValueError("EnumPolicy must give at least one value category nonzero weight")


@dataclass(frozen=True, slots=True)
class FieldDerivation:
    """Pure callback for deriving one field from explicitly named values."""

    dependencies: tuple[FormatPath, ...]
    derive: Callable[[Mapping[FormatPath, Any]], Any]

    def __post_init__(self) -> None:
        dependencies = tuple(self.dependencies)
        if any(not isinstance(path, tuple) for path in dependencies):
            raise TypeError("FieldDerivation dependency paths must be tuples")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("FieldDerivation dependency paths must be unique")
        if not callable(self.derive):
            raise TypeError("FieldDerivation derive must be callable")
        object.__setattr__(self, "dependencies", dependencies)

    def apply(self, values: Mapping[FormatPath, Any]) -> Any:
        """Call the derivation with a read-only view of its input values."""
        return self.derive(MappingProxyType(dict(values)))


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
    field_ranges: tuple[tuple[FormatPath, FieldRange], ...] = ()
    enum_policies: tuple[tuple[FormatPath, EnumPolicy], ...] = ()
    field_derivations: tuple[tuple[FormatPath, FieldDerivation], ...] = ()

    def nodes(self):
        """Yield this plan's nodes in depth-first wire order."""
        yield from _walk_nodes(self.root)

    def hint_for(self, path: FormatPath) -> FieldHint | None:
        return next((hint for hint_path, hint in self.field_hints if hint_path == path), None)

    def range_for(self, path: FormatPath) -> FieldRange | None:
        return next(
            (field_range for range_path, field_range in self.field_ranges if range_path == path),
            None,
        )

    def enum_policy_for(self, path: FormatPath) -> EnumPolicy:
        return next(
            (policy for policy_path, policy in self.enum_policies if policy_path == path),
            EnumPolicy(),
        )

    def derivation_for(self, path: FormatPath) -> FieldDerivation | None:
        return next(
            (
                derivation
                for derivation_path, derivation in self.field_derivations
                if derivation_path == path
            ),
            None,
        )


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
        return isinstance(value, int) and minimum <= value <= maximum
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


def compile_format(  # noqa: PLR0912, PLR0913, PLR0915
    fmt: Any,
    *,
    field_hints: Mapping[FormatPath, FieldHint | tuple[Any, ...]] | None = None,
    field_ranges: Mapping[FormatPath, FieldRange] | None = None,
    enum_policies: Mapping[FormatPath, EnumPolicy] | None = None,
    field_derivations: Mapping[FormatPath, FieldDerivation] | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> FormatPlan:
    """Compile an fmtspec format into a reusable, validated structural plan."""
    if isinstance(fmt, FormatPlan):
        if (
            field_hints is None
            and field_ranges is None
            and enum_policies is None
            and field_derivations is None
            and max_depth == _DEFAULT_MAX_DEPTH
        ):
            return fmt
        previous = fmt
        fmt = fmt.fmt
        field_hints = field_hints if field_hints is not None else dict(previous.field_hints)
        field_ranges = field_ranges if field_ranges is not None else dict(previous.field_ranges)
        enum_policies = enum_policies if enum_policies is not None else dict(previous.enum_policies)
        field_derivations = (
            field_derivations if field_derivations is not None else dict(previous.field_derivations)
        )

    metadata = describe_format(fmt, max_depth=max_depth)
    dependencies: list[FormatDependency] = []
    root = _compile_node(metadata, (), (), dependencies)
    field_nodes = {node.path: node for node in _walk_nodes(root) if node.role in ("field", "item")}
    normalized_hints: list[tuple[FormatPath, FieldHint]] = []
    if field_hints is not None:
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

    normalized_ranges: list[tuple[FormatPath, FieldRange]] = []
    if field_ranges is not None:
        for path, field_range in field_ranges.items():
            if not isinstance(path, tuple):
                raise TypeError("field range paths must be tuples")
            try:
                node = field_nodes[path]
            except KeyError as exc:
                raise FormatPlanError(
                    f"Field range path {path!r} does not identify a field"
                ) from exc
            if not isinstance(field_range, FieldRange):
                raise TypeError(f"Field range at {path!r} must be a FieldRange")
            if isinstance(node.fmt, Int):
                bits = node.fmt.size * 8
                minimum = -(1 << (bits - 1)) if node.fmt.signed else 0
                maximum = (1 << (bits - (1 if node.fmt.signed else 0))) - 1
            elif isinstance(node.fmt, Bitfield):
                minimum, maximum = 0, node.fmt.mask
            else:
                raise FormatPlanError(
                    f"Field range at {path!r} requires an integer or bitfield field"
                )
            if (field_range.min_value is not None and field_range.min_value < minimum) or (
                field_range.max_value is not None and field_range.max_value > maximum
            ):
                raise FormatPlanError(
                    f"Field range {field_range!r} is not representable by field {path!r}"
                )
            normalized_ranges.append((path, field_range))

    normalized_enum_policies: list[tuple[FormatPath, EnumPolicy]] = []
    if enum_policies is not None:
        for path, policy in enum_policies.items():
            if not isinstance(path, tuple):
                raise TypeError("enum policy paths must be tuples")
            try:
                node = field_nodes[path]
            except KeyError as exc:
                raise FormatPlanError(
                    f"Enum policy path {path!r} does not identify a field"
                ) from exc
            if not isinstance(node.fmt, Int) or node.fmt.enum is None:
                raise FormatPlanError(
                    f"Enum policy at {path!r} requires an Int field with a declared enum"
                )
            if not isinstance(policy, EnumPolicy):
                raise TypeError(f"Enum policy at {path!r} must be an EnumPolicy")
            normalized_enum_policies.append((path, policy))

    normalized_derivations: list[tuple[FormatPath, FieldDerivation]] = []
    if field_derivations is not None:
        ordered_fields = tuple(node for node in _walk_nodes(root) if node.role in ("field", "item"))
        field_order = {node.path: index for index, node in enumerate(ordered_fields)}
        for path, derivation in field_derivations.items():
            if not isinstance(path, tuple):
                raise TypeError("field derivation paths must be tuples")
            if path not in field_nodes:
                raise FormatPlanError(f"Field derivation path {path!r} does not identify a field")
            if not isinstance(derivation, FieldDerivation):
                raise TypeError(f"Field derivation at {path!r} must be a FieldDerivation")
            if "*" in path:
                raise FormatPlanError("Field derivations cannot target repeated array elements")
            if any("*" in dependency for dependency in derivation.dependencies):
                raise FormatPlanError("Field derivations cannot depend on repeated array elements")
            for dependency_path in derivation.dependencies:
                if not isinstance(dependency_path, tuple):
                    raise TypeError("FieldDerivation dependency paths must be tuples")
                if dependency_path not in field_nodes:
                    raise FormatPlanError(
                        f"Field derivation dependency {dependency_path!r} at {path!r} "
                        "does not identify a field"
                    )
                if path[: len(dependency_path)] == dependency_path:
                    raise FormatPlanError(
                        f"Field derivation dependency {dependency_path!r} at {path!r} "
                        "is an enclosing field that is not available yet"
                    )
                if field_order[dependency_path] >= field_order[path]:
                    raise FormatPlanError(
                        f"Field derivation dependency {dependency_path!r} at {path!r} "
                        "must precede its target"
                    )
            normalized_derivations.append((path, derivation))
        normalized_derivations.sort(key=lambda item: field_order[item[0]])

    hint_paths = {path for path, _ in normalized_hints}
    derivation_paths = {path for path, _ in normalized_derivations}
    if hint_paths & derivation_paths:
        conflict = min(hint_paths & derivation_paths, key=repr)
        raise FormatPlanError(f"Field {conflict!r} cannot have both a hint and a derivation")

    return FormatPlan(
        fmt=fmt,
        root=root,
        dependencies=tuple(dependencies),
        field_hints=tuple(normalized_hints),
        field_ranges=tuple(normalized_ranges),
        enum_policies=tuple(normalized_enum_policies),
        field_derivations=tuple(normalized_derivations),
    )
