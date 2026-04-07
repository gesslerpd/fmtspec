"""Switch type for conditional format selection and tag-based dispatch.

This merged `Switch` supports the original key-based dispatch (sibling field
selection) and an optional tag-based dispatch mode for formats that encode
their own tag in the stream. Tag-mode supports exact tag decoders and range
decoders and an optional encoding dispatch path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import KW_ONLY, dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

import msgspec

from .._utils import derive_fmt
from ..stream import decode_stream, encode_stream
from ._ref import Ref

if TYPE_CHECKING:
    from types import EllipsisType

    from .._protocol import Context, Format


def _get_struct_tag_info(tp: type) -> tuple[Any, str] | None:
    config = getattr(tp, "__struct_config__", None)
    if config is None:
        return None

    tag = getattr(config, "tag", None)
    tag_field = getattr(config, "tag_field", None)
    if tag is None or tag_field is None:
        return None

    return tag, tag_field


@dataclass(frozen=True, slots=True)
class Switch:
    """Select a format from sibling context.

    ``Switch`` is the main building block for tagged payloads where another
    field in the current parent object determines how the current field should
    be encoded or decoded.

    Example:
        >>> from fmtspec import decode, encode, types
        >>> fmt = {
        ...     "kind": types.u8,
        ...     "body": types.Switch(types.Ref("kind"), {1: types.u16}, default=types.bytes_),
        ... }
        >>> decode(encode({"kind": 1, "body": 5}, fmt), fmt)["body"]
        5
    """

    size: ClassVar[EllipsisType] = ...

    key: Ref
    cases: dict[Any, Format]
    _: KW_ONLY
    default: Format | None = None

    def _get_fmt(self, key_value: Any) -> Format:
        fmt = self.cases.get(key_value, self.default)
        if fmt is None:
            raise KeyError(f"Key {key_value!r} not found in cases and no default provided")
        return fmt

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        key_value = self.key.resolve(context)
        fmt = self._get_fmt(key_value)
        encode_stream(stream, value, fmt, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        inner_data = stream.read()
        key_value = self.key.resolve(context)
        fmt = self._get_fmt(key_value)

        inner_stream = BytesIO(inner_data)
        return decode_stream(inner_stream, fmt, context=context)


@dataclass(frozen=True, slots=True)
class TaggedUnion:
    """Decode or encode one branch of a tagged ``msgspec.Struct`` union."""

    size: ClassVar[EllipsisType] = ...

    tag: Format | Ref
    fmt_map: dict[Any, Any] = field(default_factory=dict)
    _: KW_ONLY
    # runtime mappings populated in __post_init__
    fmt_by_tag: dict[Any, Any] = field(default_factory=dict)
    struct_cls_by_tag: dict[Any, type] = field(default_factory=dict)
    struct_tag_field: str | None = None

    # implement MapPrefill protocol to support auto-populating tag field
    def prefill(
        self,
        *,
        context: Context,
    ) -> None:
        """Populate a sibling tag field from the selected branch value when possible."""
        if not isinstance(self.tag, Ref):
            return
        parent = context.parents[-1]
        field_key = context.path[-1]
        if not isinstance(parent, Mapping) or field_key is None:
            return
        if self.tag.key in parent:
            return
        if field_key not in parent:
            return

        branch_value = parent[field_key]
        if not isinstance(branch_value, Mapping) or self.struct_tag_field is None:
            return

        tag_value = branch_value.get(self.struct_tag_field)
        if tag_value is None:
            return

        if hasattr(parent, "__setitem__"):
            parent[self.tag.key] = tag_value

    def __post_init__(self) -> None:
        normalized_fmt_by_tag: dict[Any, Any] = {}
        struct_cls_by_tag: dict[Any, type] = {}
        struct_tag_field: str | None = None

        for struct_cls in self.fmt_map.values():
            if (struct_tag_info := _get_struct_tag_info(struct_cls)) is None:
                raise ValueError("TaggedUnion only supports msgspec tagged Struct classes")

            resolved_tag, resolved_tag_field = struct_tag_info
            if struct_tag_field is None:
                struct_tag_field = resolved_tag_field
            elif struct_tag_field != resolved_tag_field:
                raise ValueError("All Struct branches must share the same tag_field")

            normalized_fmt_by_tag[resolved_tag] = derive_fmt(struct_cls)
            struct_cls_by_tag[resolved_tag] = struct_cls

        if (
            struct_tag_field is not None
            and isinstance(self.tag, Ref)
            and self.tag.key != struct_tag_field
        ):
            raise ValueError(
                f"TaggedUnion tag Ref key '{self.tag.key}' does not match Struct tag_field '{struct_tag_field}'"
            )

        object.__setattr__(self, "fmt_by_tag", normalized_fmt_by_tag)
        object.__setattr__(self, "struct_cls_by_tag", struct_cls_by_tag)
        object.__setattr__(self, "struct_tag_field", struct_tag_field)

    def _resolve_tag_for_encode(
        self, value: Mapping[Any, Any], *, context: Context
    ) -> tuple[Any, bool]:
        if isinstance(self.tag, Ref):
            resolved_tag = self.tag.resolve(context)

            value_tag = value.get(self.struct_tag_field, resolved_tag)
            if value_tag != resolved_tag:
                raise ValueError(f"Tag mismatch: expected {resolved_tag!r}, got {value_tag!r}")
            return resolved_tag, False
        return value.get(self.struct_tag_field), True

    def _decode_tag(self, stream: BinaryIO, *, context: Context) -> Any:
        if isinstance(self.tag, Ref):
            return self.tag.resolve(context)
        return decode_stream(stream, self.tag, context=context)

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        unknown_type = ValueError("Unknown type")
        if not isinstance(value, Mapping) or self.struct_tag_field is None:
            raise unknown_type

        tag_val, write_tag = self._resolve_tag_for_encode(value, context=context)
        if tag_val is None:
            raise unknown_type

        fmt = self.fmt_by_tag.get(tag_val)
        if fmt is None:
            raise unknown_type

        if write_tag:
            encode_stream(stream, tag_val, self.tag, context=context)
        encode_stream(stream, value, fmt, context=context)

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        tag = self._decode_tag(stream, context=context)

        fmt = self.fmt_by_tag.get(tag)
        if fmt is None:
            if isinstance(tag, int):
                raise ValueError(f"Unknown tag: 0x{tag:02x}")
            raise ValueError(f"Unknown tag: {tag!r}")

        struct_cls = self.struct_cls_by_tag[tag]
        return msgspec.convert(decode_stream(stream, fmt, context=context), struct_cls)
