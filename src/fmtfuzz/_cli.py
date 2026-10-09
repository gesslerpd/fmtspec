"""Command-line interface for fmtfuzz campaigns."""

from __future__ import annotations

import argparse
import importlib
from typing import TYPE_CHECKING, Any

from fmtspec import DecodeError, ExcessDecodeError

from ._corpus import Corpus
from ._engine import FuzzConfig, Fuzzer

if TYPE_CHECKING:
    from collections.abc import Sequence


def _load_object(path: str) -> Any:
    module_name, separator, attribute_path = path.partition(":")
    if not separator or not module_name or not attribute_path:
        raise ValueError(f"Expected an import path in module:attribute form, got {path!r}")
    value: Any = importlib.import_module(module_name)
    for part in attribute_path.split("."):
        value = getattr(value, part)
    return value


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fmtfuzz",
        description="Fuzz a bytes target using an fmtspec format.",
    )
    parser.add_argument(
        "--format", required=True, help="Format object import path (module:attribute)"
    )
    parser.add_argument(
        "--target", required=True, help="Bytes callback import path (module:callable)"
    )
    parser.add_argument("--max-examples", type=int, default=1000)
    parser.add_argument("--max-size", type=int, default=4096)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--corpus", help="Directory for content-addressed inputs")
    parser.add_argument(
        "--expected-exception",
        action="append",
        default=[],
        metavar="MODULE:CLASS",
        help="Additional exception type treated as an expected input rejection",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one fuzz campaign from importable format and target objects."""
    args = _parse_args(argv)
    try:
        fmt = _load_object(args.format)
        target = _load_object(args.target)
        extra_exceptions = tuple(_load_object(path) for path in args.expected_exception)
    except (AttributeError, ValueError) as exc:
        raise SystemExit(f"fmtfuzz: {exc}") from exc

    if not callable(target):
        raise SystemExit("fmtfuzz: target import path does not refer to a callable")
    if any(not isinstance(exc, type) or not issubclass(exc, Exception) for exc in extra_exceptions):
        raise SystemExit("fmtfuzz: expected-exception imports must be Exception subclasses")

    corpus = Corpus(args.corpus, max_size=args.max_size) if args.corpus else None
    fuzzer = Fuzzer(
        fmt,
        target,
        corpus=corpus,
        expected_exceptions=(DecodeError, ExcessDecodeError, *extra_exceptions),
    )
    result = fuzzer.run(
        FuzzConfig(
            max_examples=args.max_examples,
            max_input_size=args.max_size,
            seed=args.seed,
        )
    )
    print(
        f"Executed {result.executions} examples: "
        f"{result.accepted} accepted, {result.rejected} rejected; "
        f"corpus has {result.corpus_entries} entries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
