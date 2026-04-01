#!/usr/bin/env python3
"""Simple benchmarks for fmtspec encode/decode paths.

Usage:
    python scripts/benchmark.py --iterations 1000 --repeats 5 --list-size 1000
"""

from __future__ import annotations

import os

# set before importing `msgpack`
os.environ["MSGPACK_PUREPYTHON"] = "1"
import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Annotated, ClassVar

from fmtspec import decode, encode, types

try:
    import msgpack
except Exception:  # pragma: no cover - optional dependency for benchmarks
    msgpack = None

sys.path.insert(0, "tests/examples")
from test_msgpack import MsgPack

msgpack_fmt = MsgPack()

INT_FMT = types.u32le
STR_FMT = types.TakeUntil(types.Str(), b"\0")


@dataclass(slots=True)
class DataclassBench:
    sentinel: ClassVar[object] = object()
    key: Annotated[str, STR_FMT]
    number: Annotated[int, INT_FMT]


@dataclass(slots=True)
class NestedBench:
    data: DataclassBench
    more: DataclassBench


def _time_func(func, iterations: int) -> float:
    t0 = time.perf_counter()
    for _ in range(iterations):
        func()
    return time.perf_counter() - t0


def bench(name: str, fn, iterations: int, repeats: int) -> None:
    times = []
    for _ in range(repeats):
        times.append(_time_func(fn, iterations))
    mean = statistics.mean(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0.0
    ops_per_sec = iterations / mean if mean > 0 else float("inf")
    print(
        f"{name}: {ops_per_sec:,.0f} ops/sec — {mean / iterations * 1e6:,.1f} µs/op (±{stdev:.4f}s)"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=1000)
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--list-size", type=int, default=1000)
    args = p.parse_args()

    # small dataclass roundtrip
    # obj = DataclassBench(key="value", number=42)
    # bench(
    #     "encode: small dataclass",
    #     lambda: encode_stream(io.BytesIO(), obj),
    #     args.iterations,
    #     args.repeats,
    # )

    # buf = io.BytesIO()
    # encode_stream(buf, obj)
    # bench(
    #     "decode: small dataclass (derive shape)",
    #     lambda: (buf.seek(0), decode_stream(buf, type=DataclassBench)),
    #     args.iterations,
    #     args.repeats,
    # )

    # # nested dataclass
    # nested = NestedBench(data=obj, more=DataclassBench(key="other", number=7))
    # bench(
    #     "encode: nested dataclass",
    #     lambda: encode_stream(io.BytesIO(), nested),
    #     args.iterations,
    #     args.repeats,
    # )
    # nbuf = io.BytesIO()
    # encode_stream(nbuf, nested)
    # bench(
    #     "decode: nested dataclass",
    #     lambda: (nbuf.seek(0), decode_stream(nbuf, type=NestedBench)),
    #     args.iterations,
    #     args.repeats,
    # )

    # # large array of ints using PrefixedArray
    # array_fmt = types.PrefixedArray("little", 4, INT_FMT)
    # arr = list(range(args.list_size))
    # bench(
    #     "encode: int array",
    #     lambda: encode_stream(io.BytesIO(), arr, fmt=array_fmt),
    #     args.iterations,
    #     args.repeats,
    # )
    # arr_buf = io.BytesIO()
    # encode_stream(arr_buf, arr, fmt=array_fmt)
    # bench(
    #     "decode: int array",
    #     lambda: (arr_buf.seek(0), decode_stream(arr_buf, fmt=array_fmt)),
    #     args.iterations,
    #     args.repeats,
    # )

    # Compare the local `msgpack_fmt` implementation via the fmtspec API
    base = {
        "id": 1,
        "name": "Alice",
        "active": True,
        "score": 95.5,
        "tags": ["admin", "user"],
        "payload": "x" * 200,
        "data": list(range(10)),
        "data_float": [i + 0.333 for i in range(10)],
    }
    payload = {"records": [base] * 200}

    fmtspec_msgpack_blob = encode(payload, fmt=msgpack_fmt)

    bench(
        "encode: fmtspec (msgpack_fmt)",
        lambda: encode(payload, fmt=msgpack_fmt),
        args.iterations,
        args.repeats,
    )

    bench(
        "decode: fmtspec (msgpack_fmt)",
        lambda: decode(fmtspec_msgpack_blob, fmt=msgpack_fmt),
        args.iterations,
        args.repeats,
    )

    # Also compare to the external `msgpack` package when available
    if msgpack is not None:
        lib_blob = msgpack.packb(payload)
        assert lib_blob == fmtspec_msgpack_blob

        bench(
            "encode: msgpack.packb",
            lambda: msgpack.packb(payload),
            args.iterations,
            args.repeats,
        )

        bench(
            "decode: msgpack.unpackb",
            lambda: msgpack.unpackb(lib_blob),
            args.iterations,
            args.repeats,
        )
    else:
        print("msgpack not installed; skipping external msgpack comparison")


if __name__ == "__main__":
    main()
