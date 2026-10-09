import hashlib
from enum import IntEnum
from typing import Annotated

import msgspec
import pytest
from hypothesis import event, find, given, settings, target
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from fmtfuzz import (
    Corpus,
    DecisionSeed,
    EnumPolicy,
    FieldDerivation,
    FieldHint,
    FieldRange,
    FormatChild,
    FormatMetadata,
    FormatNode,
    FormatPlan,
    FormatPlanError,
    FuzzConfig,
    Fuzzer,
    binary_strategy,
    capture_decision_seed,
    compile_format,
    decision_seed_strategy,
    describe_format,
    format_strategy,
    fuzz_strategy,
    message_sequence_strategy,
    mutate_malformed,
    mutate_valid,
    register_format_strategy,
    replay_decision_seed,
)
from fmtspec import DecodeError, ExcessDecodeError, decode, encode, types
from fmtspec.types import Switch
from fmtspec.types._converter import Converter


class _PacketKind(IntEnum):
    PING = 1
    PONG = 4


def _copy_value(values):
    return values[("count",)]


def _raise_derivation(_values):
    raise RuntimeError("derived callback failed")


def _copy_sequence_is_valid(messages):
    if len(messages) != 1:
        return False
    try:
        decoded = decode(messages[0], {"count": types.u8, "copy": types.u8})
    except (DecodeError, ExcessDecodeError):
        return False
    return decoded["copy"] == decoded["count"]


def _copy_message_is_valid(data):
    decoded = decode(data, {"count": types.u8, "copy": types.u8})
    return decoded["copy"] == decoded["count"]


class NumberBranch(msgspec.Struct, tag_field="kind", tag="num"):
    value: Annotated[int, types.u8]


class RawBranch(msgspec.Struct, tag_field="kind", tag="raw"):
    value: Annotated[bytes, types.Bytes(2)]


class _MessageSequenceStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.accepted = 0
        self.last_value = None

    @rule(
        messages=message_sequence_strategy(
            types.u8,
            min_messages=1,
            max_messages=3,
            max_message_size=1,
        )
    )
    def process_messages(self, messages):
        for data in messages:
            try:
                value = decode(data, types.u8)
            except (DecodeError, ExcessDecodeError):
                event("message rejected")
            else:
                self.accepted += 1
                self.last_value = value

    @invariant()
    def tracks_valid_messages(self):
        assert self.accepted >= 0
        assert self.last_value is None or 0 <= self.last_value <= 255


TestMessageSequenceStateMachine = _MessageSequenceStateMachine.TestCase
TestMessageSequenceStateMachine.settings = settings(
    max_examples=10,
    stateful_step_count=4,
    derandomize=True,
)


@settings(max_examples=25, derandomize=True)
@given(format_strategy(types.u8))
def test_integer_value_strategy(value):
    assert 0 <= value <= 255


@settings(max_examples=25, derandomize=True)
@given(format_strategy((types.u8, types.u16)))
def test_sequence_format_strategy_generates_a_list(value):
    assert isinstance(value, list)
    assert len(value) == 2
    assert 0 <= value[0] <= 255
    assert 0 <= value[1] <= 65535


@settings(max_examples=30, derandomize=True)
@given(
    format_strategy(
        {
            "length": types.u8,
            "data": types.array(types.u8, dims=types.Ref("length")),
        },
        max_size=32,
    )
)
def test_array_reference_strategy_respects_maximum(value):
    assert value["length"] == len(value["data"])


def test_single_item_array_supports_a_tail_consuming_element():
    fmt = {
        "kind": types.u8,
        "items": types.array(
            types.Switch(types.Ref("kind"), {1: types.u8}),
            dims=1,
        ),
    }

    @settings(max_examples=20, derandomize=True)
    @given(format_strategy(fmt))
    def check(value):
        assert value["kind"] == 1
        assert len(value["items"]) == 1
        assert 0 <= value["items"][0] <= 255

    check()


