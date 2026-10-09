"""Hypothesis strategies derived from fmtspec format specifications."""

from __future__ import annotations

import codecs
from collections.abc import Callable, Iterable, Iterator, Mapping
from functools import partial
from io import BytesIO
from typing import Any

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from fmtspec import Context, encode, sizeof
from fmtspec.stream import encode_stream
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

from ._plan import FieldHint, FormatPath, compile_format

type FormatContext = tuple[Mapping[str, Any], ...]
type StrategyFactory = Callable[[Any, FormatContext, int], SearchStrategy[Any]]

_CUSTOM_STRATEGIES: dict[type, StrategyFactory] = {}
_FLOAT32_SIZE = 4


class UnsupportedFormatError(TypeError):
    """Raised when a format cannot be generated without a custom strategy."""


def register_format_strategy[T](
    format_type: type[T],
    factory: Callable[[T, FormatContext, int], SearchStrategy[Any]],
) -> None:
    """Register a Hypothesis strategy factory for a custom format type.

    The factory receives the format instance, the enclosing mapping contexts
    (outermost first), and the maximum generated input size.
    """
    if not isinstance(format_type, type):
        raise TypeError("format_type must be a type")
    _CUSTOM_STRATEGIES[format_type] = factory


def _registered_strategy(
    fmt: Any,
    contexts: FormatContext,
    max_size: int,
) -> SearchStrategy[Any] | None:
    for format_type, factory in reversed(tuple(_CUSTOM_STRATEGIES.items())):
        if isinstance(fmt, format_type):
            return factory(fmt, contexts, max_size)
    return None


def _resolve_ref(ref: Ref, contexts: FormatContext) -> Any:
    if ref.parent < 1 or ref.parent > len(contexts):
        raise UnsupportedFormatError(
            f"Cannot resolve {ref!r}: format generation has only {len(contexts)} "
            "enclosing mapping context(s)"
        )
    parent = contexts[-ref.parent]
    try:
        value = parent[ref.key]
    except KeyError as exc:
        raise UnsupportedFormatError(
            f"Cannot resolve {ref!r}: generate its referenced field before this field"
        ) from exc
    return ref.cast(value) if ref.cast is not None else value


def _text_strategy(
    fmt: Str, max_size: int, *, exact_bytes: int | None = None
) -> SearchStrategy[str]:
    try:
        codecs.lookup(fmt.encoding)
        alphabet = st.characters(codec=fmt.encoding)
    except (LookupError, ValueError) as exc:
        raise UnsupportedFormatError(f"Unsupported string encoding {fmt.encoding!r}") from exc

    if exact_bytes is not None:
        if exact_bytes > max_size:
            raise UnsupportedFormatError(
                f"String payload size {exact_bytes} exceeds max_size={max_size}"
            )
        return st.text(alphabet=alphabet, max_size=exact_bytes).filter(
            partial(_has_encoded_size, encoding=fmt.encoding, size=exact_bytes)
        )

    if fmt.size is not None:
        if fmt.size > max_size:
            raise UnsupportedFormatError(f"String size {fmt.size} exceeds max_size={max_size}")
        return st.text(alphabet=alphabet, max_size=fmt.size).filter(
            partial(_has_encoded_size, encoding=fmt.encoding, size=fmt.size)
        )

    return st.text(alphabet=alphabet, max_size=max_size)


def _int_strategy(fmt: Int, *, low: int = 0, high: int | None = None) -> SearchStrategy[int]:
    bits = fmt.size * 8
    minimum = -(1 << (bits - 1)) if fmt.signed else 0
    maximum = (1 << (bits - (1 if fmt.signed else 0))) - 1
    low = max(low, minimum)
    high = maximum if high is None else min(high, maximum)
    if low > high:
        raise UnsupportedFormatError(f"No non-negative values fit the integer format {fmt!r}")
    if fmt.enum is not None:
        members = [member for member in fmt.enum if low <= int(member) <= high]
        if members:
            return st.sampled_from(members)
    return st.integers(min_value=low, max_value=high)


def _has_encoded_size(value: str, *, encoding: str, size: int) -> bool:
    return len(value.encode(encoding)) == size


