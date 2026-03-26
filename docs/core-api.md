# Core API Reference

This page documents the public API exported from `fmtspec`.

Use it to understand how values move through encoding, decoding, shape conversion, inspection, and error reporting.

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

### `decode(data, fmt=None, *, shape=None, strict=False) -> Any`

Decode a byte buffer into Python values.

- `fmt` defines the wire layout.
- `shape` converts decoded builtins into a typed result and can also drive format derivation when `fmt` is omitted.
- `strict=True` raises `DecodeError` if any trailing bytes remain after a successful decode. This is useful in protocol parsing where extra bytes indicate a malformed or truncated message rather than valid trailing data to be ignored.

```python
from dataclasses import dataclass
from typing import Annotated

from fmtspec import DecodeError, decode, types

@dataclass(frozen=True, slots=True)
class Record:
    name: Annotated[str, types.TakeUntil(types.str_utf8, b"\0")]
    count: Annotated[int, types.u32le]



record = decode(b"widget\0\x03\x00\x00\x00", shape=Record)
assert record == Record(name="widget", count=3)

# With strict=True, extra bytes raise DecodeError
assert decode(b"\x00\x2a", types.u16, strict=True) == 42

try:
    decode(b"\x00\x2a\xff", types.u16, strict=True)
except DecodeError:
    pass

# With strict=False (default), extra bytes are silently ignored
assert decode(b"\x00\x2a\xff", types.u16) == 42
```

### `encode_stream(stream, obj, fmt=None) -> None`

Encode directly into a file-like object.

Use this for files, sockets, or `BytesIO` when you do not want to allocate an intermediate `bytes` object.

### `decode_stream(stream, fmt=None, *, shape=None) -> Any`

Decode directly from a file-like object.

This is the streaming counterpart to `decode(...)`. Unlike `decode(...)`, it does not have a `strict` flag. If you need to verify that a buffer was fully consumed, use `decode(..., strict=True)` instead.

## Format Derivation and Size Information

### `derive_fmt(cls) -> Format`

Build a format from annotated fields on a class.

Supported derivation inputs include:

- dataclasses
- `msgspec.Struct` classes
- standard classes whose annotations carry fmtspec metadata

Important boundary: format derivation is broader than shape conversion. In practice, `decode(..., shape=...)` is the ergonomic path for dataclasses and `msgspec.Struct` values.

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

### `encode_inspect(obj, fmt) -> tuple[bytes, InspectNode]`

Encode and return both the bytes and the root inspection node.

### `decode_inspect(data, fmt, *, shape=None) -> tuple[Any, InspectNode]`

Decode and return both the result and the root inspection node.

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

### `DecodeError`

Raised when decoding fails.

### `ShapeError`

Raised when fmtspec decoded the bytes successfully but could not convert the result into the requested `shape`.

Exception objects preserve useful debugging state such as:

- the active format
- the current object or partial result
- the nested path
- the original cause
- an inspection node when inspection was enabled

Typical usage:

- `EncodeError` for missing fields, invalid literal values, or size mismatches during writing
- `DecodeError` for truncated input, wrong markers, unknown tags, or trailing bytes with `strict=True`
- `ShapeError` for post-decode conversion problems