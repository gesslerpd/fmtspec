# fmtspec

[![PyPI Version](https://img.shields.io/pypi/v/fmtspec.svg)](https://pypi.org/project/fmtspec/)
[![Latest Release](https://img.shields.io/github/release-date/gesslerpd/fmtspec)](https://github.com/gesslerpd/fmtspec/releases)

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

### Specify format with composable types

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

# or without keys using iterable of formats

no_map_packet_fmt = (
    types.TakeUntil(types.str_utf8, b"\0"),
    types.u32le,
)

packet_tuple = ("widget", 3)

data = encode(packet_tuple, no_map_packet_fmt)
assert data == b"widget\0\x03\x00\x00\x00"

decoded = decode(data, no_map_packet_fmt)
assert tuple(decoded) == packet_tuple
```

This is the core fmtspec style: combine primitive format objects into mappings,
tuples, or custom types, then round-trip ordinary Python values.

For streaming, the `encode_stream` and `decode_stream` functions are used:

```python
from io import BytesIO

stream = BytesIO()
encode_stream(stream, packet, packet_fmt)

# rollback to the start for decoding our encoded data
stream.seek(0)
assert decode_stream(stream, packet_fmt) == packet
```

### Derive the format from a typed class

If class fields are annotated with `typing.Annotated[..., fmt]`, fmtspec can
recursively derive the mapping format for you.

```python
from dataclasses import dataclass
from typing import Annotated

from fmtspec import decode, encode, types


@dataclass(frozen=True, slots=True)
class Record:
    name: Annotated[str, types.TakeUntil(types.str_utf8, b"\0")]
    count: Annotated[int, types.u32le]


record = Record(name="widget", count=3)
data = encode(record)
roundtripped = decode(data, type=Record)
assert roundtripped == record
```

This is the most ergonomic path when your wire layout already matches a
dataclass or `msgspec.Struct`.

### Inspect Layouts While Debugging

Inspection shows offsets, sizes, values, and child structure for each encoding
or decoding step. It is intended for debugging, tooling, and protocol
exploration rather than performance.

For simple structures:

```python
from fmtspec import encode_inspect, format_tree, types

fmt = {
    "x": types.u8,
    "y": types.u16,
}

data, tree = encode_inspect({"x": 1, "y": 0x0203}, fmt)
print(format_tree(tree))
```

Output:
```text
* Mapping @ [0:3] (3 bytes) (2 items)
├─ [x] Int @ [0:1] (1 bytes)
│    value: 1
│    data: 01
└─ [y] Int @ [1:3] (2 bytes)
     value: 515
     data: 02 03
```

For complex protocols like TLS Client Hello with nested structures and dynamic
fields:

```python
from fmtspec import encode_inspect, format_tree, types

version_fmt = {"major": types.u8, "minor": types.u8}
random_fmt = {"gmt_unix_time": types.u32, "random": types.Bytes(28)}
session_id_fmt = types.Sized(length=types.u8, fmt=types.Bytes())
cipher_suites_fmt = types.Sized(length=types.u16, fmt=types.array(types.u16))
compression_methods_fmt = types.Sized(length=types.u8, fmt=types.Bytes())

server_name_fmt = {
    "name_type": types.u8,
    "host_name": types.Sized(length=types.u16, fmt=types.Bytes()),
}
sni_fmt = types.Sized(length=types.u16, fmt=types.array(server_name_fmt))
protocol_fmt = types.Sized(length=types.u8, fmt=types.Bytes())
alpn_fmt = types.Sized(length=types.u16, fmt=types.array(protocol_fmt))

extension_fmt = {
    "type": types.u16,
    "body": types.Sized(
        length=types.u16,
        fmt=types.Switch(
            key=types.Ref("type"),
            cases={
                0x0000: sni_fmt,
                0x0010: alpn_fmt,
            },
            default=types.bytes_,
        ),
    ),
}
extensions_fmt = types.Sized(length=types.u16, fmt=types.array(extension_fmt))

tls_client_hello_fmt = {
    "version": version_fmt,
    "random": random_fmt,
    "session_id": session_id_fmt,
    "cipher_suites": cipher_suites_fmt,
    "compression_methods": compression_methods_fmt,
    "extensions": extensions_fmt,
}

client_hello = {
    "version": {"major": 3, "minor": 3},
    "random": {
        "gmt_unix_time": 0,
        "random": b"abcdefghijklmnopqrstuvwxyz_-",
    },
    "session_id": b"",
    "cipher_suites": [0x1301],
    "compression_methods": b"\x00",
    "extensions": [
        # SNI extension with one server name entry
        {"type": 0, "body": [{"name_type": 0, "host_name": b"example.com"}]},
    ],
}

data, tree = encode_inspect(client_hello, tls_client_hello_fmt)
print(format_tree(tree))
```

Output (truncated for brevity):
```text
* Mapping @ [0:63] (63 bytes) (6 items)
├─ [version] Mapping @ [0:2] (2 bytes) (2 items)
│  ├─ [major] Int @ [0:1] (1 bytes)
│  │    value: 3
│  │    data: 03
│  └─ [minor] Int @ [1:2] (1 bytes)
│       value: 3
│       data: 03
├─ [random] Mapping @ [2:34] (32 bytes) (2 items)
│  ├─ [gmt_unix_time] Int @ [2:6] (4 bytes)
│  │    value: 0
│  │    data: 00 00 00 00
│  └─ [random] Bytes @ [6:34] (28 bytes)
│       value: b'abcdefghijklmnopqrstuvwxyz_-'
│       data: 61 62 63 64 65 66 67 68 69 6a 6b 6c 6d 6e 6f 70 71 72 73 74 75 76 77 78 ... (truncated)
├─ [session_id] Sized @ [34:35] (1 bytes) (2 items)
│  ├─ [--size--] Int @ [34:35] (1 bytes)
│  │    value: 0
│  │    data: 00
│  └─ [None] Bytes @ [35:35] (0 bytes)
│       value: b''
├─ [cipher_suites] Sized @ [35:39] (4 bytes) (2 items)
│  ├─ [--size--] Int @ [35:37] (2 bytes)
│  │    value: 2
│  │    data: 00 02
│  └─ [None] Array @ [37:39] (2 bytes) (1 items)
│     └─ [0] Int @ [37:39] (2 bytes)
│          value: 4865
│          data: 13 01
├─ [compression_methods] Sized @ [39:41] (2 bytes) (2 items)
│  ├─ [--size--] Int @ [39:40] (1 bytes)
│  │    value: 1
│  │    data: 01
│  └─ [None] Bytes @ [40:41] (1 bytes)
│       value: b'\x00'
│       data: 00
└─ [extensions] Sized @ [41:63] (22 bytes) (2 items)
   ├─ [--size--] Int @ [41:43] (2 bytes)
   │    value: 20
   │    data: 00 14
   └─ [None] Array @ [43:63] (20 bytes) (1 items)
      └─ [0] Mapping @ [43:63] (20 bytes) (2 items)
         ├─ [type] Int @ [43:45] (2 bytes)
         │    value: 0
         │    data: 00 00
         └─ [body] Sized @ [45:63] (18 bytes) (2 items)
            ... (truncated for brevity)
```

The inspection tree provides visibility into the full parse structure, including
offsets and sizes at each nesting level.

## Error Model

The public API raises structured exceptions instead of only raw `ValueError`
instances.

- `EncodeError`: a Python value could not be serialized with the chosen format
- `DecodeError`: the incoming bytes did not match the format
- `ExcessDecodeError`: decoding succeeded, but trailing bytes remained;
  distinct from `DecodeError` — `exc.stream` is positioned at the excess data
  for further decoding, and `exc.remaining` holds a typed byte count
- `TypeConversionError`: decoding succeeded, but the result could not be converted into
  the requested `type`

These exceptions preserve context such as the active format, object, path,
cause, and optional inspection node.

```python
from fmtspec import DecodeError, ExcessDecodeError, decode, types

fmt = {
    "kind": types.u8,
    "payload": types.Sized(length=types.u8, fmt=types.Bytes()),
}

try:
    decode(b"\x01\x05abc", fmt)
except ExcessDecodeError as exc:
    # remaining bytes are accessible for further parsing
    print(exc.remaining)  # typed byte count
    print(exc.stream.read())  # or decode_stream(exc.stream, next_fmt)
    print(exc.path)
    print(exc.fmt)
except DecodeError as exc:
    # real decode failure (truncation, bad tag, etc.)
    print(exc)
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