def _walk_mapping_constraints(  # noqa: PLR0912
    child: Any,
    current: Mapping[str, Any],
    max_size: int,
) -> Iterator[tuple[str, str, int | set[Any]]]:
    if isinstance(child, Sized):
        if isinstance(child.length, Ref):
            ref = child.length
            if ref.parent == 1 and ref.cast is None:
                inner_size = sizeof(child.fmt)
                if isinstance(inner_size, int):
                    yield "allowed", ref.key, {inner_size}
                else:
                    yield "limit", ref.key, max_size
        yield from _walk_mapping_constraints(child.fmt, current, max_size)
    elif isinstance(child, Array):
        product = 1
        for dim in child.dims:
            if isinstance(dim, Ref) and dim.parent == 1 and dim.cast is None:
                if dim.key in current:
                    count = current[dim.key]
                    if isinstance(count, int) and count >= 0:
                        product *= count
                else:
                    yield "limit", dim.key, max_size // max(product, 1)
            elif isinstance(dim, int):
                product *= dim
        yield from _walk_mapping_constraints(child.element_fmt, current, max_size)
    elif isinstance(child, Switch):
        if child.key.parent == 1 and child.default is None:
            yield "allowed", child.key.key, set(child.cases)
        for branch in (*child.cases.values(), child.default):
            if branch is not None:
                yield from _walk_mapping_constraints(branch, current, max_size)
    elif isinstance(child, TaggedUnion):
        if isinstance(child.tag, Ref) and child.tag.parent == 1:
            yield "allowed", child.tag.key, set(child.fmt_by_tag)
        for branch in child.fmt_by_tag.values():
            yield from _walk_mapping_constraints(branch, current, max_size)
    elif isinstance(child, (Optional, TakeUntil)):
        yield from _walk_mapping_constraints(child.fmt, current, max_size)
    elif isinstance(child, (list, tuple)):
        for nested in child:
            yield from _walk_mapping_constraints(nested, current, max_size)


def _mapping_constraints(
    fmt: Mapping[str, Any],
    max_size: int,
    current: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, set[Any]]]:
    limits: dict[str, int] = {}
    allowed: dict[str, set[Any]] = {}
    for child_fmt in fmt.values():
        for kind, key, value in _walk_mapping_constraints(child_fmt, current, max_size):
            if kind == "limit":
                assert isinstance(value, int)
                limits[key] = min(limits.get(key, value), value)
            else:
                assert isinstance(value, set)
                allowed[key] = allowed.get(key, value) & value
    return limits, allowed


def _is_allowed(value: Any, *, allowed_values: set[Any]) -> bool:
    return value in allowed_values


def _is_bounded_nonnegative_int(value: Any, *, upper_bound: int) -> bool:
    return isinstance(value, int) and 0 <= value <= upper_bound


def _is_count(value: Any, *, maximum: int) -> bool:
    return _is_bounded_nonnegative_int(value, upper_bound=maximum)


def _mapping_field_strategy(  # noqa: PLR0913
    fmt: Any,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    upper_bound: int | None,
    allowed_values: set[Any] | None,
    tail: bool,
    path: FormatPath,
    value_hints: Mapping[FormatPath, FieldHint],
) -> SearchStrategy[Any]:
    if isinstance(fmt, Int) and (upper_bound is not None or allowed_values is not None):
        bits = fmt.size * 8
        minimum = -(1 << (bits - 1)) if fmt.signed else 0
        maximum = (1 << (bits - (1 if fmt.signed else 0))) - 1
        minimum = max(minimum, 0) if upper_bound is not None else minimum
        maximum = min(maximum, upper_bound) if upper_bound is not None else maximum
        if allowed_values is not None:
            values = [
                value
                for value in allowed_values
                if isinstance(value, int) and minimum <= value <= maximum
            ]
            if not values:
                raise UnsupportedFormatError("No referenced values fit the integer field format")
            return st.sampled_from(values)
        return st.integers(min_value=minimum, max_value=maximum)

    if allowed_values is not None and isinstance(fmt, Str):
        try:
            codecs.lookup(fmt.encoding)
            values = [
                value
                for value in allowed_values
                if isinstance(value, str)
                and (fmt.size is None or len(value.encode(fmt.encoding)) == fmt.size)
            ]
        except (LookupError, UnicodeEncodeError) as exc:
            raise UnsupportedFormatError(
                f"Cannot generate allowed values for encoding {fmt.encoding!r}"
            ) from exc
        if not values:
            raise UnsupportedFormatError("No referenced values fit the string field format")
        return st.sampled_from(values)

    if allowed_values is not None and isinstance(fmt, Bytes):
        values = [
            value
            for value in allowed_values
            if isinstance(value, bytes) and (fmt.size is None or len(value) == fmt.size)
        ]
        if not values:
            raise UnsupportedFormatError("No referenced values fit the byte field format")
        return st.sampled_from(values)

    if allowed_values is not None and isinstance(fmt, Literal):
        if fmt.value in allowed_values:
            return st.just(fmt.value)
        raise UnsupportedFormatError("Literal format value is not an allowed reference value")

    strategy = _value_strategy(
        fmt,
        contexts,
        max_size,
        seen,
        tail=tail,
        path=path,
        value_hints=value_hints,
    )
    if allowed_values is not None:
        strategy = strategy.filter(partial(_is_allowed, allowed_values=allowed_values))
    if upper_bound is not None:
        strategy = strategy.filter(partial(_is_bounded_nonnegative_int, upper_bound=upper_bound))
    return strategy


