# Stream and Custom Type API

This page documents the public low-level helpers in `fmtspec.stream` and the `Context` methods that custom `Type` implementations rely on.

For normal application code, prefer the top-level `fmtspec.encode_stream(...)` and `fmtspec.decode_stream(...)`. The functions documented here are the nested delegation layer used inside a custom type.

## `fmtspec.stream`

### `encode_stream(stream, obj, fmt, *, context, key=None) -> None`

Delegate nested encoding back into fmtspec while preserving the current `Context`.

Use this inside `Type.encode(...)` when your custom type handles part of the wire format manually and wants fmtspec to handle the nested remainder.

### `decode_stream(stream, fmt, *, context, key=None) -> Any`

Delegate nested decoding back into fmtspec while preserving the current `Context`.

Use this inside `Type.decode(...)` when you need correct path tracking, sibling access, and inspection support for the nested part of the format.

### `read_exactly(stream, size) -> bytes`

Read exactly `size` bytes or raise `EOFError`.

### `write_all(stream, data) -> None`

Write the full payload, retrying partial writes if needed.

### `peek(stream, size) -> bytes`

Read exactly `size` bytes and then restore the stream position.

This requires a seekable stream because the implementation rewinds with `seek(...)`.

```python
from io import BytesIO

from fmtspec.stream import peek

stream = BytesIO(b"abcdef")
stream.seek(2)

assert peek(stream, 3) == b"cde"
assert stream.tell() == 2
```

## `Context`

Every public fmtspec `Type` receives a `Context` object.

Its main responsibilities are:

- keeping the parent stack used by `Ref(...)` and sibling-aware formats
- tracking the logical path for error reporting
- carrying temporary shared state through `store`
- building inspection trees when inspection is enabled

### Parent and Path Helpers

- `push(parent)` and `pop()` manage the parent stack
- `push_path(key)` and `pop_path()` manage the logical field path

### Inspection Helpers

#### `context.inspect_leaf(stream, key, fmt, value, start, *, prepend=False) -> None`

Record a manual leaf node in the inspection tree.

Use this when your custom type bypasses fmtspec's traversal engine for a leaf operation, such as manually encoding a header byte or directly calling another formatter's `encode(...)` or `decode(...)` method.

`prepend=True` is useful when you emit a length or tag field before the payload but create the surrounding scope later.

#### `context.inspect_scope(stream, key, fmt, value)`

Create an intermediate inspection node whose children will be filled by nested work inside the context manager.

Use this for logical containers such as frames, TLV bodies, recursive nodes, or other grouped structures that should appear as a node in the tree.

The yielded node can be updated later, which is useful during decode when the final value is not known up front.

## Custom `Type` Template

```python
from typing import Any, BinaryIO

from fmtspec import Context
from fmtspec.stream import decode_stream, encode_stream


class MyType:
    size = ...

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        header_start = stream.tell()
        self.header_fmt.encode(len(value), stream, context=context)
        context.inspect_leaf(stream, "length", self.header_fmt, len(value), header_start)

        with context.inspect_scope(stream, "payload", self.payload_fmt, value) as node:
            encode_stream(stream, value, self.payload_fmt, context=context, key="payload")
            if node:
                node.value = value

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        size_start = stream.tell()
        size = self.header_fmt.decode(stream, context=context)
        context.inspect_leaf(stream, "length", self.header_fmt, size, size_start)

        with context.inspect_scope(stream, "payload", self.payload_fmt, None) as node:
            value = decode_stream(stream, self.payload_fmt, context=context, key="payload")
            if node:
                node.value = value
            return value
```

## Common Patterns

- Frame-based protocols often write a small header manually, then delegate the payload to `encode_stream(...)` and `decode_stream(...)`.
- TLV-style formats often combine `read_exactly(...)`, `write_all(...)`, and `inspect_leaf(...)` for tags and lengths.
- Recursive or tree-like encodings often use `inspect_scope(...)` so the inspection output reflects logical structure instead of only raw byte operations.

## Real-World Example: Streaming TLS Client Hello

The [README](../README.md) contains the full in-memory TLS Client Hello walkthrough. This section shows the same shape being sent through `encode_stream` and `decode_stream` instead of a byte buffer.

```python
from io import BytesIO

from fmtspec import decode_stream, encode_stream, types

# Reuse the TLS Client Hello format and sample object from the README example.
stream = BytesIO()
encode_stream(stream, client_hello, tls_client_hello_fmt)

stream.seek(0)
result = decode_stream(stream, tls_client_hello_fmt)
assert result == client_hello
```