def test_reference_sized_field_strategy_respects_maximum():
    fmt = {
        "length": types.u8,
        "payload": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }

    @settings(max_examples=30, derandomize=True)
    @given(format_strategy(fmt, max_size=32))
    def check(value):
        assert value["length"] == len(value["payload"])

    check()


def test_switch_strategy_generates_a_matching_case():
    fmt = {
        "kind": types.u8,
        "body": types.Switch(
            types.Ref("kind"),
            {1: types.u16, 2: types.Bytes(2)},
        ),
    }

    @settings(max_examples=20, derandomize=True)
    @given(format_strategy(fmt))
    def check(value):
        if value["kind"] == 1:
            assert isinstance(value["body"], int)
        else:
            assert value["kind"] == 2
            assert len(value["body"]) == 2

    check()


@settings(max_examples=20, derandomize=True)
@given(binary_strategy(types.TakeUntil(types.str_ascii, b"\0")))
def test_terminator_strategy_excludes_terminator_from_value(data):
    assert b"\0" not in data[:-1]


def test_describe_format_exposes_composite_metadata_and_cycles():
    recursive = {}
    recursive["next"] = types.Lazy(lambda: recursive)

    metadata = describe_format(
        {
            "header": types.u8,
            "payload": types.Sized(length=types.u8, fmt=types.Bytes()),
            "recursive": recursive,
        }
    )

    assert isinstance(metadata, FormatNode)
    assert metadata.children[0].role == "field"
    assert metadata.children[1].children[0].role == "length"
    assert metadata.children[1].children[1].role == "inner"
    recursive_node = metadata.children[2].children[0].children[0]
    assert recursive_node.recursive


def test_custom_format_can_expose_children():
    class CompositeFormat(FormatMetadata):
        def __fmtfuzz_children__(self):
            return (FormatChild(key="value", role="payload", fmt=types.u8),)

        def encode(self, stream, value, *, context):
            types.u8.encode(stream, value["value"], context=context)

        def decode(self, stream, *, context):
            return {"value": types.u8.decode(stream, context=context)}

    metadata = describe_format(CompositeFormat())

    assert metadata.size is ...
    assert metadata.children[0].key == "value"
    assert metadata.children[0].role == "payload"


def test_converter_exposes_its_inner_format_to_metadata():
    metadata = describe_format(Converter(types.u8))

    assert metadata.children[0].fmt is types.u8
    assert metadata.children[0].role == "inner"


@settings(max_examples=20, derandomize=True)
@given(
    format_strategy(
        {
            "kind": types.Str(3),
            "body": types.TaggedUnion(
                tag=types.Ref("kind"),
                fmt_map={0: NumberBranch, 1: RawBranch},
            ),
        }
    )
)
def test_tagged_union_strategy_generates_matching_branches(value):
    data = encode(
        value,
        {
            "kind": types.Str(3),
            "body": types.TaggedUnion(
                tag=types.Ref("kind"),
                fmt_map={0: NumberBranch, 1: RawBranch},
            ),
        },
    )
    decoded = decode(
        data,
        {
            "kind": types.Str(3),
            "body": types.TaggedUnion(
                tag=types.Ref("kind"),
                fmt_map={0: NumberBranch, 1: RawBranch},
            ),
        },
    )
    assert decoded["kind"] == value["kind"]
    expected_type = NumberBranch if value["kind"] == "num" else RawBranch
    assert type(decoded["body"]) is expected_type


@settings(max_examples=20, derandomize=True)
@given(binary_strategy(types.Optional(types.u8)))
def test_optional_strategy_generates_valid_encodings(data):
    assert decode(data, types.Optional(types.u8)) in (None, *range(256))


@settings(max_examples=30, derandomize=True)
@given(
    format_strategy(
        {
            "maybe": types.Optional(types.u8),
            "last": types.u8,
        }
    )
)
def test_optional_strategy_only_generates_none_at_end(value):
    assert value["maybe"] is not None


@settings(max_examples=30, derandomize=True)
@given(binary_strategy(types.Sized(length=types.u8, fmt=types.Bytes()), max_size=1024))
def test_sized_strategy_respects_length_prefix_range(data):
    assert data[0] == len(data) - 1
    assert data[0] <= 255


