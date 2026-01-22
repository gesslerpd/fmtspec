"""Reference helper for resolving sibling/context values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._protocol import Context

_NO_DEFAULT = object()


@dataclass(frozen=True, slots=True)
class Ref:
    """Typed reference to a sibling value in the current serialization context.

    Attributes:
        key: Sibling field name to lookup on the target parent mapping.
        parent: How many levels up to look (1 => context.parents[-1]).
        default: Value to return when the key is missing. If omitted the
                 resolver will raise KeyError.
        cast: Optional callable to transform the looked-up value (e.g., int).
        expected_type: Optional type to assert the resolved value's type.
        allow_none: Whether `None` is an acceptable resolved value.
    """

    key: str
    parent: int = 1
    default: Any = _NO_DEFAULT
    cast: Callable[[Any], Any] | None = None

    def resolve(self, context: Context) -> Any:
        """Resolve this reference against the given `Context`.

        Raises KeyError when the key is missing and no default is provided.
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
