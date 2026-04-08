#!/usr/bin/env python3
"""Quick micro-bench for encode/decode hot paths."""

from __future__ import annotations

import time

from fmtspec import decode, encode
from fmtspec.lib.msgpack import msgpack as msgpack_fmt

payload = {
    "id": 1,
    "name": "Alice",
    "active": True,
    "score": 95.5,
    "tags": ["admin", "user"],
    "payload": "x" * 200,
}
blob = encode({"records": [payload] * 200}, fmt=msgpack_fmt)


def time_fn(fn, iterations=1000):
    t0 = time.perf_counter()
    for _ in range(iterations):
        fn()
    return time.perf_counter() - t0


iters = 2000
enc_time = time_fn(lambda: encode({"records": [payload] * 200}, fmt=msgpack_fmt), iterations=iters)
dec_time = time_fn(lambda: decode(blob, fmt=msgpack_fmt), iterations=iters)

print(f"micro encode: {iters / enc_time:,.0f} ops/sec — {enc_time / iters * 1e6:,.1f} µs/op")
print(f"micro decode: {iters / dec_time:,.0f} ops/sec — {dec_time / iters * 1e6:,.1f} µs/op")