@settings(max_examples=30, derandomize=True)
@given(binary_strategy({"count": types.u8, "items": types.array(types.u16, dims=3)}))
def test_binary_strategy_generates_decodable_samples(data):
    result = decode(data, {"count": types.u8, "items": types.array(types.u16, dims=3)})
    assert len(result["items"]) == 3


def test_valid_mutation_preserves_format_and_size():
    fmt = {"word": types.u16le, "marker": types.Bytes(2)}
    original = encode({"word": 7, "marker": b"ok"}, fmt)

    mutated = mutate_valid(original, fmt, seed=7)

    assert mutated != original
    assert len(mutated) == len(original)
    decode(mutated, fmt)


def test_valid_mutation_preserves_reference_lengths():
    fmt = {
        "length": types.u8,
        "payload": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }
    original = encode({"length": 2, "payload": b"ok"}, fmt)

    mutated = mutate_valid(original, fmt, seed=0)

    assert mutated != original
    assert len(mutated) == len(original)
    assert decode(mutated, fmt)["length"] == 2


def test_valid_mutation_handles_inline_bitfields():
    fmt = {
        "ready": types.Bitfield(bits=1),
        "mode": types.Bitfield(bits=2),
    }
    original = encode({"ready": True, "mode": 1}, fmt)

    mutated = mutate_valid(original, fmt, seed=0)

    assert mutated != original
    assert decode(mutated, fmt) != {"ready": True, "mode": 1}


def test_malformed_mutation_is_bounded_and_changes_input():
    fmt = (types.u8, types.u8)
    original = encode((1, 2), fmt)

    for seed in range(10):
        mutated = mutate_malformed(original, fmt, seed=seed, max_size=8)
        assert mutated != original
        assert len(mutated) <= 8


def test_corpus_deduplicates_and_loads_deterministically(tmp_path):
    corpus = Corpus(tmp_path / "corpus", max_size=8)

    assert corpus.add(b"one")
    assert not corpus.add(b"one")
    assert corpus.extend([b"two", b"three"]) == 2
    assert corpus.load() == tuple(
        sorted(
            (b"one", b"two", b"three"),
            key=lambda data: hashlib.sha256(data).hexdigest(),
        )
    )


def test_custom_strategy_registration():
    class CustomFormat:
        size = 1

        def encode(self, stream, value, *, context):
            types.u8.encode(stream, value, context=context)

        def decode(self, stream, *, context):
            return types.u8.decode(stream, context=context)

    register_format_strategy(
        CustomFormat,
        lambda _fmt, _contexts, max_size: st.integers(min_value=0, max_value=max_size),
    )
    strategy = format_strategy(CustomFormat())

    @settings(max_examples=10, derandomize=True)
    @given(strategy)
    def check(value):
        assert value >= 0

    check()


def test_fuzzer_run_returns_execution_counts():
    fuzzer = Fuzzer(types.u8, lambda data: decode(data, types.u8))

    result = fuzzer.run(FuzzConfig(max_examples=20, max_input_size=8, seed=1))

    assert result.executions >= 20
    assert result.accepted + result.rejected == result.executions


def test_fuzzer_persists_feedback_novel_inputs(tmp_path):
    corpus = Corpus(tmp_path / "corpus", max_size=8)
    fuzzer = Fuzzer(
        types.u8,
        lambda _data: None,
        corpus=corpus,
        feedback=lambda data: data,
    )

    result = fuzzer.run(FuzzConfig(max_examples=10, max_input_size=4, seed=2))

    assert result.corpus_entries > 0
    assert result.corpus_entries == len(corpus)


def test_corpus_rejects_oversized_input(tmp_path):
    corpus = Corpus(tmp_path / "corpus", max_size=2)

    with pytest.raises(ValueError, match="exceeds"):
        corpus.add(b"too large")


