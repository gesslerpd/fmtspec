"""Hypothesis strategies derived from fmtspec format specifications."""

from __future__ import annotations

import codecs
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator, Mapping
from functools import partial
from io import BytesIO
from itertools import chain
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

from ._plan import (
    EnumPolicy,
    FieldRange,
    FormatPath,
    FormatPlan,
    _integer_bounds,
    compile_format,
)

type FormatContext = tuple[Mapping[str, Any], ...]
type StrategyFactory = Callable[[Any, FormatContext, int], SearchStrategy[Any]]

_CUSTOM_STRATEGIES: dict[type, StrategyFactory] = {}
_FLOAT32_SIZE = 4
_DEFAULT_ENUM_POLICY = EnumPolicy()


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
    for format_type, factory in reversed(_CUSTOM_STRATEGIES.items()):
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

    size = exact_bytes if exact_bytes is not None else fmt.size
    if size is None:
        return st.text(alphabet=alphabet, max_size=max_size)
    if size > max_size:
        description = "String payload size" if exact_bytes is not None else "String size"
        raise UnsupportedFormatError(f"{description} {size} exceeds max_size={max_size}")
    return st.text(alphabet=alphabet, max_size=size).filter(
        partial(_has_encoded_size, encoding=fmt.encoding, size=size)
    )


def _unrank_enum_complement(
    index: int,
    *,
    low: int,
    high: int,
    known_values: tuple[int, ...],
) -> int:
    rank = index + 1
    lower, upper = low, high
    while lower < upper:
        middle = (lower + upper) // 2
        unknowns_through_middle = middle - low + 1 - bisect_right(known_values, middle)
        if unknowns_through_middle >= rank:
            upper = middle
        else:
            lower = middle + 1
    return lower


def _int_strategy(
    fmt: Int,
    *,
    low: int | None = None,
    high: int | None = None,
    enum_policy: EnumPolicy = EnumPolicy(),
) -> SearchStrategy[int]:
    minimum, maximum = _integer_bounds(fmt)
    low = minimum if low is None else max(low, minimum)
    high = maximum if high is None else min(high, maximum)
    if low > high:
        raise UnsupportedFormatError(f"No values fit the integer format {fmt!r}")
    if fmt.enum is not None:
        members = tuple(member for member in fmt.enum if low <= int(member) <= high)
        known_values = tuple(sorted({int(member) for member in members}))
        branches: list[SearchStrategy[int]] = []
        if members and enum_policy.known_weight:
            known_strategy = st.sampled_from(members)
            branches.extend(known_strategy for _ in range(enum_policy.known_weight))
        unknown_count = high - low + 1 - len(known_values)
        if unknown_count and enum_policy.unknown_weight:
            unknown_strategy = st.integers(min_value=0, max_value=unknown_count - 1).map(
                partial(
                    _unrank_enum_complement,
                    low=low,
                    high=high,
                    known_values=known_values,
                )
            )
            branches.extend(unknown_strategy for _ in range(enum_policy.unknown_weight))
        if branches:
            return st.one_of(*branches)
        raise UnsupportedFormatError(
            f"Enum policy and range admit no values for integer format {fmt!r}"
        )
    return st.integers(min_value=low, max_value=high)


def _bitfield_patterns(bits: int) -> tuple[int, ...]:
    mask = (1 << bits) - 1
    values = {0, mask}
    values.update(1 << index for index in range(bits))
    values.update(mask ^ (1 << index) for index in range(bits))
    values.add(sum(1 << index for index in range(0, bits, 2)))
    values.add(sum(1 << index for index in range(1, bits, 2)))
    return tuple(sorted(values))


def _bitfield_strategy(
    fmt: Bitfield,
    *,
    field_range: FieldRange | None = None,
) -> SearchStrategy[Any]:
    low = max(0, field_range.min_value or 0) if field_range is not None else 0
    high = (
        min(fmt.mask, field_range.max_value)
        if field_range is not None and field_range.max_value is not None
        else fmt.mask
    )
    if low > high:
        raise UnsupportedFormatError(f"Field range admits no values for bitfield {fmt!r}")
    if fmt.bits == 1:
        if low == high:
            return st.just(bool(low))
        return st.booleans()
    values = tuple(value for value in _bitfield_patterns(fmt.bits) if low <= value <= high)
    ordinary = st.integers(min_value=low, max_value=high)
    return st.one_of(ordinary, st.sampled_from(values)) if values else ordinary