def _count_strategy(
    count_fmt: Any,
    contexts: FormatContext,
    max_size: int,
) -> SearchStrategy[int]:
    if isinstance(count_fmt, Int):
        return _int_strategy(count_fmt, low=0, high=max_size)
    strategy = _value_strategy(count_fmt, contexts, max_size, frozenset())
    return strategy.filter(partial(_is_count, maximum=max_size))


def _sized_strategy(  # noqa: PLR0912, PLR0913, PLR0917
    fmt: Sized,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    path: FormatPath,
    value_hints: Mapping[FormatPath, FieldHint],
) -> SearchStrategy[Any]:
    length = fmt.length
    is_reference = isinstance(length, Ref)
    if isinstance(length, Ref):
        expected = _resolve_ref(length, contexts)
        if not isinstance(expected, int) or expected < 0 or expected > max_size:
            raise UnsupportedFormatError(
                f"Referenced size {expected!r} is outside the supported range 0..{max_size}"
            )
        exact_size = expected
    elif isinstance(length, int):
        if length < 0 or length > max_size:
            raise UnsupportedFormatError(
                f"Sized length {length} is outside the supported range 0..{max_size}"
            )
        exact_size = length
    else:
        payload_limit = max_size
        if isinstance(length, Int):
            bits = length.size * 8
            encoded_maximum = (1 << (bits - (1 if length.signed else 0))) - 1
            payload_limit = min(payload_limit, encoded_maximum)
        inner_size = sizeof(fmt.fmt)
        if isinstance(inner_size, int) and inner_size > payload_limit:
            raise UnsupportedFormatError(
                "Inner format size exceeds the maximum representable Sized length"
            )
        return _value_strategy(
            fmt.fmt,
            contexts,
            payload_limit,
            seen,
            tail=True,
            path=path,
            value_hints=value_hints,
        )

    inner_fmt = fmt.fmt
    inner_tail = exact_size == 0 if isinstance(length, (int, Ref)) else True
    if isinstance(inner_fmt, Bytes):
        if inner_fmt.size is not None and inner_fmt.size != exact_size:
            if is_reference:
                raise UnsupportedFormatError(
                    "A Ref-sized field must encode exactly the referenced byte count"
                )
            if inner_fmt.size > exact_size:
                raise UnsupportedFormatError("Inner byte format exceeds the Sized field length")
            return st.binary(min_size=inner_fmt.size, max_size=inner_fmt.size)
        return st.binary(min_size=exact_size, max_size=exact_size)

    if isinstance(inner_fmt, Str):
        if inner_fmt.size is None:
            return _text_strategy(inner_fmt, max_size, exact_bytes=exact_size)
        if is_reference and inner_fmt.size != exact_size:
            raise UnsupportedFormatError(
                "A Ref-sized field must encode exactly the referenced byte count"
            )
        if inner_fmt.size > exact_size:
            raise UnsupportedFormatError("Inner string format exceeds the Sized field length")
        return _text_strategy(inner_fmt, max_size)

    inner_size = sizeof(inner_fmt)
    if isinstance(inner_size, int):
        if inner_size > exact_size:
            raise UnsupportedFormatError("Inner format exceeds the Sized field length")
        return _value_strategy(
            inner_fmt,
            contexts,
            max_size,
            seen,
            tail=inner_tail,
            path=path,
            value_hints=value_hints,
        )

    raise UnsupportedFormatError(
        "A fixed/reference-sized wrapper around a variable-size format requires a custom strategy"
    )


