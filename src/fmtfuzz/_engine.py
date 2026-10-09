"""Hypothesis-backed fuzzing engine and public campaign configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from hypothesis import given, settings
from hypothesis import seed as hypothesis_seed
from hypothesis import strategies as st

from fmtspec import DecodeError, ExcessDecodeError

from ._mutations import mutate_malformed, mutate_valid
from ._plan import FieldHint, FormatPath, compile_format
from ._strategies import binary_strategy

if TYPE_CHECKING:
    from datetime import timedelta

    from hypothesis.database import ExampleDatabase
    from hypothesis.strategies import SearchStrategy

    from ._corpus import Corpus

type FuzzTarget = Callable[[bytes], Any]
type Feedback = Callable[[bytes], Any]


def _mutate_valid_with_seed(
    data: bytes,
    seed: int,
    *,
    fmt: Any,
    max_size: int,
) -> bytes:
    return mutate_valid(data, fmt, seed=seed, max_size=max_size)


def _mutate_malformed_with_seed(
    data: bytes,
    seed: int,
    *,
    fmt: Any,
    max_size: int,
) -> bytes:
    return mutate_malformed(data, fmt, seed=seed, max_size=max_size)


def _valid_mutations(
    data: bytes,
    *,
    fmt: Any,
    max_size: int,
) -> SearchStrategy[bytes]:
    return st.integers().map(partial(_mutate_valid_with_seed, data, fmt=fmt, max_size=max_size))


def _malformed_mutations(
    data: bytes,
    *,
    fmt: Any,
    max_size: int,
) -> SearchStrategy[bytes]:
    return st.integers().map(partial(_mutate_malformed_with_seed, data, fmt=fmt, max_size=max_size))


@dataclass(frozen=True, slots=True)
class FuzzConfig:
    """Bounds and reproducibility options for one fuzzing campaign."""

    max_examples: int = 1000
    max_input_size: int = 4096
    seed: int | None = None
    deadline: int | timedelta | None = None
    database: ExampleDatabase | None = None

    def __post_init__(self) -> None:
        if self.max_examples < 1:
            raise ValueError("max_examples must be at least 1")
        if self.max_input_size < 1:
            raise ValueError("max_input_size must be at least 1")


@dataclass(frozen=True, slots=True)
class FuzzResult:
    """Campaign execution counts returned when no target failure occurs."""

    executions: int
    accepted: int
    rejected: int
    corpus_entries: int


def fuzz_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
    corpus: Corpus | None = None,
    field_hints: Mapping[FormatPath, FieldHint | tuple[Any, ...]] | None = None,
) -> SearchStrategy[bytes]:
    """Combine valid encodings, valid mutations, and malformed mutations."""
    plan = compile_format(fmt, field_hints=field_hints)
    fmt = plan
    valid = binary_strategy(plan, max_size=max_size)
    sources: list[SearchStrategy[bytes]] = [valid]

    if corpus is not None:
        stored = corpus.load()
        if any(len(data) > max_size for data in stored):
            raise ValueError(f"Corpus contains an input larger than max_size={max_size}")
        if stored:
            sources.append(st.sampled_from(stored))

    base = sources[0] if len(sources) == 1 else st.one_of(*sources)
    valid_mutations = valid.flatmap(partial(_valid_mutations, fmt=fmt, max_size=max_size))
    malformed_mutations = base.flatmap(partial(_malformed_mutations, fmt=fmt, max_size=max_size))
    return st.one_of(base, valid_mutations, malformed_mutations)


class Fuzzer:
    """Run a bytes target against format-derived Hypothesis examples.

    Target exceptions are failures unless their types appear in
    ``expected_exceptions``. Hypothesis then shrinks unexpected failures to a
    smaller reproducer. A feedback callback can return a hashable novelty key;
    the first input for each new key is added to the optional corpus.
    """

    def __init__(  # noqa: PLR0913
        self,
        fmt: Any,
        target: FuzzTarget,
        *,
        corpus: Corpus | None = None,
        expected_exceptions: tuple[type[Exception], ...] = (
            DecodeError,
            ExcessDecodeError,
        ),
        feedback: Feedback | None = None,
        field_hints: Mapping[FormatPath, FieldHint | tuple[Any, ...]] | None = None,
    ) -> None:
        if not callable(target):
            raise TypeError("target must be callable")
        if any(
            not isinstance(exc, type) or not issubclass(exc, Exception)
            for exc in expected_exceptions
        ):
            raise TypeError("expected_exceptions must contain Exception subclasses")
        self.plan = compile_format(fmt, field_hints=field_hints)
        self.fmt = self.plan.fmt
        self.target = target
        self.corpus = corpus
        self.expected_exceptions = expected_exceptions
        self.feedback = feedback

    def strategy(self, *, max_size: int = 4096) -> SearchStrategy[bytes]:
        """Return a strategy suitable for ``@given`` or HypoFuzz tests."""
        return fuzz_strategy(self.plan, max_size=max_size, corpus=self.corpus)

    def run(self, config: FuzzConfig = FuzzConfig()) -> FuzzResult:
        """Run a bounded Hypothesis campaign.

        Unexpected target exceptions propagate as Hypothesis failures, which
        includes the minimized binary example.
        """
        executions = 0
        accepted = 0
        rejected = 0
        feedback_keys: set[Any] = set()

        @given(data=self.strategy(max_size=config.max_input_size))
        @settings(
            max_examples=config.max_examples,
            deadline=config.deadline,
            database=config.database,
        )
        def execute(data: bytes) -> None:
            nonlocal executions, accepted, rejected
            executions += 1
            try:
                self.target(data)
            except self.expected_exceptions:
                rejected += 1
            else:
                accepted += 1

            if self.feedback is not None:
                key = self.feedback(data)
                if key is not None and key not in feedback_keys:
                    feedback_keys.add(key)
                    if self.corpus is not None:
                        self.corpus.add(data)

        runner = execute
        if config.seed is not None:
            runner = hypothesis_seed(config.seed)(runner)
        runner()

        return FuzzResult(
            executions=executions,
            accepted=accepted,
            rejected=rejected,
            corpus_entries=len(self.corpus) if self.corpus is not None else 0,
        )