@settings(max_examples=30, derandomize=True)
@given(
    message_sequence_strategy(
        types.u8,
        min_messages=1,
        max_messages=5,
        max_message_size=2,
    )
)
def test_message_sequence_strategy_respects_count_and_size_bounds(messages):
    assert 1 <= len(messages) <= 5
    assert all(len(message) <= 2 for message in messages)
    event(f"message count: {len(messages)}")
    target(sum(map(len, messages)), label="sequence bytes")


@pytest.mark.parametrize(
    ("min_messages", "max_messages", "max_message_size"),
    [(-1, 2, 4), (3, 2, 4), (0, -1, 4), (0, 2, 0)],
)
def test_message_sequence_strategy_rejects_invalid_bounds(
    min_messages,
    max_messages,
    max_message_size,
):
    with pytest.raises(ValueError, match="message"):
        message_sequence_strategy(
            types.u8,
            min_messages=min_messages,
            max_messages=max_messages,
            max_message_size=max_message_size,
        )


def test_message_sequence_strategy_supports_compiled_plans_and_corpus(tmp_path):
    fmt = {"opcode": types.u8}
    plan = compile_format(fmt, field_hints={("opcode",): FieldHint((0xA5,), weight=2)})
    hinted = message_sequence_strategy(
        plan,
        min_messages=1,
        max_messages=2,
        max_message_size=1,
    )

    assert b"\xa5" in find(hinted, lambda messages: b"\xa5" in messages)

    corpus = Corpus(tmp_path / "sequence-corpus", max_size=1)
    corpus.add(b"\xfe")
    seeded = message_sequence_strategy(
        plan,
        min_messages=1,
        max_messages=2,
        max_message_size=1,
        corpus=corpus,
    )

    assert b"\xfe" in find(seeded, lambda messages: b"\xfe" in messages)


def test_message_sequence_strategy_supports_zero_messages():
    strategy = message_sequence_strategy(
        types.u8,
        min_messages=0,
        max_messages=0,
        max_message_size=1,
    )

    assert find(strategy, lambda _messages: True) == ()


def test_compiled_plan_tracks_dependencies_and_field_hints():
    fmt = {
        "count": types.u8,
        "items": types.array(types.u16, dims=types.Ref("count")),
    }

    plan = compile_format(fmt, field_hints={("count",): FieldHint((2, 3), weight=3)})

    assert isinstance(plan, FormatPlan)
    assert plan.dependencies[0].source_path == ("items",)
    assert plan.dependencies[0].target_path == ("count",)
    assert plan.dependencies[0].relation == "dimension"
    assert plan.hint_for(("count",)) == FieldHint((2, 3), weight=3)
    assert compile_format(plan) is plan
    switch_plan = compile_format(
        {
            "kind": types.u8,
            "body": types.Switch(types.Ref("kind"), {1: types.u8, 2: types.Bytes(2)}),
        }
    )
    switch_node = next(node for node in switch_plan.nodes() if node.kind is Switch)
    assert switch_node.choices == (1, 2)


def test_field_hints_are_generated_alongside_ordinary_values():
    fmt = {"opcode": types.u8}
    strategy = format_strategy(fmt, field_hints={("opcode",): FieldHint((0xA5,), weight=2)})

    assert find(strategy, lambda value: value["opcode"] == 0xA5) == {"opcode": 0xA5}


def test_enum_strategy_generates_declared_and_undefined_values_by_default():
    enum_fmt = types.Int(size=1, byteorder="big", signed=False, enum=_PacketKind)
    strategy = format_strategy({"kind": enum_fmt})

    known = find(strategy, lambda value: int(value["kind"]) == 1)
    unknown = find(strategy, lambda value: int(value["kind"]) == 2)

    assert known["kind"] is _PacketKind.PING
    assert type(unknown["kind"]) is int
    assert int(unknown["kind"]) not in {int(member) for member in _PacketKind}
    encoded = encode(unknown, {"kind": enum_fmt})
    assert type(decode(encoded, {"kind": enum_fmt})["kind"]) is int


