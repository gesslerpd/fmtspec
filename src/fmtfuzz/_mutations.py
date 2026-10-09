"""Format-aware valid mutations and inspection-guided wire mutations."""

from __future__ import annotations

import random
import string
from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from typing import Any

from msgspec import Struct, to_builtins

from fmtspec import (
    DecodeError,
    Error,
    ExcessDecodeError,
    InspectNode,
    decode,
    decode_inspect,
    encode,
)
from fmtspec.types import (
    Array,
    Bitfield,
    Bitfields,
    Bytes,
    Float,
    Int,
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

from ._plan import FormatPlan, FormatPlanNode, compile_format

_NO_CHANGE = object()


def _replacement(fmt: Any, value: Any, rng: random.Random) -> Any:  # noqa: PLR0911, PLR0912
    if isinstance(fmt, Int):
        bits = fmt.size * 8
        minimum = -(1 << (bits - 1)) if fmt.signed else 0
        maximum = (1 << (bits - (1 if fmt.signed else 0))) - 1
        candidates = [minimum, maximum, 0, 1, -1]
        if fmt.enum is not None:
            candidates.extend(fmt.enum)
        if isinstance(value, int):
            candidates.append(value ^ 1)
        candidates = [candidate for candidate in candidates if minimum <= int(candidate) <= maximum]
        alternatives = [candidate for candidate in candidates if candidate != value]
        if alternatives:
            return rng.choice(alternatives)
        if minimum < maximum:
            return minimum if value != minimum else maximum
        return _NO_CHANGE

    if isinstance(fmt, Bitfield):
        maximum = fmt.mask
        alternatives = [
            candidate for candidate in (0, maximum, 1, value ^ 1) if candidate <= maximum
        ]
        alternatives = [candidate for candidate in alternatives if candidate != value]
        return rng.choice(alternatives) if alternatives else _NO_CHANGE

    if isinstance(fmt, Float):
        alternatives = [0.0, 1.0, -1.0, 0.5, -0.5]
        alternatives = [candidate for candidate in alternatives if candidate != value]
        return rng.choice(alternatives) if alternatives else _NO_CHANGE

    if isinstance(fmt, Bytes):
        if not value:
            return _NO_CHANGE
        replacement = bytearray(value)
        index = rng.randrange(len(replacement))
        replacement[index] ^= 1 << rng.randrange(8)
        return bytes(replacement)

    if isinstance(fmt, Str):
        if not value:
            return _NO_CHANGE
        index = rng.randrange(len(value))
        current = value[index]
        try:
            current_size = len(current.encode(fmt.encoding))
        except UnicodeEncodeError:
            return _NO_CHANGE
        alphabet = string.printable + "éΩ中"
        alternatives = []
        for candidate in alphabet:
            if candidate == current:
                continue
            try:
                if len(candidate.encode(fmt.encoding)) == current_size:
                    alternatives.append(candidate)
            except UnicodeEncodeError:
                continue
        if not alternatives:
            return _NO_CHANGE
        return value[:index] + rng.choice(alternatives) + value[index + 1 :]

    return _NO_CHANGE


def _walk_mutable(
    node: InspectNode,
    path: tuple[str | int, ...],
    rng: random.Random,
) -> Iterator[tuple[tuple[str | int, ...], Any, Any]]:
    replacement = _replacement(node.fmt, node.value, rng)
    if replacement is not _NO_CHANGE:
        yield path, node.value, replacement
    if isinstance(node.fmt, Bitfields) and isinstance(node.value, Mapping):
        for key, child_fmt in node.fmt.fmt.items():
            original = node.value[key]
            child_replacement = _replacement(child_fmt, original, rng)
            if child_replacement is not _NO_CHANGE:
                child_path = (*path[:-1], key) if node.fmt.inline else (*path, key)
                yield child_path, original, child_replacement
    for child in node.children:
        if child.key is None:
            child_path = path
        elif isinstance(node.fmt, Bitfields) and node.fmt.inline:
            child_path = (*path[:-1], child.key)
        else:
            child_path = (*path, child.key)
        yield from _walk_mutable(child, child_path, rng)


def _walk_inspection(node: InspectNode) -> Iterator[InspectNode]:
    yield node
    for child in node.children:
        yield from _walk_inspection(child)


def _inspection_boundaries(node: InspectNode, data_size: int) -> Iterator[int]:
    start = max(0, min(node.offset, data_size))
    yield start
    yield max(start, min(node.offset + node.size, data_size))


def _get_at(value: Any, path: tuple[str | int, ...]) -> Any:
    current = value
    try:
        for key in path:
            if isinstance(current, Mapping):
                current = current[key]
            elif isinstance(current, (list, tuple)):
                current = current[key]
            elif isinstance(current, Struct):
                current = getattr(current, key)
            else:
                return _NO_CHANGE
    except (IndexError, KeyError, TypeError):
        return _NO_CHANGE
    return current


def _replace_at(value: Any, path: tuple[str | int, ...], replacement: Any) -> Any:
    if not path:
        return replacement
    parent = value
    for key in path[:-1]:
        if isinstance(parent, Struct):
            parent = getattr(parent, key)
        else:
            parent = parent[key]
    key = path[-1]
    if isinstance(parent, MutableMapping):
        parent[key] = replacement
    elif isinstance(parent, list):
        parent[key] = replacement
    elif isinstance(parent, Struct):
        setattr(parent, key, replacement)
    else:
        raise TypeError(f"Cannot replace a value inside {type(parent).__name__}")
    return value


def _resolve_ref(ref: Ref, contexts: tuple[Mapping[Any, Any], ...]) -> Any:
    if ref.parent < 1 or ref.parent > len(contexts):
        return _NO_CHANGE
    return contexts[-ref.parent].get(ref.key, _NO_CHANGE)


def _contexts_at(value: Any, path: tuple[str | int, ...]) -> tuple[Mapping[Any, Any], ...]:
    contexts: list[Mapping[Any, Any]] = []
    current = value
    for key in path:
        if isinstance(current, Mapping):
            contexts.append(current)
            current = current.get(key, _NO_CHANGE)
        elif isinstance(current, Struct):
            builtins = to_builtins(current)
            if not isinstance(builtins, Mapping):
                return tuple(contexts)
            contexts.append(builtins)
            current = builtins.get(key, _NO_CHANGE)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[key]
            except (IndexError, TypeError):
                return tuple(contexts)
        else:
            return tuple(contexts)
    return tuple(contexts)


def _build_array_value(
    element_fmt: Any,
    dimensions: list[int],
    level: int,
    rng: random.Random,
    contexts: tuple[Mapping[Any, Any], ...],
) -> Any:
    if level == len(dimensions):
        return _default_value(element_fmt, rng, contexts)
    return [
        _build_array_value(element_fmt, dimensions, level + 1, rng, contexts)
        for _ in range(dimensions[level])
    ]


def _default_value(  # noqa: PLR0911, PLR0912, PLR0915
    fmt: Any,
    rng: random.Random,
    contexts: tuple[Mapping[Any, Any], ...] = (),
    *,
    exact_size: int | None = None,
) -> Any:
    if isinstance(fmt, Mapping):
        result: dict[Any, Any] = {}
        nested_contexts = (*contexts, result)
        for key, child_fmt in fmt.items():
            result[key] = _default_value(child_fmt, rng, nested_contexts)
        return result
    if isinstance(fmt, Int):
        if fmt.enum:
            return int(rng.choice(fmt.enum))
        return 0
    if isinstance(fmt, Bitfield):
        return False if fmt.bits == 1 else 0
    if isinstance(fmt, Float):
        return 0.0
    if isinstance(fmt, Bytes):
        size = exact_size if exact_size is not None else fmt.size
        if size is not None and fmt.size is not None and size != fmt.size:
            return _NO_CHANGE
        return bytes(size or 0)
    if isinstance(fmt, Str):
        size = exact_size if exact_size is not None else fmt.size
        if size is None:
            return ""
        try:
            candidate = "A" * size
            return candidate if len(candidate.encode(fmt.encoding)) == size else _NO_CHANGE
        except (LookupError, UnicodeEncodeError):
            return _NO_CHANGE
    if isinstance(fmt, Literal):
        return fmt.value
    if isinstance(fmt, Null):
        return None
    if isinstance(fmt, Optional):
        return None
    if isinstance(fmt, Bitfields):
        return _default_value(fmt.fmt, rng, contexts)
    if isinstance(fmt, Sized):
        if isinstance(fmt.length, Ref):
            size = _resolve_ref(fmt.length, contexts)
        elif isinstance(fmt.length, int):
            size = fmt.length
        else:
            size = None
        return _default_value(
            fmt.fmt,
            rng,
            contexts,
            exact_size=size if isinstance(size, int) and size >= 0 else None,
        )
    if isinstance(fmt, Array):
        if not fmt.dims:
            return []
        dimensions: list[int] = []
        for dimension in fmt.dims:
            if isinstance(dimension, int):
                dimensions.append(dimension)
            elif isinstance(dimension, Ref):
                value = _resolve_ref(dimension, contexts)
                if not isinstance(value, int) or value < 0:
                    return _NO_CHANGE
                dimensions.append(value)
            else:
                return _NO_CHANGE
        return _build_array_value(fmt.element_fmt, dimensions, 0, rng, contexts)
    if isinstance(fmt, Switch):
        tag = _resolve_ref(fmt.key, contexts) if isinstance(fmt.key, Ref) else _NO_CHANGE
        branch = fmt.cases.get(tag, fmt.default)
        if branch is None and fmt.cases:
            branch = next(iter(fmt.cases.values()))
        return _default_value(branch, rng, contexts) if branch is not None else _NO_CHANGE
    if isinstance(fmt, TaggedUnion):
        tag = _resolve_ref(fmt.tag, contexts) if isinstance(fmt.tag, Ref) else _NO_CHANGE
        if tag not in fmt.fmt_by_tag:
            if not fmt.fmt_by_tag:
                return _NO_CHANGE
            tag = next(iter(fmt.fmt_by_tag))
        return _default_value(fmt.fmt_by_tag[tag], rng, contexts)
    if isinstance(fmt, TakeUntil):
        return _default_value(fmt.fmt, rng, contexts)
    if isinstance(fmt, (list, tuple)):
        values = [_default_value(child_fmt, rng, contexts) for child_fmt in fmt]
        return values if isinstance(fmt, list) else tuple(values)
    return _NO_CHANGE


def _updated_value(
    value: Any,
    updates: tuple[tuple[tuple[str | int, ...], Any], ...],
) -> Any:
    result = deepcopy(value)
    for path, replacement in updates:
        result = _replace_at(result, path, replacement)
    return result


def _array_candidates(
    value: Any,
    node: FormatPlanNode,
    fmt: Array,
    plan: FormatPlan,
    rng: random.Random,
) -> Iterator[Any]:
    current = _get_at(value, node.path)
    if not isinstance(current, list):
        return
    dimension_dependencies = [
        dependency
        for dependency in plan.dependencies
        if dependency.source_path == node.path and dependency.relation == "dimension"
    ]
    dynamic_ref = (
        len(fmt.dims) == 1 and len(dimension_dependencies) == 1 and isinstance(fmt.dims[0], Ref)
    )
    if dynamic_ref or not fmt.dims:
        for index in range(len(current)):
            updated = list(current)
            del updated[index]
            updates = [(node.path, updated)]
            if dynamic_ref:
                dependency = dimension_dependencies[0]
                count = _get_at(value, dependency.target_path)
                if not isinstance(count, int) or count < 1:
                    continue
                updates.append((dependency.target_path, count - 1))
            try:
                yield _updated_value(value, tuple(updates))
            except (AttributeError, IndexError, KeyError, TypeError):
                continue

        element = (
            deepcopy(rng.choice(current))
            if current
            else _default_value(fmt.element_fmt, rng, _contexts_at(value, node.path))
        )
        if element is not _NO_CHANGE:
            updated = list(current)
            updated.insert(rng.randrange(len(updated) + 1), element)
            updates = [(node.path, updated)]
            if dynamic_ref:
                dependency = dimension_dependencies[0]
                count = _get_at(value, dependency.target_path)
                if not isinstance(count, int):
                    return
                updates.append((dependency.target_path, count + 1))
            try:
                yield _updated_value(value, tuple(updates))
            except (AttributeError, IndexError, KeyError, TypeError):
                return
    elif len(current) > 1:
        try:
            yield _updated_value(value, ((node.path, list(reversed(current))),))
        except (AttributeError, IndexError, KeyError, TypeError):
            return


def _optional_candidate(
    value: Any,
    node: FormatPlanNode,
    fmt: Optional,
    rng: random.Random,
) -> Iterator[Any]:
    current = _get_at(value, node.path)
    replacement = (
        _default_value(fmt.fmt, rng, _contexts_at(value, node.path)) if current is None else None
    )
    if replacement is _NO_CHANGE or replacement == current:
        return
    try:
        yield _updated_value(value, ((node.path, replacement),))
    except (AttributeError, IndexError, KeyError, TypeError):
        return


def _branch_candidates(
    value: Any,
    node: FormatPlanNode,
    fmt: Switch | TaggedUnion,
    plan: FormatPlan,
    rng: random.Random,
) -> Iterator[Any]:
    relation = "switch" if isinstance(fmt, Switch) else "tag"
    dependency = next(
        (
            item
            for item in plan.dependencies
            if item.source_path == node.path and item.relation == relation
        ),
        None,
    )
    if dependency is None:
        return
    current_tag = _get_at(value, dependency.target_path)
    cases = fmt.cases if isinstance(fmt, Switch) else fmt.fmt_by_tag
    for tag, branch_fmt in cases.items():
        if tag == current_tag:
            continue
        branch_value = _default_value(branch_fmt, rng, _contexts_at(value, node.path))
        if branch_value is _NO_CHANGE:
            continue
        if isinstance(fmt, TaggedUnion):
            if not isinstance(branch_value, MutableMapping):
                continue
            if fmt.struct_tag_field is not None:
                branch_value[fmt.struct_tag_field] = tag
        try:
            yield _updated_value(
                value,
                (
                    (node.path, branch_value),
                    (dependency.target_path, tag),
                ),
            )
        except (AttributeError, IndexError, KeyError, TypeError):
            continue


def _structural_candidates(
    value: Any,
    plan: FormatPlan,
    rng: random.Random,
) -> Iterator[Any]:
    for node in plan.nodes():
        fmt = node.fmt
        if isinstance(fmt, Array):
            yield from _array_candidates(value, node, fmt, plan, rng)
        elif isinstance(fmt, Optional):
            yield from _optional_candidate(value, node, fmt, rng)
        elif isinstance(fmt, (Switch, TaggedUnion)):
            yield from _branch_candidates(value, node, fmt, plan, rng)


def mutate_valid(  # noqa: PLR0912
    data: bytes,
    fmt: Any,
    *,
    seed: int | None = None,
    max_size: int = 4096,
) -> bytes:
    """Mutate a scalar or format structure while preserving validity.

    Scalar changes retain their byte width. Structural changes are accepted
    only when they encode within ``max_size`` and decode successfully.
    """
    if max_size < 1:
        raise ValueError("max_size must be at least 1")
    if len(data) > max_size:
        raise ValueError(f"Input size {len(data)} exceeds max_size={max_size}")

    plan = compile_format(fmt)
    fmt = plan.fmt
    value, tree = decode_inspect(data, fmt)
    rng = random.Random(seed)
    candidates: list[tuple[Any, bool]] = []
    for path, original, replacement in _walk_mutable(tree, (), rng):
        if _get_at(value, path) != original:
            continue
        try:
            candidates.append((_replace_at(deepcopy(value), path, replacement), True))
        except (AttributeError, IndexError, KeyError, TypeError):
            continue

    for path, hint in plan.field_hints:
        original = _get_at(value, path)
        for replacement in hint.values:
            if replacement == original:
                continue
            try:
                candidate = _replace_at(deepcopy(value), path, replacement)
            except (AttributeError, IndexError, KeyError, TypeError):
                continue
            candidates.extend((candidate, True) for _ in range(hint.weight))

    candidates.extend((candidate, False) for candidate in _structural_candidates(value, plan, rng))
    if not candidates:
        return data

    rng.shuffle(candidates)
    for mutated_value, same_size in candidates:
        try:
            mutated = encode(mutated_value, fmt)
            if (
                len(mutated) > max_size
                or (same_size and len(mutated) != len(data))
                or mutated == data
            ):
                continue
            decoded = decode(mutated, fmt)
            if not same_size and to_builtins(decoded) != to_builtins(mutated_value):
                continue
        except (Error, IndexError, KeyError, TypeError):
            continue
        return mutated
    return data


def _inspection_tree(data: bytes, fmt: Any) -> InspectNode | None:
    try:
        _, tree = decode_inspect(data, fmt)
    except DecodeError as exc:
        return exc.inspect_node
    except ExcessDecodeError as exc:
        return exc.inspect_node
    return tree


def _inspection_at(node: InspectNode, path: tuple[str | int, ...]) -> InspectNode | None:
    current = node
    for key in path:
        current = next((child for child in current.children if child.key == key), None)
        if current is None:
            return None
    return current


def _unlisted_tag(
    target: InspectNode,
    cases: Mapping[Any, Any],
) -> Any:
    fmt = target.fmt
    current = target.value
    if isinstance(fmt, Int):
        bits = fmt.size * 8
        minimum = -(1 << (bits - 1)) if fmt.signed else 0
        maximum = (1 << (bits - (1 if fmt.signed else 0))) - 1
        candidates = (minimum, maximum, 0, 1, current ^ 1, current + 1, current - 1)
        return next(
            (
                candidate
                for candidate in candidates
                if minimum <= candidate <= maximum and candidate not in cases
            ),
            _NO_CHANGE,
        )
    if isinstance(fmt, Str):
        try:
            byte_size = len(current.encode(fmt.encoding))
            candidates = [char * len(current) for char in ("!", "?", "~", "x", "0", "\0")]
            return next(
                (
                    candidate
                    for candidate in candidates
                    if candidate not in cases and len(candidate.encode(fmt.encoding)) == byte_size
                ),
                _NO_CHANGE,
            )
        except (AttributeError, LookupError, UnicodeEncodeError):
            return _NO_CHANGE
    return _NO_CHANGE


def _dependency_corruptions(  # noqa: PLR0912, PLR0915
    data: bytes,
    plan: FormatPlan,
    tree: InspectNode | None,
) -> Iterator[bytes]:
    if tree is None:
        return
    for dependency in plan.dependencies:
        target = _inspection_at(tree, dependency.target_path)
        if target is None:
            continue
        current = target.value
        replacement = _NO_CHANGE
        if dependency.relation in ("length", "dimension") and isinstance(target.fmt, Int):
            bits = target.fmt.size * 8
            minimum = -(1 << (bits - 1)) if target.fmt.signed else 0
            maximum = (1 << (bits - (1 if target.fmt.signed else 0))) - 1
            if isinstance(current, int):
                if current < maximum:
                    replacement = current + 1
                elif current > minimum:
                    replacement = current - 1
        elif dependency.relation in ("switch", "tag"):
            source = next(
                (
                    node
                    for node in plan.nodes()
                    if node.path == dependency.source_path
                    and isinstance(node.fmt, (Switch, TaggedUnion))
                ),
                None,
            )
            if source is None:
                continue
            fmt = source.fmt
            if isinstance(fmt, Switch):
                if fmt.default is not None:
                    continue
                cases = fmt.cases
            else:
                cases = fmt.fmt_by_tag
            replacement = _unlisted_tag(target, cases)
        if replacement is _NO_CHANGE:
            continue
        try:
            encoded = encode(replacement, target.fmt)
        except (Error, TypeError, ValueError):
            continue
        if len(encoded) != target.size:
            continue
        start = target.offset
        end = start + target.size
        if start < 0 or end > len(data):
            continue
        mutated = data[:start] + encoded + data[end:]
        if mutated != data:
            yield mutated
    for node in plan.nodes():
        if not isinstance(node.fmt, TakeUntil):
            continue
        inspected = _inspection_at(tree, node.path)
        if inspected is None or inspected.size < len(node.fmt.terminator):
            continue
        start = inspected.offset + inspected.size - len(node.fmt.terminator)
        end = start + len(node.fmt.terminator)
        if start < 0 or end > len(data):
            continue
        replacement = bytearray(node.fmt.terminator)
        replacement[-1] ^= 1
        mutated = data[:start] + bytes(replacement) + data[end:]
        if mutated != data:
            yield mutated


def mutate_malformed(  # noqa: PLR0911, PLR0912
    data: bytes,
    fmt: Any,
    *,
    seed: int | None = None,
    max_size: int = 4096,
) -> bytes:
    """Mutate bytes at inspected field boundaries or wire offsets.

    Operations include bit flips, truncation, field deletion/duplication, and
    byte insertion/overwriting. The result never exceeds ``max_size``.
    """
    if max_size < 1:
        raise ValueError("max_size must be at least 1")
    if len(data) > max_size:
        raise ValueError(f"Input size {len(data)} exceeds max_size={max_size}")

    plan = compile_format(fmt)
    fmt = plan.fmt
    rng = random.Random(seed)
    tree = _inspection_tree(data, fmt)
    boundaries = {0, len(data)}
    nodes = list(_walk_inspection(tree)) if tree is not None else []
    boundaries.update(
        boundary for node in nodes for boundary in _inspection_boundaries(node, len(data))
    )

    operations: list[tuple[str, int, int]] = []
    dependency_mutations = list(_dependency_corruptions(data, plan, tree))
    if dependency_mutations and rng.randrange(2) == 0:
        return rng.choice(dependency_mutations)
    if data:
        operations.append(("flip", 0, len(data)))
    for boundary in boundaries:
        if boundary < len(data):
            operations.append(("truncate", boundary, 0))
        if len(data) < max_size:
            operations.append(("insert", boundary, 1))
    for node in nodes:
        if node.key is None or node.size <= 0:
            continue
        start = max(0, min(node.offset, len(data)))
        size = max(0, min(node.size, len(data) - start))
        if not size:
            continue
        operations.append(("delete", start, size))
        if len(data) + size <= max_size:
            operations.append(("duplicate", start, size))
        operations.append(("zero", start, size))

    if not operations:
        return b"\x00"

    kind, offset, size = rng.choice(operations)
    if kind == "flip":
        result = bytearray(data)
        index = rng.randrange(len(result))
        result[index] ^= 1 << rng.randrange(8)
        return bytes(result)
    if kind == "truncate":
        return data[:offset]
    if kind == "insert":
        return data[:offset] + rng.randbytes(size) + data[offset:]
    if kind == "delete":
        return data[:offset] + data[offset + size :]
    if kind == "duplicate":
        part = data[offset : offset + size]
        return data[: offset + size] + part + data[offset + size :]

    result = bytearray(data)
    result[offset : offset + size] = bytes(size)
    if bytes(result) == data:
        result[offset] ^= 1
    return bytes(result)
