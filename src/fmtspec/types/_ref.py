"""Reference helper for resolving sibling/context values."""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._protocol import Context


@dataclass(frozen=True, slots=True)
class Ref:
    """Typed reference to a sibling value in the current serialization context.

    Attributes:
        key: Sibling field name to lookup on the target parent mapping.
        parent: How many levels up to look (1 => context.parents[-1]).
        cast: Optional callable to transform the looked-up value (e.g., ``int``).
    """

    key: str
    _: KW_ONLY
    parent: int = 1
    cast: Callable[[Any], Any] | None = None

    def resolve(self, context: Context) -> Any:
        """Resolve this reference against the given `Context`.

        Raises KeyError when the key is missing.
        Propagates exceptions raised by `cast`.
        """
        # determine parent mapping
        try:
            target = context.parents[-self.parent]
        except IndexError:
            raise KeyError(f"Invalid parent level {self.parent}")

        val = target[self.key]

        # apply cast
        if self.cast is not None:
            val = self.cast(val)

        return val