def test_enum_policy_and_field_range_select_unknown_values():
    enum_fmt = types.Int(size=1, byteorder="big", signed=False, enum=_PacketKind)
    strategy = format_strategy(
        {"kind": enum_fmt},
        field_ranges={("kind",): FieldRange(min_value=2, max_value=3)},
        enum_policies={("kind",): EnumPolicy(known_weight=0, unknown_weight=1)},
    )

    unknown = find(strategy, lambda value: value["kind"] == 2)
    assert 2 <= unknown["kind"] <= 3


def test_enum_policy_can_keep_generation_to_declared_members():
    enum_fmt = types.Int(size=1, byteorder="big", signed=False, enum=_PacketKind)
    strategy = format_strategy(
        {"kind": enum_fmt},
        enum_policies={("kind",): EnumPolicy(known_weight=1, unknown_weight=0)},
    )

    @settings(max_examples=20, derandomize=True)
    @given(strategy)
    def check(value):
        assert int(value["kind"]) in {int(member) for member in _PacketKind}

    check()


def test_enum_complement_strategy_handles_nearly_full_integer_domains():
    dense_enum = IntEnum("DenseEnum", {f"VALUE_{value}": value for value in range(255)})
    enum_fmt = types.Int(size=1, byteorder="big", signed=False, enum=dense_enum)
    strategy = format_strategy(
        {"kind": enum_fmt},
        enum_policies={("kind",): EnumPolicy(known_weight=0, unknown_weight=1)},
    )

    assert find(strategy, lambda value: value["kind"] == 255) == {"kind": 255}


def test_field_hints_can_emphasize_unknown_enum_values():
    enum_fmt = types.Int(size=1, byteorder="big", signed=False, enum=_PacketKind)
    strategy = format_strategy(
        {"kind": enum_fmt},
        field_hints={("kind",): FieldHint((0xA5,), weight=2)},
    )

    assert find(strategy, lambda value: value["kind"] == 0xA5)["kind"] == 0xA5


def test_field_ranges_constrain_integer_and_bitfield_generation():
    int_strategy = format_strategy(
        {"value": types.i8},
        field_ranges={("value",): FieldRange(min_value=-5, max_value=3)},
    )
    bitfield_strategy = format_strategy(
        {"mode": types.Bitfield(bits=4)},
        field_ranges={("mode",): FieldRange(min_value=3, max_value=6)},
    )

    @settings(max_examples=30, derandomize=True)
    @given(int_strategy, bitfield_strategy)
    def check(integer, bitfield):
        assert -5 <= integer["value"] <= 3
        assert 3 <= bitfield["mode"] <= 6

    check()


def test_field_range_targets_a_named_packed_bitfield():
    fmt = {
        "flags": types.Bitfields({"mode": types.Bitfield(bits=4), "ready": types.Bitfield(bits=1)})
    }
    strategy = format_strategy(
        fmt,
        field_ranges={("flags", "mode"): FieldRange(min_value=2, max_value=3)},
    )

    @settings(max_examples=20, derandomize=True)
    @given(strategy)
    def check(value):
        assert 2 <= value["flags"]["mode"] <= 3

    check()


def test_bitfield_strategy_includes_curated_width_patterns():
    strategy = format_strategy({"flags": types.Bitfield(bits=4)})

    for pattern in (0, 0xF, 0x1, 0x2, 0x4, 0x8, 0x5, 0xA):
        assert find(strategy, lambda value, pattern=pattern: value["flags"] == pattern)


def test_field_derivation_computes_values_after_dependencies():
    fmt = {"count": types.u8, "copy": types.u8}
    strategy = format_strategy(
        fmt,
        field_derivations={
            ("copy",): FieldDerivation(dependencies=(("count",),), derive=_copy_value),
        },
    )

    @settings(max_examples=30, derandomize=True)
    @given(strategy)
    def check(value):
        assert value["copy"] == value["count"]

    check()


def test_field_derivation_rejects_forward_dependencies():
    with pytest.raises(FormatPlanError, match="must precede"):
        compile_format(
            {"copy": types.u8, "count": types.u8},
            field_derivations={
                ("copy",): FieldDerivation(
                    dependencies=(("count",),),
                    derive=_copy_value,
                ),
            },
        )


