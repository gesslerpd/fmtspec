
# fmtspec

`fmtspec` is a flexible binary format serialization library for Python.

## Custom Inspection Helpers

When writing custom format types that manually read or write child values, use the public `Context`
inspection helpers instead of importing private helpers from internal modules.

```python
from fmtspec import Context


def encode(self, value, stream, *, context: Context) -> None:
	start = stream.tell()
	self.prefix.encode(len(value), stream, context=context)
	context.inspect_leaf(stream, "--len--", self.prefix, len(value), start)

	with context.inspect_scope(stream, "payload", self, value) as node:
		self.payload.encode(value, stream, context=context)
		if node:
			node.value = value
```

Use `context.inspect_leaf(...)` when your type performs a manual leaf encode/decode step that would
otherwise bypass the normal inspection tree. Use `context.inspect_scope(...)` when your type creates
an intermediate grouping node for nested traversal.

## Low-Level Stream Helpers

Use `fmtspec.stream` for public low-level stream/runtime helpers inside custom formats.

```python
from fmtspec import Context
from fmtspec.stream import decode_value, encode_value, peek, read_exactly, write_all
```

`encode_value(...)` and `decode_value(...)` delegate nested work back into fmtspec's traversal engine
using an existing `Context`. `peek(...)`, `read_exactly(...)`, and `write_all(...)` provide the public
stream primitives previously only available from internal modules.
