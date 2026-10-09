"""Format-aware valid mutations and inspection-guided wire mutations."""

from __future__ import annotations

import random
import string
from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from typing import Any

from fmtspec import (
    DecodeError,
    Error,
    ExcessDecodeError,
    InspectNode,
    decode,
    decode_inspect,
    encode,
)
from fmtspec.types import Bitfield, Bitfields, Bytes, Float, Int, Str

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
        parent = parent[key]
    key = path[-1]
    if isinstance(parent, MutableMapping):
        parent[key] = replacement
    elif isinstance(parent, list):
        parent[key] = replacement
    else:
        raise TypeError(f"Cannot replace a value inside {type(parent).__name__}")
    return value


def mutate_valid(data: bytes, fmt: Any, *, seed: int | None = None) -> bytes:
    """Change one inspected scalar while preserving the encoded structure.

    Mutated scalar values retain their byte width. Formats without a mutable
    scalar or a same-width mutation that survives a complete round trip are
    returned unchanged.
    """
    value, tree = decode_inspect(data, fmt)
    rng = random.Random(seed)
    candidates = list(_walk_mutable(tree, (), rng))
    if not candidates:
        return data

    rng.shuffle(candidates)
    for path, original, replacement in candidates:
        if _get_at(value, path) != original:
            continue
        try:
            mutated_value = _replace_at(deepcopy(value), path, replacement)
            mutated = encode(mutated_value, fmt)
            if len(mutated) != len(data) or mutated == data:
                continue
            decode(mutated, fmt)
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

    rng = random.Random(seed)
    tree = _inspection_tree(data, fmt)
    boundaries = {0, len(data)}
    nodes = list(_walk_inspection(tree)) if tree is not None else []
    boundaries.update(
        boundary for node in nodes for boundary in _inspection_boundaries(node, len(data))
    )

    operations: list[tuple[str, int, int]] = []
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
