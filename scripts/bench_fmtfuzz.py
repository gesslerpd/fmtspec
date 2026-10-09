#!/usr/bin/env python3
"""Compare raw-format and compiled-plan fmtfuzz generation throughput."""

from __future__ import annotations

import argparse
import statistics
import time
from functools import partial
from typing import Any

from hypothesis import given, settings

from fmtfuzz import binary_strategy, compile_format
from fmtspec import types


def _consume_sample(_value: bytes) -> None:
    pass


def _generate_samples(strategy: Any, iterations: int) -> None:
    runner = settings(
        max_examples=iterations,
        derandomize=True,
        deadline=None,
        database=None,
    )(given(strategy)(_consume_sample))
    runner()


def _time_calls(func: Any, iterations: int) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    return time.perf_counter() - start


def _benchmark(name: str, func: Any, iterations: int, repeats: int) -> None:
    durations = [_time_calls(func, iterations) for _ in range(repeats)]
    mean = statistics.mean(durations)
    deviation = statistics.stdev(durations) if repeats > 1 else 0.0
    rate = iterations / mean if mean else float("inf")
    print(f"{name}: {rate:,.0f} samples/sec ({mean / iterations * 1e6:,.1f} µs/sample)")
    if repeats > 1:
        print(f"  standard deviation: {deviation:.4f}s")


def _benchmark_generation(
    name: str,
    strategy: Any,
    iterations: int,
    repeats: int,
) -> None:
    durations = [
        _time_calls(partial(_generate_samples, strategy, iterations), 1) for _ in range(repeats)
    ]
    mean = statistics.mean(durations)
    deviation = statistics.stdev(durations) if repeats > 1 else 0.0
    rate = iterations / mean if mean else float("inf")
    print(f"{name}: {rate:,.0f} samples/sec ({mean / iterations * 1e6:,.1f} µs/sample)")
    if repeats > 1:
        print(f"  standard deviation: {deviation:.4f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error("--iterations and --repeats must be at least 1")

    fmt = {
        "count": types.u8,
        "items": types.array(types.u16le, dims=types.Ref("count")),
    }
    plan = compile_format(fmt)
    _benchmark(
        "compile_format",
        partial(compile_format, fmt),
        args.iterations,
        args.repeats,
    )
    _benchmark_generation(
        "binary generation: raw format",
        binary_strategy(fmt),
        args.iterations,
        args.repeats,
    )
    _benchmark_generation(
        "binary generation: reused plan",
        binary_strategy(plan),
        args.iterations,
        args.repeats,
    )


if __name__ == "__main__":
    main()
