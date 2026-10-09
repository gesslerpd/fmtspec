# Structure-aware fuzzing

`fmtfuzz` builds on `fmtspec` format specifications to generate valid binary
inputs and mutate them without losing field boundaries. Hypothesis is a runtime
dependency of the `fmtfuzz` package; HypoFuzz is not required.

## Python API

```python
from fmtspec import decode, types
from fmtfuzz import FuzzConfig, Fuzzer

packet_fmt = {
    "kind": types.u8,
    "payload": types.Sized(length=types.u16, fmt=types.Bytes()),
}


def parse_packet(data: bytes) -> None:
    decode(data, packet_fmt)


result = Fuzzer(packet_fmt, parse_packet).run(
    FuzzConfig(max_examples=500, max_input_size=1024, seed=2026)
)
print(result)
```

`Fuzzer` passes each sample to a callback as `bytes`. By default, fmtspec
`DecodeError` and `ExcessDecodeError` exceptions are treated as expected
rejections; other target exceptions are Hypothesis failures and include a
shrunk reproducing input. Add other expected exception types with
`expected_exceptions=(...)` when constructing `Fuzzer`.

`FuzzConfig` bounds examples and input size and optionally sets a deterministic
seed, Hypothesis deadline, and example database. The returned `FuzzResult`
reports target executions, accepted/rejected inputs, and current corpus size.
Unexpected target failures propagate instead of returning a success-shaped
result.

## Hypothesis strategies and HypoFuzz

Use `format_strategy(fmt)` to generate Python values,
`binary_strategy(fmt)` to generate their valid encodings, or
`fuzz_strategy(fmt)` to combine valid encodings, structure-preserving and
structural valid mutations, and malformed mutations. `binary_strategy()` is
valid-only; the mixed campaign strategy also includes malformed inputs. A
strategy can be used in an ordinary Hypothesis test. Hypothesis remains in
control of generation, shrinking, deadlines, settings, and its example database:

```python
from hypothesis import event, given, target
from fmtspec import DecodeError, ExcessDecodeError
from fmtfuzz import fuzz_strategy


@given(fuzz_strategy(packet_fmt, max_size=1024))
def test_packet_parser(data: bytes) -> None:
    event("empty" if not data else "non-empty")
    target(len(data), label="input size")
    try:
        parse_packet(data)
    except (DecodeError, ExcessDecodeError):
        event("rejected")
    else:
        event("accepted")
```

`event()` records semantic categories and `target()` records a numeric
objective. These signals are useful to HypoFuzz as well as in normal Hypothesis
test runs. Other unexpected target exceptions should remain uncaught so
Hypothesis can report and shrink them.

For multiple independent messages, `message_sequence_strategy()` returns a
bounded tuple. It uses the same mixed strategy for each message:

```python
from hypothesis import given
from fmtfuzz import message_sequence_strategy


@given(
    message_sequence_strategy(
        packet_fmt,
        min_messages=1,
        max_messages=8,
        max_message_size=1024,
    )
)
def test_packet_batch(messages: tuple[bytes, ...]) -> None:
    for message in messages:
        parse_packet(message)
```

Each message is generated independently; the strategy bounds both the number
of messages and each message's byte length, so total payload bytes are at most
`max_messages * max_message_size`. It does not model dependencies between
messages.

For stateful request/response protocols, define the transitions and invariants
with Hypothesis's stateful API, and use `fuzz_strategy()` as a rule argument.
This keeps protocol-specific state semantics with the test:

```python
from fmtspec import decode, encode
from hypothesis import event
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from fmtfuzz import fuzz_strategy


class PacketSessionMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.last_packet = None

    @rule(data=fuzz_strategy(packet_fmt, max_size=1024))
    def receive(self, data: bytes) -> None:
        try:
            self.last_packet = decode(data, packet_fmt)
        except (DecodeError, ExcessDecodeError):
            event("rejected")
        else:
            event("accepted")

    @invariant()
    def last_packet_roundtrips(self) -> None:
        if self.last_packet is not None:
            assert decode(encode(self.last_packet, packet_fmt), packet_fmt) == self.last_packet


TestPacketSession = PacketSessionMachine.TestCase
```

Adapt the rule to call the real session API and assert invariants over its
state. Hypothesis and HypoFuzz will then explore sequences of rule calls.

