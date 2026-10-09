import hashlib
from typing import Annotated

import msgspec
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fmtfuzz import (
    Corpus,
    FormatChild,
    FormatMetadata,
    FormatNode,
    FuzzConfig,
    Fuzzer,
    binary_strategy,
    describe_format,
    format_strategy,
    mutate_malformed,
    mutate_valid,
    register_format_strategy,
)
from fmtspec import decode, encode, types
from fmtspec.types._converter import Converter


class NumberBranch(msgspec.Struct, tag_field="kind", tag="num"):
    value: Annotated[int, types.u8]


class RawBranch(msgspec.Struct, tag_field="kind", tag="raw"):
    value: Annotated[bytes, types.Bytes(2)]


@settings(max_examples=25, derandomize=True)
@given(format_strategy(types.u8))
def test_integer_value_strategy(value):
    assert 0 <= value <= 255


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
