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
strategy can be used in an ordinary Hypothesis test:

```python
from hypothesis import given
from fmtfuzz import fuzz_strategy


@given(fuzz_strategy(packet_fmt, max_size=1024))
def test_packet_parser(data: bytes) -> None:
    parse_packet(data)
```

Install HypoFuzz separately if coverage-guided scheduling is wanted, then run
the test through its Hypothesis CLI:

```console
hypothesis fuzz tests/test_packet_parser.py
```

`fmtfuzz` does not implement its own code-coverage scheduler; `Fuzzer` accepts a
feedback callback that returns a hashable novelty key. The first input for each
new key is saved to the optional corpus.

## Compiled plans, hints, and decision seeds

`compile_format(fmt)` creates an explicit reusable `FormatPlan` containing the
format tree, field paths, sizes, available enum/branch choices, and discovered
`Ref` dependencies. Pass the plan to strategy or mutation APIs to reuse it; raw
formats remain accepted as convenience inputs. A plan describes the format as
it existed at compilation, so do not mutate the source format afterward.

`FieldHint` supplies known values for a scalar field, such as protocol magic
values or uncommon branch selectors. Values are sampled alongside ordinary
strategy values, with `weight` controlling their relative frequency:

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
deterministic order.

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