Install HypoFuzz separately if adaptive coverage-guided scheduling is wanted.
It discovers ordinary Hypothesis tests (including state-machine test cases);
run the test module through its Hypothesis CLI:

```console
hypothesis fuzz tests/test_packet_parser.py
```

This `@given`/state-machine path is the recommended HypoFuzz integration.
`Fuzzer.run()` is a bounded convenience runner that invokes its own Hypothesis
test directly; it is not itself a discoverable test for HypoFuzz. `fmtfuzz`
does not implement its own coverage scheduler. In `Fuzzer.run()`, the optional
feedback callback can return a hashable novelty key; the first input for each
new key is saved to the optional corpus.

## Compiled plans, hints, and decision seeds

`compile_format(fmt)` creates an explicit reusable `FormatPlan` containing the
format tree, field paths, sizes, available enum/branch choices, and discovered
`Ref` dependencies. Pass the plan to strategy or mutation APIs to reuse it; raw
formats remain accepted as convenience inputs. A plan describes the format as
it existed at compilation, so do not mutate the source format afterward.

`FieldHint` supplies preferred values for a scalar field, such as protocol
magic values, uncommon branch selectors, or a specific unknown enum value.
Values are sampled alongside ordinary strategy values, with `weight`
controlling their relative frequency:

```python
from fmtfuzz import FieldHint, compile_format, binary_strategy

plan = compile_format(
    packet_fmt,
    field_hints={
        ("kind",): FieldHint((0x7E, 0xA5), weight=3),
    },
)
packet_bytes = binary_strategy(plan, max_size=1024)
```

`FieldRange` applies inclusive hard bounds to an integer or bitfield field.
The range must fit the field's encoded domain and intersects other generation
constraints such as references and field hints. Valid mutations respect these
ranges too; they do not change what the underlying `fmtspec` decoder accepts.

`Int` formats with a declared enum generate both named members and unnamed,
representable integer values by default. These unknown values are valid
encodings, but they have no declared enum meaning: a normal `IntEnum` decode
returns the raw integer for an unknown value. `IntFlag` may return an unnamed
flag combination. Use `EnumPolicy` to change the relative weights or disable
either category for a specific field. The complement strategy respects the
integer width and any `FieldRange` without building a list of every possible
integer or relying on high-rejection filtering. `FieldHint` can explicitly
emphasize a representable unknown value.

```python
from enum import IntEnum

from fmtfuzz import EnumPolicy, FieldHint, FieldRange, compile_format
from fmtspec import types


class Kind(IntEnum):
    PING = 1
    PONG = 2


packet_fmt = {
    "kind": types.Int(size=1, byteorder="big", signed=False, enum=Kind),
    "length": types.u8,
    "checksum": types.u8,
}

plan = compile_format(
    packet_fmt,
    field_ranges={("length",): FieldRange(min_value=1, max_value=32)},
    enum_policies={("kind",): EnumPolicy(known_weight=1, unknown_weight=3)},
    field_hints={("kind",): FieldHint((0xA5,), weight=2)},
)
```

The default enum policy gives known and unknown values equal weight.
`known_weight=0` selects only unknown values; `unknown_weight=0` preserves
declared-only sampling. The configured weights are bounded from 0 through 32,
and at least one category must remain enabled. If a range contains no unknown
values, that category contributes no examples within the range.

Ordinary `Bitfield` strategies also bias generation toward width-aware
patterns: zero, all ones, walking one/zero, and alternating bits. These are
combined with ordinary range sampling, deduplicated, and clipped by a
configured `FieldRange`.

Use `FieldDerivation` for a value determined by fields that precede it. The
callback receives a read-only mapping of the exact declared dependency paths;
callbacks should be pure and deterministic. Unknown, forward, and repeated
array-element paths are rejected during plan compilation. Callback failures
remain visible. `mutate_valid()` recomputes derived values after structured
changes and does not mutate a derived field independently; malformed mutations
can still break the relationship intentionally.

```python
from fmtfuzz import FieldDerivation, compile_format
from fmtspec import types


def copy_count(values):
    return values[("count",)]


length_fmt = {"count": types.u8, "count_copy": types.u8}
plan = compile_format(
    length_fmt,
    field_derivations={
        ("count_copy",): FieldDerivation(
            dependencies=(("count",),),
            derive=copy_count,
        ),
    },
)
```

