# Core API Reference

This page documents the public API exported from `fmtspec`.

Use it to understand how values move through encoding, decoding, type conversion, inspection, and error reporting.

## The Main Entry Points

### `encode(obj, fmt=None) -> bytes`

Encode one Python value into a `bytes` object.

- Pass `fmt` when encoding dictionaries, lists, tuples, or custom format objects.
- Omit `fmt` when `obj` is a shape whose format can be derived from `typing.Annotated[..., fmt]` field metadata.

```python
from fmtspec import encode, types

packet_fmt = {
    "name": types.TakeUntil(types.str_utf8, b"\0"),
    "count": types.u32le,
}

data = encode({"name": "widget", "count": 3}, packet_fmt)
assert data == b"widget\0\x03\x00\x00\x00"
```

### `decode(data, fmt=None, *, type=None) -> Any`

Decode a byte buffer into Python values.

- `fmt` defines the wire layout.
- `type` converts decoded builtins into a typed result and can also drive format derivation when `fmt` is omitted.
- Raises `ExcessDecodeError` if any trailing bytes remain after a successful decode. Use `decode_stream` when partial consumption is intended.

```python
from dataclasses import dataclass
from typing import Annotated

from fmtspec import ExcessDecodeError, decode, types

@dataclass(frozen=True, slots=True)
class Record:
    name: Annotated[str, types.TakeUntil(types.str_utf8, b"\0")]
    count: Annotated[int, types.u32le]



record = decode(b"widget\0\x03\x00\x00\x00", type=Record)
assert record == Record(name="widget", count=3)

assert decode(b"\x00\x2a", types.u16) == 42

try:
    decode(b"\x00\x2a\xff", types.u16)
except ExcessDecodeError as exc:
    print(exc.remaining)  # 1 — typed byte count, no message parsing needed
```

### `encode_stream(stream, obj, fmt=None) -> None`

Encode directly into a file-like object.

Use this for files, sockets, or `BytesIO` when you do not want to allocate an intermediate `bytes` object.

### `decode_stream(stream, fmt=None, *, type=None) -> Any`

Decode directly from a file-like object.

This is the streaming counterpart to `decode(...)`. It does not raise on trailing bytes — the stream is left positioned after the decoded data, and `stream.read()` returns any remaining bytes.

## Format Derivation and Size Information

### `derive_fmt(cls) -> Format`

Build a format from annotated fields on a class.

Supported derivation inputs include:

- dataclasses
- `msgspec.Struct` classes
- standard classes whose annotations carry fmtspec metadata

Important boundary: format derivation is broader than type conversion. In practice, `decode(..., type=...)` is the ergonomic path for dataclasses and `msgspec.Struct` values.

```python
from dataclasses import dataclass
from typing import Annotated

from fmtspec import derive_fmt, types


@dataclass(frozen=True, slots=True)
class Header:
    version: Annotated[int, types.u8]
    length: Annotated[int, types.u16]


assert derive_fmt(Header) == {
    "version": types.u8,
    "length": types.u16,
}
```

Key rules:

- field metadata usually comes from `typing.Annotated[T, fmt]`
- nested annotated shapes are derived recursively
- unannotated fields in a composite shape raise `TypeError`
- classes may also define `__fmt__` to supply a format directly

### `sizeof(fmt) -> Size`

Return the static size of a format when fmtspec can determine it.

- returns an `int` for fixed-size formats
- returns `...` for dynamically sized formats
- returns `None` for greedy formats that consume the remaining stream

```python
from fmtspec import sizeof, types

assert sizeof(types.u32) == 4
assert sizeof(types.Sized(length=types.u8, fmt=types.Bytes())) is ...
assert sizeof(types.Bytes()) is None
```

## Inspection

Inspection is fmtspec's debugging-oriented view. It records offsets, byte counts, nested structure, and values for each encoding or decoding step.

### `encode_inspect(obj, fmt=None) -> tuple[bytes, InspectNode]`

Encode and return both the bytes and the root inspection node.

### `decode_inspect(data, fmt=None, *, type=None) -> tuple[Any, InspectNode]`

Decode and return both the result and the root inspection node.

- If `fmt` is omitted, `type` must be provided so fmtspec can derive the format before decoding.
- Raises `ExcessDecodeError` if any trailing bytes remain after a successful decode (the error carries an `inspect_node` with the successfully decoded tree).