def _build_array_values(  # noqa: PLR0913, PLR0917
    draw: Callable[[SearchStrategy[Any]], Any],
    fmt: Array,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    dimensions: list[int],
    level: int,
    tail: bool,
    path: FormatPath,
    value_hints: Mapping[FormatPath, FieldHint],
) -> list[Any]:
    count = dimensions[level]
    if level == len(dimensions) - 1:
        return [
            draw(
                _value_strategy(
                    fmt.element_fmt,
                    contexts,
                    max_size,
                    seen,
                    tail=tail and index == count - 1,
                    path=path,
                    value_hints=value_hints,
                )
            )
            for index in range(count)
        ]
    return [
        _build_array_values(
            draw,
            fmt,
            contexts,
            max_size,
            seen,
            dimensions,
            level + 1,
            tail and index == count - 1,
            path,
            value_hints,
        )
        for index in range(count)
    ]


def _array_strategy(  # noqa: PLR0913
    fmt: Array,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    tail: bool,
    path: FormatPath,
    value_hints: Mapping[FormatPath, FieldHint],
) -> SearchStrategy[list[Any]]:
    element_size = sizeof(fmt.element_fmt)
    element_limit = (
        max_size // element_size if isinstance(element_size, int) and element_size else max_size
    )
    if not element_limit:
        raise UnsupportedFormatError("Array element format exceeds max_size")

    @st.composite
    def make_array(draw) -> list[Any]:
        dimensions: list[int] = []
        product = 1
        specs = fmt.dims or (None,)
        for dim in specs:
            limit = max(0, element_limit // product)
            if dim is None:
                count = draw(st.integers(min_value=0, max_value=limit))
            elif isinstance(dim, int):
                count = dim
            elif isinstance(dim, Ref):
                count = _resolve_ref(dim, contexts)
            else:
                count = draw(_count_strategy(dim, contexts, limit))

            if not isinstance(count, int) or count < 0 or count > limit:
                raise UnsupportedFormatError(
                    f"Array dimension {count!r} exceeds the supported element limit {limit}"
                )
            dimensions.append(count)
            product *= count

        element_path = (*path, *("*" for _ in dimensions))
        return _build_array_values(
            draw,
            fmt,
            contexts,
            max_size,
            seen,
            dimensions,
            0,
            tail,
            element_path,
            value_hints,
        )

    return make_array()


def _tagged_union_branch_strategy(  # noqa: PLR0913, PLR0917
    tag: Any,
    fmt: TaggedUnion,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    tail: bool,
    path: FormatPath,
    value_hints: Mapping[FormatPath, FieldHint],
) -> SearchStrategy[Any]:
    return _value_strategy(
        fmt.fmt_by_tag[tag],
        contexts,
        max_size,
        seen,
        tail=tail,
        path=path,
        value_hints=value_hints,
    ).map(partial(_add_union_tag, tag=tag, fmt=fmt, contexts=contexts))


def _tagged_union_strategy(  # noqa: PLR0913
    fmt: TaggedUnion,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    tail: bool,
    path: FormatPath,
    value_hints: Mapping[FormatPath, FieldHint],
) -> SearchStrategy[Any]:
    if fmt.struct_tag_field is None or not fmt.fmt_by_tag:
        raise UnsupportedFormatError("TaggedUnion has no supported tagged branches")

    tags = tuple(fmt.fmt_by_tag)
    if isinstance(fmt.tag, Ref):
        if not contexts:
            raise UnsupportedFormatError("A Ref-based TaggedUnion requires a mapping context")
        parent = contexts[-1]
        if fmt.tag.key in parent:
            tag = parent[fmt.tag.key]
            if tag not in fmt.fmt_by_tag:
                raise UnsupportedFormatError(f"Unknown TaggedUnion tag {tag!r}")
            return _tagged_union_branch_strategy(
                tag, fmt, contexts, max_size, seen, tail, path, value_hints
            )
    return st.one_of(
        *(
            _tagged_union_branch_strategy(
                tag, fmt, contexts, max_size, seen, tail, path, value_hints
            )
            for tag in tags
        )
    )


def _add_union_tag(
    value: Any,
    tag: Any,
    fmt: TaggedUnion,
    contexts: FormatContext,
) -> Any:
    if not isinstance(value, Mapping):
        raise UnsupportedFormatError("TaggedUnion branches must generate mapping values")
    result = dict(value)
    tag_field = fmt.struct_tag_field
    if tag_field is not None:
        existing = result.get(tag_field, tag)
        if existing != tag:
            raise UnsupportedFormatError(
                f"Generated TaggedUnion branch has tag {existing!r}, expected {tag!r}"
            )
        result[tag_field] = tag
    if isinstance(fmt.tag, Ref) and contexts:
        parent = contexts[-1]
        existing = parent.get(fmt.tag.key, tag)
        if existing != tag:
            raise UnsupportedFormatError(
                f"Referenced tag field {fmt.tag.key!r} has value {existing!r}, expected {tag!r}"
            )
        if isinstance(parent, dict):
            parent[fmt.tag.key] = tag
    return result


def _valid_take_until_value(
    value: Any,
    *,
    fmt: TakeUntil,
    contexts: FormatContext,
) -> bool:
    stream = BytesIO()
    context = Context()
    for parent in contexts:
        context.push(parent)
    encode_stream(stream, value, fmt.fmt, context=context)
    encoded = stream.getvalue()
    return fmt.terminator not in encoded and (fmt.max_size is None or len(encoded) <= fmt.max_size)


def _encode_value(value: Any, *, fmt: Any) -> bytes:
    return encode(value, fmt)


def _within_size(data: bytes, *, maximum: int) -> bool:
    return len(data) <= maximum


def _value_strategy(  # noqa: PLR0911, PLR0912, PLR0913, PLR0915
    fmt: Any,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    tail: bool = True,
    path: FormatPath = (),
    value_hints: Mapping[FormatPath, FieldHint] | None = None,
) -> SearchStrategy[Any]:
    field_hints = value_hints or {}
    custom = _registered_strategy(fmt, contexts, max_size)
    if custom is not None:
        return custom

    if isinstance(fmt, Mapping):

        @st.composite
        def mapping_value(draw) -> dict[str, Any]:
            result: dict[str, Any] = {}
            child_contexts = (*contexts, result)
            items = tuple(fmt.items())
            for index, (key, child_fmt) in enumerate(items):
                if key not in result:
                    limits, allowed = _mapping_constraints(fmt, max_size, result)
                    child_path = (*path, key)
                    strategy = _mapping_field_strategy(
                        child_fmt,
                        child_contexts,
                        max_size,
                        seen,
                        upper_bound=limits.get(key),
                        allowed_values=allowed.get(key),
                        tail=tail and index == len(items) - 1,
                        path=child_path,
                        value_hints=field_hints,
                    )
                    hint = field_hints.get(child_path)
                    if hint is not None:
                        values = tuple(
                            value
                            for value in hint.values
                            if (allowed.get(key) is None or value in allowed[key])
                            and (
                                limits.get(key) is None
                                or _is_bounded_nonnegative_int(value, upper_bound=limits[key])
                            )
                        )
                        if not values:
                            raise UnsupportedFormatError(
                                f"All field hints conflict with constraints at {child_path!r}"
                            )
                        hinted = st.sampled_from(values)
                        strategy = st.one_of(strategy, *(hinted for _ in range(hint.weight)))
                    result[key] = draw(strategy)
            return result

        return mapping_value()

    if isinstance(fmt, (list, tuple)):
        items = tuple(fmt)
        return st.tuples(
            *(
                _value_strategy(
                    child,
                    contexts,
                    max_size,
                    seen,
                    tail=tail and index == len(items) - 1,
                    path=(*path, index),
                    value_hints=field_hints,
                )
                for index, child in enumerate(items)
            )
        ).map(list)

    if isinstance(fmt, (bytes, str)):
        raise UnsupportedFormatError(f"{type(fmt).__name__} cannot be used as an fmtspec format")

    if isinstance(fmt, Int):
        return _int_strategy(fmt)
    if isinstance(fmt, Float):
        return st.floats(
            width=32 if fmt.size == _FLOAT32_SIZE else 64,
            allow_nan=False,
            allow_infinity=False,
        )
    if isinstance(fmt, Bytes):
        if fmt.size is None:
            return st.binary(max_size=max_size)
        if fmt.size > max_size:
            raise UnsupportedFormatError(f"Byte size {fmt.size} exceeds max_size={max_size}")
        return st.binary(min_size=fmt.size, max_size=fmt.size)
    if isinstance(fmt, Str):
        return _text_strategy(fmt, max_size)
    if isinstance(fmt, Literal):
        return st.just(fmt.value)
    if isinstance(fmt, Null):
        return st.none()
    if isinstance(fmt, Bitfield):
        if fmt.bits == 1:
            return st.booleans()
        return st.integers(min_value=0, max_value=fmt.mask)
    if isinstance(fmt, Bitfields):
        return _value_strategy(
            fmt.fmt,
            contexts,
            max_size,
            seen,
            path=path,
            value_hints=field_hints,
        )
    if isinstance(fmt, Optional):
        inner = _value_strategy(
            fmt.fmt,
            contexts,
            max_size,
            seen,
            tail=tail,
            path=path,
            value_hints=field_hints,
        )
        return st.one_of(st.none(), inner) if tail else inner
    if isinstance(fmt, Array):
        return _array_strategy(
            fmt,
            contexts,
            max_size,
            seen,
            tail=tail,
            path=path,
            value_hints=field_hints,
        )
    if isinstance(fmt, Sized):
        return _sized_strategy(fmt, contexts, max_size, seen, path, field_hints)
    if isinstance(fmt, Switch):
        if not tail:
            raise UnsupportedFormatError(
                "Switch consumes the remainder of its stream and must be the final field"
            )
        tag = _resolve_ref(fmt.key, contexts)
        branch = fmt.cases.get(tag, fmt.default)
        if branch is None:
            raise UnsupportedFormatError(f"Switch has no case or default for {tag!r}")
        return _value_strategy(
            branch,
            contexts,
            max_size,
            seen,
            tail=True,
            path=path,
            value_hints=field_hints,
        )
    if isinstance(fmt, TaggedUnion):
        return _tagged_union_strategy(
            fmt,
            contexts,
            max_size,
            seen,
            tail=tail,
            path=path,
            value_hints=field_hints,
        )
    if isinstance(fmt, TakeUntil):
        strategy = _value_strategy(
            fmt.fmt,
            contexts,
            max_size,
            seen,
            tail=True,
            path=path,
            value_hints=field_hints,
        )
        return strategy.filter(partial(_valid_take_until_value, fmt=fmt, contexts=contexts))
    if isinstance(fmt, Lazy):
        if id(fmt) in seen:
            raise UnsupportedFormatError(
                "Recursive Lazy formats require a registered strategy with a recursion bound"
            )
        inner_fmt = fmt.get_format()
        return _value_strategy(
            inner_fmt,
            contexts,
            max_size,
            seen | {id(fmt)},
            tail=tail,
            path=path,
            value_hints=field_hints,
        )

    if isinstance(fmt, Iterable):
        return _value_strategy(
            tuple(fmt),
            contexts,
            max_size,
            seen,
            path=path,
            value_hints=field_hints,
        )

    raise UnsupportedFormatError(
        f"No strategy is registered for format type {type(fmt).__module__}.{type(fmt).__qualname__}"
    )


def format_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
    field_hints: Mapping[FormatPath, FieldHint | tuple[Any, ...]] | None = None,
) -> SearchStrategy[Any]:
    """Build a Hypothesis strategy for Python values accepted by ``fmt``.

    ``max_size`` bounds generated variable-length values and arrays. Dynamic
    fields that depend on earlier mapping keys are generated in field order.
    """
    if max_size < 1:
        raise ValueError("max_size must be at least 1")
    plan = compile_format(fmt, field_hints=field_hints)
    return _value_strategy(
        plan.fmt,
        (),
        max_size,
        frozenset(),
        value_hints=dict(plan.field_hints),
    )


def binary_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
    field_hints: Mapping[FormatPath, FieldHint | tuple[Any, ...]] | None = None,
) -> SearchStrategy[bytes]:
    """Build a strategy for valid encoded bytes accepted by ``fmt``."""
    plan = compile_format(fmt, field_hints=field_hints)
    values = format_strategy(plan, max_size=max_size)
    strategy = values.map(partial(_encode_value, fmt=plan.fmt))
    return strategy.filter(partial(_within_size, maximum=max_size))