`format_strategy()`, `binary_strategy()`, `fuzz_strategy()`,
`message_sequence_strategy()`, `Fuzzer`, and `mutate_valid()` accept or retain
compiled plans containing these policies. Unknown enum values are
wire-valid-only inputs; target-specific semantic validation remains the
responsibility of the parser or protocol implementation under test.

`capture_decision_seed(data, fmt)` decodes a canonical input and stores its
structured value. `replay_decision_seed(seed)` re-encodes it; the seed can also
produce a valid or malformed mutation with `seed.mutate(...)`. Decision seeds
are in-memory Python objects tied to their originating plan, not serialized
cross-process tokens. Capture raises `DecisionSeedError` if decoding and
re-encoding would not reproduce the input exactly.

`mutate_valid()` can change same-width scalar values, toggle optional fields,
insert or remove dynamic array elements while updating referenced dimensions,
and select another switch or tagged-union branch. A candidate is returned only
if the complete output remains decodable and within `max_size`.
`mutate_malformed()` targets referenced lengths/dimensions, selectors, and
terminator bytes when possible, alongside its existing field-boundary and
raw-byte operations.

## Format support and custom strategies

Nested mappings and sequences, integer and floating-point types, byte and text
fields, literals, bitfields, optional fields, arrays, sized fields, switches,
tagged unions, and terminator-wrapped fields are handled directly. Dynamic
references are generated in mapping order. Variable-size wrappers with
unsupported dependencies, recursive `Lazy` formats, and opaque custom types
require a registered Hypothesis strategy rather than an arbitrary byte fallback.

`fmtfuzz.describe_format(fmt)` exposes a cycle-aware metadata tree with each
node's format, size, semantic role, key, and child nodes. Custom composite
format implementations can implement the `FormatMetadata` protocol and return
`FormatChild(key=..., role=..., fmt=...)` objects from `__fmtfuzz_children__()`.

```python
from fmtfuzz import FormatChild, FormatMetadata, describe_format


class WrappedType(FormatMetadata):
    def __fmtfuzz_children__(self):
        return (FormatChild(key="payload", role="inner", fmt=payload_fmt),)


metadata = describe_format(packet_format)
```

```python
from hypothesis import strategies as st
from fmtfuzz import register_format_strategy


class CustomWireType: ...


register_format_strategy(
    CustomWireType,
    lambda fmt, contexts, max_size: st.binary(max_size=max_size),
)
```

The registered factory receives the format instance, enclosing mapping
contexts (outermost first), and maximum input size. Its generated value must be
accepted by the custom type's `encode` method.

## Corpus

`Corpus(path, max_size=...)` stores inputs as SHA-256-named files and
deduplicates them. Pass it to `Fuzzer` to include stored inputs in future
strategies and persist feedback-novel examples. Add seed files with
`corpus.add(Path(seed_path).read_bytes())`; `corpus.load()` returns entries in
deterministic order. `fuzz_strategy()` snapshots the corpus when the strategy
is constructed. `Fuzzer.run()` constructs a strategy at the start of each run,
so feedback-added entries can seed a later run but are not injected into a
strategy that is already running.

These stores have different roles:

- `FuzzConfig.database` configures Hypothesis's example database for
  `Fuzzer.run()`; pass an `ExampleDatabase` to enable persistent examples for
  that runner. Ordinary `@given` tests use their own Hypothesis settings.
- `Corpus` is an explicit content-addressed store of raw byte inputs shared
  when callers pass it to `fmtfuzz`.
- HypoFuzz maintains its own adaptive seed pool and coverage feedback when it
  runs discovered Hypothesis tests. It does not require `Corpus` or
  `Fuzzer.run()`.

The CLI imports a format and bytes callback using `module:attribute` paths:

```console
fmtfuzz --format my_protocol:packet_fmt --target my_protocol:parse_packet --max-examples 1000 --corpus .fmtfuzz-corpus
```

The imported module must be importable in the current environment. The target
is trusted Python code executed in-process.

## Generation benchmark

Run `uv run python scripts/bench_fmtfuzz.py` to compare format compilation and
repeated binary generation from a raw format versus a reused compiled plan.
The benchmark is informational and does not impose a performance threshold.
