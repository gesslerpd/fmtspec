# Library API Reference

`fmtspec.lib` contains a library of ready-made `fmtspec` implementations of
common binary formats. Each format object is a standard fmtspec `Type` and you
can pass it anywhere `fmtspec.types` primitives are accepted, embed it inside
dicts, arrays, `Sized(...)`, `Switch(...)`, or any other composite format.

> **Tip:** This module and the test files under
> [`tests/examples/`](../tests/examples/) are good places to look for real-world
> examples of writing custom `fmtspec` types. These examples also serve as a
> reference for AI coding agents.

---

## `fmtspec.lib.asn1`

Provides a fmtspec `Type` that encodes and decodes the ASN.1 Basic Encoding
Rules (BER) / Distinguished Encoding Rules (DER) Tag-Length-Value structure.

### Imports

```python
from fmtspec.lib.asn1 import (
    ASN1Class,    # Enum for tag class (UNIVERSAL, APPLICATION, CONTEXT, PRIVATE)
    UniversalTag, # IntEnum for universal tag numbers
    asn1,         # pre-built singleton — use this in practice
)
```

### Usage

```python
from fmtspec import decode, encode, types
from fmtspec.lib.asn1 import ASN1Class, UniversalTag, asn1

# Primitives
data = encode({"tag": UniversalTag.INTEGER, "value": 2026}, asn1)
assert decode(data, asn1)["value"] == 2026

# Constructed (SEQUENCE / SET)
seq = {
    "tag": UniversalTag.SEQUENCE,
    "value": [
        {"tag": UniversalTag.INTEGER, "value": 42},
        {"tag": UniversalTag.UTF8_STRING, "value": "hello"},
    ],
}
assert decode(encode(seq, asn1), asn1)["value"][0]["value"] == 42

# Context-specific tags
node = {"tag_class": ASN1Class.CONTEXT, "tag": 0, "constructed": True,
        "value": [{"tag": UniversalTag.INTEGER, "value": 5}]}
result = decode(encode(node, asn1), asn1)
assert result["tag_class"] == ASN1Class.CONTEXT
assert result["value"][0]["value"] == 5

# Composed with other fmtspec.types primitives
fmt = {"version": types.u8, "body": asn1}
data = encode({"version": 1, "body": {"tag": UniversalTag.INTEGER, "value": 42}}, fmt)
assert decode(data, fmt)["body"]["value"] == 42
```

---

## `fmtspec.lib.msgpack`

Provides a fmtspec `Type` that encodes and decodes the
[MessagePack](https://msgpack.org/) binary serialization format.

### Imports

```python
from fmtspec.lib.msgpack import (
    MsgPack,      # the Type class, for customisation
    msgpack,      # pre-built singleton (float64, list, dict)
    msgpack_f32,  # pre-built singleton with float32
)
```

### Usage

```python
from fmtspec import decode, encode, types
from fmtspec.lib.msgpack import msgpack

# Round-trip any value
payload = {"x": 1, "items": [1, 2, 3]}
assert decode(encode(payload, msgpack), msgpack) == payload

# Composed with other fmtspec.types primitives
fmt = {"version": types.u8, "payload": types.Sized(length=types.u32, fmt=msgpack)}
data = encode({"version": 1, "payload": payload}, fmt)
assert decode(data, fmt) == {"version": 1, "payload": payload}
```

---

## Inspection

Both `asn1` and `msgpack` are fully inspection-aware and work with
`encode_inspect` and `decode_inspect`.

```python
from fmtspec import encode_inspect, format_tree
from fmtspec.lib.msgpack import msgpack

payload = {"x": 1, "items": [1, 2, 3]}
data, tree = encode_inspect(payload, msgpack)
print(format_tree(tree))
# * MsgPack @ [0:14] (14 bytes) (2 items)
# ├─ [0] MsgPack @ [1:4] (3 bytes) (2 items)
# │  ├─ [None] MsgPack @ [1:3] (2 bytes)
# │  │    value: 'x'
# │  │    data: a1 78
# │  └─ [x] MsgPack @ [3:4] (1 bytes)
# │       value: 1
# │       data: 01
# └─ [1] MsgPack @ [4:14] (10 bytes) (2 items)
#    ├─ [None] MsgPack @ [4:10] (6 bytes)
#    │    value: 'items'
#    │    data: a5 69 74 65 6d 73
#    └─ [items] MsgPack @ [10:14] (4 bytes) (3 items)
#       ├─ [0] MsgPack @ [11:12] (1 bytes)
#       │    value: 1
#       │    data: 01
#       ├─ [1] MsgPack @ [12:13] (1 bytes)
#       │    value: 2
#       │    data: 02
#       └─ [2] MsgPack @ [13:14] (1 bytes)
#            value: 3
#            data: 03
```