def test_field_derivation_callback_errors_are_visible():
    strategy = format_strategy(
        {"count": types.u8, "copy": types.u8},
        field_derivations={
            ("copy",): FieldDerivation(
                dependencies=(("count",),),
                derive=_raise_derivation,
            ),
        },
    )

    with pytest.raises(RuntimeError, match="derived callback failed"):
        find(strategy, lambda _value: True)


def test_valid_mutation_recomputes_derived_fields():
    fmt = {"count": types.u8, "copy": types.u8}
    plan = compile_format(
        fmt,
        field_derivations={
            ("copy",): FieldDerivation(dependencies=(("count",),), derive=_copy_value),
        },
    )
    original = encode({"count": 1, "copy": 1}, fmt)

    mutated = mutate_valid(original, plan, seed=0)
    decoded = decode(mutated, fmt)

    assert decoded["copy"] == decoded["count"]


def test_valid_mutation_respects_field_ranges_and_recomputes_derivations():
    fmt = {"count": types.u8, "copy": types.u8}
    plan = compile_format(
        fmt,
        field_ranges={("count",): FieldRange(min_value=1, max_value=5)},
        field_derivations={
            ("copy",): FieldDerivation(dependencies=(("count",),), derive=_copy_value),
        },
    )
    original = encode({"count": 1, "copy": 1}, fmt)

    for seed in range(20):
        decoded = decode(mutate_valid(original, plan, seed=seed), fmt)
        assert 1 <= decoded["count"] <= 5
        assert decoded["copy"] == decoded["count"]


def test_field_range_and_enum_policy_validate_targets_and_domains():
    with pytest.raises(FormatPlanError, match="not representable"):
        compile_format(
            {"value": types.u8},
            field_ranges={("value",): FieldRange(min_value=-1)},
        )

    with pytest.raises(FormatPlanError, match="declared enum"):
        compile_format(
            {"kind": types.u8},
            enum_policies={("kind",): EnumPolicy()},
        )
    with pytest.raises(ValueError, match="nonzero weight"):
        EnumPolicy(known_weight=0, unknown_weight=0)


def test_configured_plan_policies_flow_through_strategy_and_fuzzer_apis():
    fmt = {"count": types.u8, "copy": types.u8}
    derivations = {
        ("copy",): FieldDerivation(dependencies=(("count",),), derive=_copy_value),
    }
    ranges = {("count",): FieldRange(min_value=1, max_value=5)}
    plan = compile_format(fmt, field_ranges=ranges, field_derivations=derivations)
    data = find(
        binary_strategy(plan),
        _copy_message_is_valid,
    )
    decoded = decode(data, fmt)
    assert 1 <= decoded["count"] <= 5
    assert decoded["copy"] == decoded["count"]

    fuzzer = Fuzzer(
        fmt,
        lambda _data: None,
        field_ranges=ranges,
        field_derivations=derivations,
    )
    assert fuzzer.plan.field_ranges == plan.field_ranges
    assert fuzzer.plan.field_derivations == plan.field_derivations

    mixed = find(
        fuzz_strategy(fmt, field_ranges=ranges, field_derivations=derivations),
        _copy_message_is_valid,
    )
    assert _copy_message_is_valid(mixed)

    sequence = find(
        message_sequence_strategy(
            fmt,
            min_messages=1,
            max_messages=1,
            field_ranges=ranges,
            field_derivations=derivations,
        ),
        _copy_sequence_is_valid,
    )
    assert len(sequence) == 1


def test_valid_mutation_changes_dynamic_array_shape_with_its_count():
    fmt = {
        "count": types.u8,
        "items": types.array(types.u8, dims=types.Ref("count")),
    }
    original = encode({"count": 2, "items": [1, 2]}, fmt)
    results = (mutate_valid(original, fmt, seed=seed, max_size=16) for seed in range(32))
    decoded = [decode(data, fmt) for data in results]

    assert any(len(value["items"]) != 2 for value in decoded)
    assert all(value["count"] == len(value["items"]) for value in decoded)