def _has_encoded_size(value: str, *, encoding: str, size: int) -> bool:
    return len(value.encode(encoding)) == size


def _walk_mapping_constraints(  # noqa: PLR0912
    child: Any,
    current: Mapping[str, Any],
    max_size: int,
) -> Iterator[tuple[str, str, int | set[Any]]]:
    match child:
        case Sized():
            if isinstance(child.length, Ref):
                ref = child.length
                if ref.parent == 1 and ref.cast is None:
                    inner_size = sizeof(child.fmt)
                    if isinstance(inner_size, int):
                        yield "allowed", ref.key, {inner_size}
                    else:
                        yield "limit", ref.key, max_size
            yield from _walk_mapping_constraints(child.fmt, current, max_size)
        case Array():
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
        case Switch():
            if child.key.parent == 1 and child.default is None:
                yield "allowed", child.key.key, set(child.cases)
            for branch in chain(child.cases.values(), (child.default,)):
                if branch is not None:
                    yield from _walk_mapping_constraints(branch, current, max_size)
        case TaggedUnion():
            if isinstance(child.tag, Ref) and child.tag.parent == 1:
                yield "allowed", child.tag.key, set(child.fmt_by_tag)
            for branch in child.fmt_by_tag.values():
                yield from _walk_mapping_constraints(branch, current, max_size)
        case Optional() | TakeUntil():
            yield from _walk_mapping_constraints(child.fmt, current, max_size)
        case list() | tuple():
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


