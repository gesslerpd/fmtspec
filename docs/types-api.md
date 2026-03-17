# Types API Reference

This page documents the public constructors and aliases exported from `fmtspec.types`.

The goal is to help you choose the right building block, not just list names. Start with the primitive section, then add boundaries, repetition, and dynamic dispatch as needed.

## Primitive Values

### `Int(byteorder, signed, size, enum=None)`

General fixed-width integer type.

- `byteorder` is `"big"` or `"little"`
- `signed` controls signed vs unsigned interpretation
- `size` is `1`, `2`, `4`, `8`, or `16` bytes
- `enum` may be an `IntEnum` or `IntFlag` subclass for automatic enum conversion on decode

Aliases:

- big-endian shorthand: `u8`, `u16`, `u32`, `u64`, `u128`, `i8`, `i16`, `i32`, `i64`, `i128`
- explicit big-endian: `u8be`, `u16be`, `u32be`, `u64be`, `u128be`, `i8be`, `i16be`, `i32be`, `i64be`, `i128be`
- little-endian: `u8le`, `u16le`, `u32le`, `u64le`, `u128le`, `i8le`, `i16le`, `i32le`, `i64le`, `i128le`

```python
from fmtspec import decode, encode, types

assert encode(0x1234, types.u16) == b"\x12\x34"
assert decode(b"\x34\x12", types.u16le) == 0x1234
```

### `Float(byteorder, size)`

Fixed-width IEEE floating-point type.

- `size=4` gives single precision
- `size=8` gives double precision

Aliases: `f32`, `f64`, `f32be`, `f64be`, `f32le`, `f64le`

### `Bytes(size=None)`

Binary blob format.

- with `size`, reads or writes exactly that many bytes
- without `size`, greedily consumes the remaining stream

Alias: `bytes_`

### `Str(size=None, encoding="utf-8")`

Text format backed by encoded bytes.

- with `size`, reads or writes exactly that many encoded bytes
- without `size`, greedily consumes the remaining stream

Aliases: `str_`, `str_utf8`, `str_ascii`

In practice, greedy `Bytes()` and `Str()` are usually wrapped by `Sized(...)`, `TakeUntil(...)`, or an enclosing structure that already provides a boundary.

### `Literal(value, *, strict=True)`

Fixed byte sequence.

- encoding always writes `value`
- when `strict=True`, encoding rejects a non-`None` input that does not match the literal
- decoding verifies the incoming bytes and returns the literal value

### `Null()`

Zero-width format that accepts and returns `None`.

Alias: `null`

## Boundaries and Repetition

### `Sized(length, fmt, align=None, fill=b"\x00", factor=1)`

Wrap another format whose byte length is determined at runtime.

`length` can be:

- an `int` for a fixed-width field
- a `Ref(...)` that points at a sibling length value
- another type object that encodes and decodes the length header itself

Other parameters:

- `align` pads the payload out to a byte boundary after the content
- `fill` controls the padding bytes
- `factor` converts between stored length units and raw byte count

This is the standard tool for length-prefixed payloads, fixed-width payload slots, and padded protocol bodies.

### `TakeUntil(fmt, terminator, max_size=None)`

Repeatedly encode or decode `fmt` values until a terminator byte sequence is reached.

Common uses are null-terminated strings and delimiter-separated byte fields.

```python
from fmtspec import decode, encode, types

line_fmt = types.TakeUntil(types.str_utf8, b"\n")
assert decode(encode("hello", line_fmt), line_fmt) == "hello"
```

### `Array(element_fmt, dims)`

Array format for one or more dimensions.

`dims` may contain:

- fixed integers
- `Ref(...)` objects that resolve lengths from sibling values
- type objects that encode or decode a length prefix

An empty dimension tuple means a greedy array that repeats until end-of-stream.

Decoded arrays are nested Python lists.

### `array(fmt, dims=())`

Convenience wrapper around `Array(...)`.

Examples:

- `types.array(types.u8, 3)` for three bytes
- `types.array(types.u8, types.u16)` for a count-prefixed array
- `types.array(types.u16, (2, 3))` for a fixed 2x3 matrix
- `types.array(types.u8)` for a greedy array

## Dynamic and Referential Types

### `Ref(key, parent=1, cast=None)`

Resolve a sibling value from the active `Context`.

- `key` is the sibling field name
- `parent=1` means the current parent mapping
- `cast` optionally transforms the resolved value before use

`Ref(...)` is the glue used by array lengths, `Sized(...)`, and dispatch formats.

### `Switch(key, cases, default=None)`

Choose a branch format from a sibling value.

This is useful when one earlier field determines the layout of the current field.

```python
from fmtspec import decode, encode, types

fmt = {
	"kind": types.u8,
	"body": types.Switch(types.Ref("kind"), {1: types.u16}, default=types.bytes_),
}

assert decode(encode({"kind": 1, "body": 5}, fmt), fmt)["body"] == 5
```

Practical note: `Switch(...)` works best when the selected branch is already bounded by the surrounding format, or when it is naturally the trailing part of a structure.

### `TaggedUnion(tag, fmt_map=...)`

Tagged union helper for tagged `msgspec.Struct` branches.

Important constraints:

- branches in `fmt_map` must be tagged `msgspec.Struct` classes
- `tag` may be a type that reads and writes the tag, or a `Ref(...)` to a sibling tag field
- decode returns the selected struct instance, not a raw dictionary
- when `tag` is a `Ref(...)`, fmtspec can auto-populate the sibling tag field during encoding when the branch provides it

Use `TaggedUnion(...)` when you want strongly typed tagged payloads instead of raw `Switch(...)` branches.

### `Optional(fmt)`

Optional trailing-value wrapper.

- encoding omits the wrapped value when the Python value is `None`
- decoding returns `None` only when the wrapped format would hit end-of-stream

This is intentionally narrow. It is mainly for trailing fields that may or may not be present at the end of a record.

### `Lazy(get_format)`

Defer format construction until encode or decode time.

Use this for recursive formats or situations where the format graph cannot be constructed eagerly.

```python
from fmtspec import types

node_fmt = None
node_ref = types.Lazy(lambda: node_fmt)

node_fmt = {
	"value": types.u8,
	"children": types.Sized(length=types.u8, fmt=types.array(node_ref)),
}
```

## Bit Packing

### `Bitfield(bits, offset=0, align=None, enum=None)`

Describe one packed bit range inside a larger integer value.

- `bits` must be positive
- `offset` counts from the least-significant bit
- `align` can force the bitfield or auto-placement group into a `1`, `2`, `4`, or `8` byte bucket
- `enum` may be an `IntEnum` or `IntFlag` subclass

When `bits == 1`, decoding returns `bool` unless `enum` is supplied.

### `Bitfields(fields, size=None)`

Pack multiple named `Bitfield(...)` definitions into one integer-backed value.

- `size` may be omitted to infer the smallest supported container width
- the result encodes and decodes dictionaries keyed by the field names

```python
from fmtspec import decode, encode, types

flags = types.Bitfields(
	size=1,
	fields={
		"opcode": types.Bitfield(bits=4),
		"fin": types.Bitfield(bits=1, offset=7),
	},
)

decoded = decode(encode({"opcode": 2, "fin": True}, flags), flags)
assert decoded == {"opcode": 2, "fin": True}
```

## Choosing the Right Tool

- Use `Int`, `Float`, `Bytes`, and `Str` for primitive values.
- Use `Sized`, `TakeUntil`, and `Literal` to express boundaries.
- Use `Array` when the wire format repeats a value or tuple shape.
- Use `Ref`, `Switch`, and `TaggedUnion` when one field controls another.
- Use `Optional` only for trailing EOF-based optional values.
- Use `Bitfield` and `Bitfields` when multiple values share one integer.
- Use `Lazy` when the format graph is recursive.