def test_valid_mutation_toggles_optional_presence():
    fmt = types.Optional(types.u8)
    original = encode(None, fmt)

    mutated = mutate_valid(original, fmt, seed=1)

    assert decode(mutated, fmt) == 0


def test_valid_mutation_can_select_an_alternate_switch_branch():
    fmt = {
        "kind": types.u8,
        "body": types.Switch(types.Ref("kind"), {1: types.u8, 2: types.Bytes(2)}),
    }
    original = encode({"kind": 1, "body": 7}, fmt)

    mutated = next(
        mutate_valid(original, fmt, seed=seed)
        for seed in range(32)
        if decode(mutate_valid(original, fmt, seed=seed), fmt)["kind"] == 2
    )

    assert decode(mutated, fmt) == {"kind": 2, "body": b"\0\0"}


def test_valid_mutation_can_select_an_alternate_tagged_union_branch():
    fmt = {
        "kind": types.Str(3),
        "body": types.TaggedUnion(
            tag=types.Ref("kind"),
            fmt_map={0: NumberBranch, 1: RawBranch},
        ),
    }
    original = encode(
        {"kind": "num", "body": {"kind": "num", "value": 7}},
        fmt,
    )
    mutated = next(
        mutate_valid(original, fmt, seed=seed)
        for seed in range(32)
        if decode(mutate_valid(original, fmt, seed=seed), fmt)["kind"] == "raw"
    )

    decoded = decode(mutated, fmt)
    assert decoded["kind"] == "raw"
    assert type(decoded["body"]) is RawBranch


def test_malformed_mutation_targets_referenced_length_fields():
    fmt = {
        "length": types.u8,
        "payload": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }
    original = encode({"length": 2, "payload": b"ok"}, fmt)
    targeted = None
    for seed in range(32):
        candidate = mutate_malformed(original, fmt, seed=seed, max_size=8)
        if candidate[1:] == original[1:] and candidate[0] != original[0]:
            targeted = candidate
            break

    assert targeted is not None
    with pytest.raises((DecodeError, ExcessDecodeError)):
        decode(targeted, fmt)


def test_malformed_mutation_targets_switch_selectors():
    fmt = {
        "kind": types.u8,
        "body": types.Switch(types.Ref("kind"), {1: types.u8, 2: types.Bytes(2)}),
    }
    original = encode({"kind": 1, "body": 7}, fmt)
    targeted = None
    for seed in range(32):
        candidate = mutate_malformed(original, fmt, seed=seed, max_size=8)
        if candidate[1:] == original[1:] and candidate[0] not in (1, 2):
            targeted = candidate
            break

    assert targeted is not None
    with pytest.raises(DecodeError):
        decode(targeted, fmt)


def test_malformed_mutation_targets_terminator_bytes():
    fmt = types.TakeUntil(types.str_ascii, b"\0")
    original = encode("ok", fmt)
    targeted = None
    for seed in range(32):
        candidate = mutate_malformed(original, fmt, seed=seed, max_size=8)
        if candidate[:-1] == original[:-1] and candidate[-1:] != original[-1:]:
            targeted = candidate
            break

    assert targeted is not None
    with pytest.raises(DecodeError):
        decode(targeted, fmt)


def test_decision_seed_capture_replay_and_strategy():
    fmt = {
        "length": types.u8,
        "payload": types.Sized(length=types.Ref("length"), fmt=types.Bytes()),
    }
    original = encode({"length": 2, "payload": b"ok"}, fmt)
    seed = capture_decision_seed(original, fmt)

    assert isinstance(seed, DecisionSeed)
    assert replay_decision_seed(seed) == original
    assert decode(seed.mutate(seed=4, max_size=16), fmt) is not None

    @settings(max_examples=8, derandomize=True)
    @given(decision_seed_strategy(types.u8))
    def check(generated):
        assert replay_decision_seed(generated) == encode(generated.value, types.u8)

    check()