def _mapping_field_strategy(  # noqa: PLR0911, PLR0912, PLR0913
    fmt: Any,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    upper_bound: int | None,
    allowed_values: set[Any] | None,
    tail: bool,
    path: FormatPath,
    config: FormatPlan | None,
) -> SearchStrategy[Any]:
    field_range = config.field_ranges.get(path) if config is not None else None
    match fmt:
        case Int() as int_fmt if (
            upper_bound is not None or allowed_values is not None or field_range is not None
        ):
            minimum, maximum = _integer_bounds(int_fmt)
            minimum = max(minimum, 0) if upper_bound is not None else minimum
            maximum = min(maximum, upper_bound) if upper_bound is not None else maximum
            if field_range is not None:
                minimum = max(
                    minimum,
                    field_range.min_value if field_range.min_value is not None else minimum,
                )
                maximum = min(
                    maximum,
                    field_range.max_value if field_range.max_value is not None else maximum,
                )
            if minimum > maximum:
                raise UnsupportedFormatError(f"Field constraints admit no values at {path!r}")
            if allowed_values is not None:
                values = [
                    value
                    for value in allowed_values
                    if isinstance(value, int) and minimum <= value <= maximum
                ]
                if not values:
                    raise UnsupportedFormatError(
                        "No referenced values fit the integer field format"
                    )
                return st.sampled_from(values)
            enum_policy = (
                config.enum_policy_for(path) if config is not None else _DEFAULT_ENUM_POLICY
            )
            return _int_strategy(
                int_fmt,
                low=minimum,
                high=maximum,
                enum_policy=enum_policy,
            )
        case Bitfield() as bitfield_fmt if field_range is not None:
            return _bitfield_strategy(bitfield_fmt, field_range=field_range)
        case Str() as string_fmt if allowed_values is not None:
            try:
                codecs.lookup(string_fmt.encoding)
                values = [
                    value
                    for value in allowed_values
                    if isinstance(value, str)
                    and (
                        string_fmt.size is None
                        or len(value.encode(string_fmt.encoding)) == string_fmt.size
                    )
                ]
            except (LookupError, UnicodeEncodeError) as exc:
                raise UnsupportedFormatError(
                    f"Cannot generate allowed values for encoding {string_fmt.encoding!r}"
                ) from exc
            if not values:
                raise UnsupportedFormatError("No referenced values fit the string field format")
            return st.sampled_from(values)
        case Bytes() as bytes_fmt if allowed_values is not None:
            values = [
                value
                for value in allowed_values
                if isinstance(value, bytes)
                and (bytes_fmt.size is None or len(value) == bytes_fmt.size)
            ]
            if not values:
                raise UnsupportedFormatError("No referenced values fit the byte field format")
            return st.sampled_from(values)
        case Literal() as literal_fmt if allowed_values is not None:
            if literal_fmt.value in allowed_values:
                return st.just(literal_fmt.value)
            raise UnsupportedFormatError("Literal format value is not an allowed reference value")

    strategy = _value_strategy(
        fmt,
        contexts,
        max_size,
        seen,
        tail=tail,
        path=path,
        config=config,
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
    config: FormatPlan | None,
) -> SearchStrategy[Any]:
    length = fmt.length
    match length:
        case Ref() as ref:
            expected = _resolve_ref(ref, contexts)
            if not isinstance(expected, int) or expected < 0 or expected > max_size:
                raise UnsupportedFormatError(
                    f"Referenced size {expected!r} is outside the supported range 0..{max_size}"
                )
            exact_size = expected
            is_reference = True
        case int() as exact_size:
            if exact_size < 0 or exact_size > max_size:
                raise UnsupportedFormatError(
                    f"Sized length {exact_size} is outside the supported range 0..{max_size}"
                )
            is_reference = False
        case _:
            payload_limit = max_size
            if isinstance(length, Int):
                payload_limit = min(payload_limit, _integer_bounds(length)[1])
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
                config=config,
            )

    inner_fmt = fmt.fmt
    inner_tail = exact_size == 0
    match inner_fmt:
        case Bytes():
            if inner_fmt.size is not None and inner_fmt.size != exact_size:
                if is_reference:
                    raise UnsupportedFormatError(
                        "A Ref-sized field must encode exactly the referenced byte count"
                    )
                if inner_fmt.size > exact_size:
                    raise UnsupportedFormatError("Inner byte format exceeds the Sized field length")
                return st.binary(min_size=inner_fmt.size, max_size=inner_fmt.size)
            return st.binary(min_size=exact_size, max_size=exact_size)
        case Str():
            if inner_fmt.size is None:
                return _text_strategy(inner_fmt, max_size, exact_bytes=exact_size)
            if is_reference and inner_fmt.size != exact_size:
                raise UnsupportedFormatError(
                    "A Ref-sized field must encode exactly the referenced byte count"
                )
            if inner_fmt.size > exact_size:
                raise UnsupportedFormatError("Inner string format exceeds the Sized field length")
            return _text_strategy(inner_fmt, max_size)
        case _:
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
                    config=config,
                )

            raise UnsupportedFormatError(
                "A fixed/reference-sized wrapper around a variable-size format "
                "requires a custom strategy"
            )


def _append_list_tail(values: tuple[list[Any], Any]) -> list[Any]:
    prefix, last = values
    return [*prefix, last]


def _single_item_list(value: Any) -> list[Any]:
    return [value]


def _tail_sensitive(fmt: Any) -> bool:
    if isinstance(fmt, (Optional, Switch, TaggedUnion, Lazy)):
        return True
    if isinstance(fmt, Mapping):
        last_child = None
        for child in fmt.values():
            last_child = child
        return last_child is not None and _tail_sensitive(last_child)
    if isinstance(fmt, (list, tuple)):
        return bool(fmt) and _tail_sensitive(fmt[-1])
    if isinstance(fmt, Array):
        return _tail_sensitive(fmt.element_fmt)
    return False


def _fixed_list_strategy(
    item_strategy: SearchStrategy[Any],
    last_strategy: SearchStrategy[Any],
    count: int,
) -> SearchStrategy[list[Any]]:
    prefix = st.lists(item_strategy, min_size=count - 1, max_size=count - 1)
    return st.tuples(prefix, last_strategy).map(_append_list_tail)


