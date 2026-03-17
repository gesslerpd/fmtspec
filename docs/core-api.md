# Core API Reference

This page covers the public API exported from `fmtspec.__init__`.

Use it when you want to understand how values move through encode, decode, shape conversion, inspection, and error reporting.

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

Decode a byte buffer into Python data.

- `fmt` controls the wire layout.
- `shape` converts the decoded builtins into a typed result and can also drive format derivation when `fmt` is omitted.
- `strict=True` raises `DecodeError` if any trailing bytes remain after a successful decode.

```python
from dataclasses import dataclass
from typing import Annotated

from fmtspec import DecodeError, decode, types

STR_FMT = types.TakeUntil(types.str_utf8, b"\0")
INT_FMT = types.u32le


@dataclass(frozen=True, slots=True)
class Record:
    name: Annotated[str, STR_FMT]
    count: Annotated[int, INT_FMT]


record = decode(b"widget\0\x03\x00\x00\x00", shape=Record)
assert record == Record(name="widget", count=3)

try:
    decode(b"\x00\x2a\xff", types.u16, strict=True)
except DecodeError:
    pass
```

### `encode_stream(obj, stream, fmt=None) -> None`

Encode directly into a file-like object.

Use this for files, sockets, or `BytesIO` when you do not want an intermediate `bytes` allocation.

### `decode_stream(stream, fmt=None, *, shape=None) -> Any`

Decode directly from a file-like object.

This is the streaming counterpart to `decode(...)`. Unlike `decode(...)`, it does not have a `strict` flag. If you need full-consumption checks for a buffer, use `decode(..., strict=True)`.

## Format Derivation and Size Information

### `derive_fmt(cls) -> Format`

Build a format from annotated fields on a class.

Supported derivation inputs include:

- dataclasses
- `msgspec.Struct` classes
- standard classes whose annotations carry fmtspec metadata

Important boundary: format derivation is broader than shape conversion. In practice, `decode(..., shape=...)` is primarily the ergonomic path for dataclasses and `msgspec.Struct` values.

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

Rules worth knowing:

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

Inspection is the debugging-oriented view of fmtspec. It records offsets, byte counts, nested structure, and values for each encode or decode step.

### `encode_inspect(obj, fmt) -> tuple[bytes, InspectNode]`

Encode and return both the bytes and the root inspection node.

### `decode_inspect(data, fmt, *, shape=None) -> tuple[Any, InspectNode]`

Decode and return both the result and the root inspection node.

### `format_tree(node, *, indent="  ", show_data=True, max_data_bytes=24, only_leaf=True, max_depth=-1) -> str`

Render an inspection tree into readable text.

```python
from fmtspec import encode_inspect, format_tree, types

fmt = {"x": types.u8, "y": types.u16}
data, tree = encode_inspect({"x": 1, "y": 0x0203}, fmt)

assert data == b"\x01\x02\x03"
print(format_tree(tree))
```

Use the formatting options when you need a narrower view:

- `show_data=False` hides raw hex bytes
- `max_data_bytes` truncates long byte dumps
- `only_leaf=False` shows values for container nodes too
- `max_depth` limits how deep the rendered tree goes

## Core Public Types

### `Context`

`Context` is the serialization state passed to every public `Type.encode(...)` and `Type.decode(...)` implementation.

Important pieces:

- `parents`: sibling-access stack used by formats such as `Ref(...)`
- `path`: current logical path for error reporting
- `fmt`: the active format during a step
- `store`: scratch storage for cooperating formats
- `inspect`: whether inspection is enabled
- `inspect_node`: root inspection node when inspection is active
- `inspect_leaf(...)`: add a manual leaf node
- `inspect_scope(...)`: create an intermediate inspection node

The practical custom-type pattern is covered in [stream-api.md](stream-api.md).

### `Type`

Protocol implemented by fmtspec-compatible format objects.

```python
def encode(self, value, stream, *, context: Context) -> None: ...
def decode(self, stream, *, context: Context) -> Any: ...
```

Formats conventionally expose a `size` attribute when they have a fixed width.

### `InspectNode`

Represents one node in the inspection tree.

Commonly useful attributes are:

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

The exception objects preserve useful debugging state such as:

- the active format
- the current object or partial result
- the nested path
- the original cause
- an inspection node when inspection was enabled

Typical usage split:

- `EncodeError` for missing fields, invalid literal values, or size mismatches during writing
- `DecodeError` for truncated input, wrong markers, unknown tags, or trailing bytes with `strict=True`
- `ShapeError` for post-decode conversion problems