### `format_tree(node, *, indent="  ", show_data=True, max_data_bytes=24, only_leaf=True, max_depth=-1) -> str`

Render an inspection tree as readable text.

For a simple structure:

```python
from fmtspec import encode_inspect, format_tree, types

fmt = {"x": types.u8, "y": types.u16}
data, tree = encode_inspect({"x": 1, "y": 0x0203}, fmt)

assert data == b"\x01\x02\x03"
print(format_tree(tree))
```

For complex nested protocols like TLS, inspection reveals the full structure at
each nesting level:

```python
from fmtspec import encode_inspect, format_tree, types

# TLS Client Hello format with version, random, and cipher suites
version_fmt = {"major": types.u8, "minor": types.u8}
cipher_suites_fmt = types.Sized(length=types.u16, fmt=types.array(types.u16))

tls_fmt = {
    "version": version_fmt,
    "random": types.Bytes(32),
    "cipher_suites": cipher_suites_fmt,
}

client_hello = {
    "version": {"major": 3, "minor": 3},
    "random": b"\x00" * 32,
    "cipher_suites": [0x1301, 0x1302],
}

data, tree = encode_inspect(client_hello, tls_fmt)
print(format_tree(tree))  # Shows nesting, offsets, values at each level
```

Use the formatting options when you need a narrower view:

- `show_data=False` hides raw hex bytes
- `max_data_bytes` truncates long byte dumps
- `only_leaf=False` also shows values for container nodes
- `max_depth` limits how deep the rendered tree goes

## Core Public Types

### `Context`

`Context` is the serialization state passed to every public `Type.encode(...)` and `Type.decode(...)` implementation.

Important pieces include:

- `parents`: sibling-access stack used by formats such as `Ref(...)`
- `path`: current logical path for error reporting
- `fmt`: the active format during a step
- `store`: scratch storage for cooperating formats
- `inspect`: whether inspection is enabled
- `inspect_node`: root inspection node when inspection is active
- `inspect_leaf(...)`: add a manual leaf node
- `inspect_scope(...)`: create an intermediate inspection node

See [stream-api.md](stream-api.md) for the standard custom-type pattern.

### `Type`

Protocol implemented by fmtspec-compatible format objects.

```python
def encode(self, stream, value, *, context: Context) -> None: ...
def decode(self, stream, *, context: Context) -> Any: ...
```

Formats conventionally expose a `size` attribute when they have a fixed width.

### `InspectNode`

Represents one node in the inspection tree.

Commonly useful attributes include:

- `key`: field name, array index, or `None` for the root
- `fmt`: format used at that node
- `value`: encoded or decoded Python value
- `offset`: starting stream offset
- `size`: byte length for the node
- `children`: nested inspection nodes
- `data`: raw bytes for the node

## Errors

### `Error`

Base exception for fmtspec failures.

### `EncodeError`

Raised when encoding fails.

### `ExcessDecodeError`

Raised when trailing bytes remain after a successful decode.

Distinct from `DecodeError` — use `except ExcessDecodeError` to handle only excess-data situations, or `except Error` to catch all fmtspec failures together.

The `stream` is positioned at the start of the excess data, so further decoding can be done via `decode_stream`:

```python
from fmtspec import ExcessDecodeError, decode_stream, types

try:
    result = decode(data, header_fmt)
except ExcessDecodeError as exc:
    # decode the remaining bytes as a payload
    payload = decode_stream(exc.stream, payload_fmt)
```

Extra attribute:

- `remaining: int` — count of unconsumed bytes, without materialising them.

### `DecodeError`

Raised when decoding fails.

### `TypeConversionError`

Raised when fmtspec decoded the bytes successfully but could not convert the result into the requested `type`.

Attributes:

- `obj`: the raw decoded data (Python builtins) that failed conversion
- `type`: the target type that was requested
- `fmt`: the format used to decode the bytes
- `cause`: the underlying exception raised during type conversion
- `inspect_node`: inspection tree from the decode step, when inspection was enabled

Typical usage:

- `EncodeError` for missing fields, invalid literal values, or size mismatches during writing
- `DecodeError` for truncated input, wrong markers, or unknown tags
- `ExcessDecodeError` for trailing bytes after a successful decode
- `TypeConversionError` for post-decode type conversion problems