def _array_values_strategy(  # noqa: PLR0913, PLR0917
    fmt: Array,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    dimensions: list[int],
    level: int,
    tail: bool,
    tail_sensitive: bool,
    path: FormatPath,
    config: FormatPlan | None,
) -> SearchStrategy[list[Any]]:
    count = dimensions[level]
    if count == 0:
        return st.builds(list)
    if level == len(dimensions) - 1:
        make_strategy = partial(
            _value_strategy,
            fmt.element_fmt,
            contexts,
            max_size,
            seen,
            path=path,
            config=config,
        )
    else:
        make_strategy = partial(
            _array_values_strategy,
            fmt,
            contexts,
            max_size,
            seen,
            dimensions,
            level + 1,
            tail_sensitive=tail_sensitive,
            path=path,
            config=config,
        )

    if tail and tail_sensitive:
        last_strategy = make_strategy(tail=True)
        if count == 1:
            return last_strategy.map(_single_item_list)
        item_strategy = make_strategy(tail=False)
        return _fixed_list_strategy(item_strategy, last_strategy, count)

    item_strategy = make_strategy(tail=False)
    return st.lists(item_strategy, min_size=count, max_size=count)


@st.composite
def _array_strategy_value(  # noqa: PLR0913, PLR0917
    draw: Callable[[SearchStrategy[Any]], Any],
    fmt: Array,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    element_limit: int,
    tail_sensitive: bool,
    tail: bool,
    path: FormatPath,
    config: FormatPlan | None,
) -> list[Any]:
    dimensions: list[int] = []
    product = 1
    for dim in fmt.dims or (None,):
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
    return draw(
        _array_values_strategy(
            fmt,
            contexts,
            max_size,
            seen,
            dimensions,
            0,
            tail,
            tail_sensitive,
            element_path,
            config,
        )
    )


def _array_strategy(  # noqa: PLR0913
    fmt: Array,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    tail: bool,
    path: FormatPath,
    config: FormatPlan | None,
) -> SearchStrategy[list[Any]]:
    element_size = sizeof(fmt.element_fmt)
    tail_sensitive = _tail_sensitive(fmt.element_fmt)
    element_limit = (
        max_size // element_size if isinstance(element_size, int) and element_size else max_size
    )
    if not element_limit:
        raise UnsupportedFormatError("Array element format exceeds max_size")

    return _array_strategy_value(
        fmt,
        contexts,
        max_size,
        seen,
        element_limit,
        tail_sensitive,
        tail,
        path,
        config,
    )


def _tagged_union_branch_strategy(  # noqa: PLR0913, PLR0917
    tag: Any,
    fmt: TaggedUnion,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    tail: bool,
    path: FormatPath,
    config: FormatPlan | None,
) -> SearchStrategy[Any]:
    return _value_strategy(
        fmt.fmt_by_tag[tag],
        contexts,
        max_size,
        seen,
        tail=tail,
        path=path,
        config=config,
    ).map(partial(_add_union_tag, tag=tag, fmt=fmt, contexts=contexts))


