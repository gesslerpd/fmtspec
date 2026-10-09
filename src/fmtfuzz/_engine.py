"""Hypothesis-backed fuzzing engine and public campaign configuration."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from hypothesis import given, settings
from hypothesis import seed as hypothesis_seed
from hypothesis import strategies as st

from fmtspec import DecodeError, ExcessDecodeError

from ._mutations import mutate_malformed, mutate_valid
from ._plan import compile_format
from ._strategies import binary_strategy

if TYPE_CHECKING:
    from datetime import timedelta

    from hypothesis.database import ExampleDatabase
    from hypothesis.strategies import SearchStrategy

    from ._corpus import Corpus

type FuzzTarget = Callable[[bytes], Any]
type Feedback = Callable[[bytes], Hashable | None]


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


@dataclass(slots=True, repr=False)
class _RunState:
    target: FuzzTarget
    expected_exceptions: tuple[type[Exception], ...]
    feedback: Feedback | None
    corpus: Corpus | None
    accepted: int = 0
    rejected: int = 0
    feedback_keys: set[Hashable] = field(default_factory=set)

    def __repr__(self) -> str:
        return "_RunState()"


def _execute_sample(state: _RunState, data: bytes) -> None:
    try:
        state.target(data)
    except state.expected_exceptions:
        state.rejected += 1
    else:
        state.accepted += 1

    if state.feedback is not None:
        key = state.feedback(data)
        if key is not None and key not in state.feedback_keys:
            state.feedback_keys.add(key)
            if state.corpus is not None:
                state.corpus.add(data)


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

    accepted: int
    rejected: int
    corpus_entries: int

    @property
    def executions(self) -> int:
        """Return the total number of accepted and rejected executions."""
        return self.accepted + self.rejected


def fuzz_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
    corpus: Corpus | None = None,
) -> SearchStrategy[bytes]:
    """Combine valid encodings, valid mutations, and malformed mutations."""
    plan = compile_format(fmt)
    valid = binary_strategy(plan, max_size=max_size)
    base = valid

    if corpus is not None:
        stored = corpus.load()
        if any(len(data) > max_size for data in stored):
            raise ValueError(f"Corpus contains an input larger than max_size={max_size}")
        if stored:
            base = st.one_of(valid, st.sampled_from(stored))

    valid_mutations = valid.flatmap(partial(_valid_mutations, fmt=plan, max_size=max_size))
    malformed_mutations = base.flatmap(partial(_malformed_mutations, fmt=plan, max_size=max_size))
    return st.one_of(base, valid_mutations, malformed_mutations)


def message_sequence_strategy(
    fmt: Any,
    *,
    min_messages: int = 0,
    max_messages: int = 8,
    max_message_size: int = 4096,
    corpus: Corpus | None = None,
) -> SearchStrategy[tuple[bytes, ...]]:
    """Generate a bounded sequence of independently fuzzed binary messages.

    The sequence is returned as a tuple. Each message uses the same mixed
    valid/malformed strategy as :func:`fuzz_strategy`; protocol state and
    message-to-message dependencies remain the caller's responsibility.
    """
    if min_messages < 0:
        raise ValueError("min_messages must be non-negative")
    if max_messages < 0:
        raise ValueError("max_messages must be non-negative")
    if min_messages > max_messages:
        raise ValueError("min_messages cannot exceed max_messages")
    if max_message_size < 1:
        raise ValueError("max_message_size must be at least 1")

    messages = fuzz_strategy(
        fmt,
        max_size=max_message_size,
        corpus=corpus,
    )
    return st.lists(
        messages,
        min_size=min_messages,
        max_size=max_messages,
    ).map(tuple)


class Fuzzer:
    """Run a bytes target against format-derived Hypothesis examples.

    Target exceptions are failures unless their types appear in
    ``expected_exceptions``. Hypothesis then shrinks unexpected failures to a
    smaller reproducer. A feedback callback can return a hashable novelty key;
    the first input for each new key is added to the optional corpus.
    """

    def __init__(
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
    ) -> None:
        if not callable(target):
            raise TypeError("target must be callable")
        if any(
            not isinstance(exc, type) or not issubclass(exc, Exception)
            for exc in expected_exceptions
        ):
            raise TypeError("expected_exceptions must contain Exception subclasses")
        self.plan = compile_format(fmt)
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
        state = _RunState(
            target=self.target,
            expected_exceptions=self.expected_exceptions,
            feedback=self.feedback,
            corpus=self.corpus,
        )
        runner = given(
            st.just(state),
            self.strategy(max_size=config.max_input_size),
        )(_execute_sample)
        runner = settings(
            max_examples=config.max_examples,
            deadline=config.deadline,
            database=config.database,
        )(runner)
        if config.seed is not None:
            runner = hypothesis_seed(config.seed)(runner)
        runner()

        return FuzzResult(
            accepted=state.accepted,
            rejected=state.rejected,
            corpus_entries=len(self.corpus) if self.corpus is not None else 0,
        )
