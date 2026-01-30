#!/usr/bin/env python3
"""Micro-benchmark for `Array` formats.

Creates a fixed-shape 2D array of integers and measures encode/decode
throughput (ops/sec and µs/op), similar to `micro_bench.py`.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import TYPE_CHECKING, cast

from fmtspec import decode, decode_stream, encode, encode_stream, types

if TYPE_CHECKING:
    from collections.abc import Sequence


def time_fn(fn, iterations: int = 1000) -> float:
    t0 = time.perf_counter()
    for _ in range(iterations):
        fn()
    return time.perf_counter() - t0


type ListOfList[T] = Sequence[T | ListOfList[T]]


def make_array[T](element: T, dims: Sequence[int]) -> ListOfList[T]:
    if not dims:
        raise ValueError("dims must be non-empty")

    # cast since the loop guaranteed to run at least once
    result = cast("list[T]", element)
    for dim in reversed(dims):
        result = [result] * dim
    return result


def decode_file(f, fmt) -> None:
    decode_stream(f, fmt=fmt)


def encode_file(f, value, fmt) -> None:
    encode_stream(value, f, fmt=fmt)


def main() -> None:
    rows = 200
    cols = 10
    iters = 2000

    # 32-bit unsigned little-endian integers
    elem_fmt = types.u32le
    arr_fmt = types.Array(elem_fmt, (rows, cols))

    value = make_array(0, (rows, cols))

    # warmup / produce blob for decode bench
    blob = encode(value, fmt=arr_fmt)

    # write blob to a temporary file for file-read decode benchmarking
    tf = tempfile.NamedTemporaryFile(delete=False)
    try:
        tf.write(blob)
        tf.flush()
        temp_path = tf.name
    finally:
        tf.close()

    enc_time = time_fn(lambda: encode(value, fmt=arr_fmt), iterations=iters)
    dec_time = time_fn(lambda: decode(blob, fmt=arr_fmt), iterations=iters)

    print(f"array encode: {iters / enc_time:,.0f} ops/sec — {enc_time / iters * 1e6:,.1f} µs/op")
    print(f"array decode: {iters / dec_time:,.0f} ops/sec — {dec_time / iters * 1e6:,.1f} µs/op")

    # compare from a tempfile (read-from-disk each iteration)
    with open(temp_path, "wb") as f:
        enc_file_time = time_fn(lambda: encode_file(f, value, arr_fmt), iterations=iters)
    with open(temp_path, "rb") as f:
        dec_file_time = time_fn(lambda: decode_file(f, arr_fmt), iterations=iters)

    print(
        f"tempfile encode: {iters / enc_file_time:,.0f} ops/sec — {enc_file_time / iters * 1e6:,.1f} µs/op"
    )
    print(
        f"tempfile decode: {iters / dec_file_time:,.0f} ops/sec — {dec_file_time / iters * 1e6:,.1f} µs/op"
    )

    # naive make_array approach for comparison
    make_arr_format = make_array(elem_fmt, (rows, cols))

    enc_time = time_fn(lambda: encode(value, fmt=make_arr_format), iterations=iters)
    dec_time = time_fn(lambda: decode(blob, fmt=make_arr_format), iterations=iters)

    print(
        f"make_array encode: {iters / enc_time:,.0f} ops/sec — {enc_time / iters * 1e6:,.1f} µs/op"
    )
    print(
        f"make_array decode: {iters / dec_time:,.0f} ops/sec — {dec_time / iters * 1e6:,.1f} µs/op"
    )

    # remove temp file

    print("size of tempfile:", os.path.getsize(temp_path))
    try:
        os.remove(temp_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
