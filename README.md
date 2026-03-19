# fmtspec

`fmtspec` is a Python library for binary encoding and decoding built around
composable format objects.

The only dependency is the excellent
<a href="https://jcristharif.com/msgspec/" target="_blank" rel="noopener">msgspec</a>
package.

## Installation

```bash
$ pip install fmtspec
```

or add as a dependency in `pyproject.toml`

```bash
$ uv add fmtspec
```

## Core Features

- `encode(...)` and `decode(...)` for in-memory byte buffers
- `encode_stream(...)` and `decode_stream(...)` for files, sockets, and
  `BytesIO`
- `fmtspec.types` for reusable primitives such as integers, enums, arrays, sized
  fields, bitfields, and tagged layouts
- `encode_inspect(...)`, `decode_inspect(...)`, and `format_tree(...)` for
  inspecting parse trees during encoding and decoding
- Informative exceptions with failure paths and format context
- `Context` and `fmtspec.stream` for implementing custom `Type` classes on the
  public API

## Typical Workflow

1. Describe the wire format with `fmtspec.types` and plain Python containers.
2. Encode Python values with `encode(...)` or `encode_stream(...)`.
3. Decode the bytes back into builtins, dataclasses, or `msgspec.Struct` shapes.

### Start With a Mapping Format

```python
from fmtspec import decode, encode, types

packet_fmt = {
    "name": types.TakeUntil(types.str_utf8, b"\0"),
    "count": types.u32le,
}

packet = {
    "name": "widget",
    "count": 3,
}

data = encode(packet, packet_fmt)
assert data == b"widget\0\x03\x00\x00\x00"

decoded = decode(data, packet_fmt)
assert decoded == packet
```

This is the core fmtspec style: combine primitive format objects into mappings,
tuples, or arrays, then round-trip ordinary Python values.

### Derive the Format From a Typed Shape

If fields are annotated with `typing.Annotated[..., fmt]`, fmtspec can derive
the mapping format for you.

```python
from dataclasses import dataclass
from typing import Annotated

from fmtspec import decode, encode, types

STR_FMT = types.TakeUntil(types.str_utf8, b"\0")
INT_FMT = types.u32le


@dataclass(frozen=True, slots=True)
class Record:
    name: Annotated[str, STR_FMT]
    count: Annotated[int, INT_FMT]


record = Record(name="widget", count=3)
data = encode(record)
roundtripped = decode(data, shape=Record)
assert roundtripped == record
```

This is the most ergonomic path when your wire layout already matches a
dataclass or `msgspec.Struct`.

### Reject Trailing Bytes When You Need Full Consumption

```python
from fmtspec import DecodeError, decode, types

assert decode(b"\x00\x2a", types.u16, strict=True) == 42

try:
    decode(b"\x00\x2a\xff", types.u16, strict=True)
except DecodeError:
    pass
```

Use `strict=True` on `decode(...)` when extra bytes should be treated as a
protocol error instead of being silently ignored.

### Inspect Layouts While Debugging

```python
from fmtspec import encode_inspect, format_tree, types

fmt = {
    "x": types.u8,
    "y": types.u16,
}

data, tree = encode_inspect({"x": 1, "y": 0x0203}, fmt)
print(data)
print(format_tree(tree))
```

Inspection shows offsets, sizes, values, and child structure for each encoding
or decoding step. It is intended for debugging, tooling, and protocol
exploration rather than performance.

For the example above, `format_tree(tree)` renders output like this:

```text
* Mapping @ [0:3] (3 bytes) (2 items)
├─ [x] Int @ [0:1] (1 bytes)
│    value: 1
│    data: 01
└─ [y] Int @ [1:3] (2 bytes)
     value: 515
     data: 02 03
```

## Error Model

The public API raises structured exceptions instead of only raw `ValueError`
instances.

- `EncodeError`: a Python value could not be serialized with the chosen format
- `DecodeError`: the incoming bytes did not match the format
- `ShapeError`: decoding succeeded, but the result could not be converted into
  the requested `shape`

These exceptions preserve context such as the active format, object, path,
cause, and optional inspection node.

```python
from fmtspec import DecodeError, decode, types

fmt = {
    "kind": types.u8,
    "payload": types.Sized(length=types.u8, fmt=types.Bytes()),
}

try:
    decode(b"\x01\x05abc", fmt, strict=True)
except DecodeError as exc:
    print(exc)
    print(exc.path)
    print(exc.fmt)
```

This context is especially useful with nested mappings, arrays, `Switch(...)`,
and custom types, where the failing field path matters as much as the raw
message. See [docs/core-api.md](docs/core-api.md) for more detail on errors and
inspection.

## Documentation

These reference pages cover the details by topic:

- [docs/core-api.md](docs/core-api.md) for top-level encode/decode, format
  derivation, inspection, and errors
- [docs/types-api.md](docs/types-api.md) for `fmtspec.types`
- [docs/stream-api.md](docs/stream-api.md) for custom `Type` implementations,
  `Context`, and `fmtspec.stream`