def _tagged_union_strategy(  # noqa: PLR0913
    fmt: TaggedUnion,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    tail: bool,
    path: FormatPath,
    config: FormatPlan | None,
) -> SearchStrategy[Any]:
    if fmt.struct_tag_field is None or not fmt.fmt_by_tag:
        raise UnsupportedFormatError("TaggedUnion has no supported tagged branches")

    if isinstance(fmt.tag, Ref):
        if not contexts:
            raise UnsupportedFormatError("A Ref-based TaggedUnion requires a mapping context")
        parent = contexts[-1]
        if fmt.tag.key in parent:
            tag = parent[fmt.tag.key]
            if tag not in fmt.fmt_by_tag:
                raise UnsupportedFormatError(f"Unknown TaggedUnion tag {tag!r}")
            return _tagged_union_branch_strategy(
                tag, fmt, contexts, max_size, seen, tail, path, config
            )
    return st.one_of(
        *(
            _tagged_union_branch_strategy(tag, fmt, contexts, max_size, seen, tail, path, config)
            for tag in fmt.fmt_by_tag
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


def _generated_dependency(
    dependency: FormatPath,
    *,
    path: FormatPath,
    current: Mapping[str, Any],
    contexts: FormatContext,
) -> Any:
    if dependency[: len(path)] == path:
        value: Any = current
        remaining = dependency[len(path) :]
    else:
        if not contexts:
            raise UnsupportedFormatError(f"Cannot resolve derived-field dependency {dependency!r}")
        value = contexts[0]
        remaining = dependency
    try:
        for key in remaining:
            value = value[key]
    except (IndexError, KeyError, TypeError) as exc:
        raise UnsupportedFormatError(
            f"Derived-field dependency {dependency!r} is not available yet"
        ) from exc
    return value


@st.composite
def _mapping_value_strategy(  # noqa: PLR0913, PLR0917
    draw: Callable[[SearchStrategy[Any]], Any],
    fmt: Mapping[str, Any],
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    tail: bool,
    path: FormatPath,
    config: FormatPlan | None,
    constrained_keys: set[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    child_contexts = (*contexts, result)
    last_index = len(fmt) - 1
    for index, (key, child_fmt) in enumerate(fmt.items()):
        if key in result:
            continue
        if key in constrained_keys:
            limits, allowed = _mapping_constraints(fmt, max_size, result)
        else:
            limits, allowed = {}, {}
        child_path = (*path, key)
        derivation = config.field_derivations.get(child_path) if config is not None else None
        if derivation is not None:
            inputs = {
                dependency: _generated_dependency(
                    dependency,
                    path=path,
                    current=result,
                    contexts=contexts,
                )
                for dependency in derivation.dependencies
            }
            derived = derivation.apply(inputs)
            field_range = config.field_ranges.get(child_path)
            if field_range is not None and not field_range.contains(derived):
                raise UnsupportedFormatError(
                    f"Derived value {derived!r} is outside the range at {child_path!r}"
                )
            if key in allowed and derived not in allowed[key]:
                raise UnsupportedFormatError(
                    f"Derived value {derived!r} violates a reference at {child_path!r}"
                )
            if key in limits and not _is_bounded_nonnegative_int(derived, upper_bound=limits[key]):
                raise UnsupportedFormatError(
                    f"Derived value {derived!r} exceeds its bound at {child_path!r}"
                )
            result[key] = derived
            continue

        strategy = _mapping_field_strategy(
            child_fmt,
            child_contexts,
            max_size,
            seen,
            upper_bound=limits.get(key),
            allowed_values=allowed.get(key),
            tail=tail and index == last_index,
            path=child_path,
            config=config,
        )
        hint = config.field_hints.get(child_path) if config is not None else None
        if hint is not None:
            field_range = config.field_ranges.get(child_path)
            values = tuple(
                value
                for value in hint.values
                if (allowed.get(key) is None or value in allowed[key])
                and (
                    limits.get(key) is None
                    or _is_bounded_nonnegative_int(value, upper_bound=limits[key])
                )
                and (field_range is None or field_range.contains(value))
            )
            if not values:
                raise UnsupportedFormatError(
                    f"All field hints conflict with constraints at {child_path!r}"
                )
            hinted = st.sampled_from(values)
            strategy = st.one_of(strategy, *(hinted for _ in range(hint.weight)))
        result[key] = draw(strategy)
    return result


def _value_strategy(  # noqa: PLR0911, PLR0912, PLR0913
    fmt: Any,
    contexts: FormatContext,
    max_size: int,
    seen: frozenset[int],
    *,
    tail: bool = True,
    path: FormatPath = (),
    config: FormatPlan | None = None,
) -> SearchStrategy[Any]:
    custom = _registered_strategy(fmt, contexts, max_size)
    if custom is not None:
        return custom

    match fmt:
        case Mapping():
            constrained_keys = {
                key
                for child_fmt in fmt.values()
                for _, key, _ in _walk_mapping_constraints(child_fmt, {}, max_size)
            }
            return _mapping_value_strategy(
                fmt,
                contexts,
                max_size,
                seen,
                tail,
                path,
                config,
                constrained_keys,
            )
        case list() | tuple():
            last_index = len(fmt) - 1
            return st.tuples(
                *(
                    _value_strategy(
                        child,
                        contexts,
                        max_size,
                        seen,
                        tail=tail and index == last_index,
                        path=(*path, index),
                        config=config,
                    )
                    for index, child in enumerate(fmt)
                )
            ).map(list)
        case bytes() | str():
            raise UnsupportedFormatError(
                f"{type(fmt).__name__} cannot be used as an fmtspec format"
            )
        case Int() as int_fmt:
            enum_policy = (
                config.enum_policy_for(path) if config is not None else _DEFAULT_ENUM_POLICY
            )
            return _int_strategy(int_fmt, enum_policy=enum_policy)
        case Float():
            return st.floats(
                width=32 if fmt.size == _FLOAT32_SIZE else 64,
                allow_nan=False,
                allow_infinity=False,
            )
        case Bytes(size=None):
            return st.binary(max_size=max_size)
        case Bytes(size=size):
            if size > max_size:
                raise UnsupportedFormatError(f"Byte size {size} exceeds max_size={max_size}")
            return st.binary(min_size=size, max_size=size)
        case Str():
            return _text_strategy(fmt, max_size)
        case Literal():
            return st.just(fmt.value)
        case Null():
            return st.none()
        case Bitfield():
            field_range = config.field_ranges.get(path) if config is not None else None
            return _bitfield_strategy(fmt, field_range=field_range)
        case Bitfields():
            return _value_strategy(
                fmt.fmt,
                contexts,
                max_size,
                seen,
                path=path,
                config=config,
            )
        case Optional():
            inner = _value_strategy(
                fmt.fmt,
                contexts,
                max_size,
                seen,
                tail=tail,
                path=path,
                config=config,
            )
            return st.one_of(st.none(), inner) if tail else inner
        case Array():
            return _array_strategy(
                fmt,
                contexts,
                max_size,
                seen,
                tail=tail,
                path=path,
                config=config,
            )
        case Sized():
            return _sized_strategy(fmt, contexts, max_size, seen, path, config)
        case Switch():
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
                config=config,
            )
        case TaggedUnion():
            return _tagged_union_strategy(
                fmt,
                contexts,
                max_size,
                seen,
                tail=tail,
                path=path,
                config=config,
            )
        case TakeUntil():
            strategy = _value_strategy(
                fmt.fmt,
                contexts,
                max_size,
                seen,
                tail=True,
                path=path,
                config=config,
            )
            return strategy.filter(partial(_valid_take_until_value, fmt=fmt, contexts=contexts))
        case Lazy():
            if id(fmt) in seen:
                raise UnsupportedFormatError(
                    "Recursive Lazy formats require a registered strategy with a recursion bound"
                )
            return _value_strategy(
                fmt.get_format(),
                contexts,
                max_size,
                seen | {id(fmt)},
                tail=tail,
                path=path,
                config=config,
            )
        case Iterable():
            return _value_strategy(
                tuple(fmt),
                contexts,
                max_size,
                seen,
                path=path,
                config=config,
            )
        case _:
            raise UnsupportedFormatError(
                f"No strategy is registered for format type "
                f"{type(fmt).__module__}.{type(fmt).__qualname__}"
            )


def format_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
) -> SearchStrategy[Any]:
    """Build a Hypothesis strategy for Python values accepted by ``fmt``.

    ``max_size`` bounds generated variable-length values and arrays. Dynamic
    fields that depend on earlier mapping keys are generated in field order.
    """
    if max_size < 1:
        raise ValueError("max_size must be at least 1")
    plan = compile_format(fmt)
    return _value_strategy(
        plan.fmt,
        (),
        max_size,
        frozenset(),
        config=plan,
    )


def binary_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
) -> SearchStrategy[bytes]:
    """Build a strategy for valid encoded bytes accepted by ``fmt``."""
    plan = compile_format(fmt)
    values = format_strategy(plan, max_size=max_size)
    strategy = values.map(partial(_encode_value, fmt=plan.fmt))
    return strategy.filter(partial(_within_size, maximum=max_size))
