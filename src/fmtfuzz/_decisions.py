"""Capture and replay structured choices for compiled format plans."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from fmtspec import decode, encode

from ._mutations import mutate_malformed, mutate_valid
from ._plan import FormatPlan, compile_format
from ._strategies import format_strategy

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy


class DecisionSeedError(ValueError):
    """Raised when a value cannot be replayed through its compiled format."""


@dataclass(frozen=True, slots=True)
class DecisionSeed:
    """An in-memory, structured decision record tied to one compiled plan."""

    plan: FormatPlan
    value: Any

    def replay(self, *, max_size: int | None = None) -> bytes:
        data = encode(self.value, self.plan.fmt)
        if max_size is not None and len(data) > max_size:
            raise DecisionSeedError(
                f"Replayed input has {len(data)} bytes, exceeding max_size={max_size}"
            )
        return data

    def mutate(
        self,
        *,
        valid: bool = True,
        seed: int | None = None,
        max_size: int = 4096,
    ) -> bytes:
        """Mutate the recorded structure and replay it through its format."""
        data = self.replay(max_size=max_size)
        if valid:
            mutated = mutate_valid(data, self.plan, seed=seed, max_size=max_size)
        else:
            mutated = mutate_malformed(data, self.plan, seed=seed, max_size=max_size)
        if len(mutated) > max_size:
            raise DecisionSeedError(
                f"Mutated input has {len(mutated)} bytes, exceeding max_size={max_size}"
            )
        return mutated


def capture_decision_seed(data: bytes, fmt: Any) -> DecisionSeed:
    """Parse a canonical input and retain its structured choices for replay."""
    plan = compile_format(fmt)
    value = decode(data, plan.fmt)
    seed = DecisionSeed(plan, deepcopy(value))
    if seed.replay() != data:
        raise DecisionSeedError(
            "Input does not round-trip canonically through this format and cannot be replayed"
        )
    return seed


def replay_decision_seed(
    seed: DecisionSeed,
    *,
    plan: FormatPlan | None = None,
    max_size: int | None = None,
) -> bytes:
    """Replay a seed, optionally requiring its originating compiled plan."""
    if plan is not None and seed.plan is not plan:
        raise DecisionSeedError("Decision seed belongs to a different FormatPlan")
    return seed.replay(max_size=max_size)


def _decision_seed_from_value(value: Any, *, plan: FormatPlan) -> DecisionSeed:
    return DecisionSeed(plan, deepcopy(value))


def decision_seed_strategy(
    fmt: Any,
    *,
    max_size: int = 4096,
) -> SearchStrategy[DecisionSeed]:
    """Generate replayable structured decisions for a format."""
    plan = compile_format(fmt)
    strategy: SearchStrategy[Any] = format_strategy(plan, max_size=max_size)
    return strategy.map(partial(_decision_seed_from_value, plan=plan))
