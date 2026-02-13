from typing import Annotated

import msgspec
import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


class MsgspecU16(msgspec.Struct, tag_field="kind", tag="u16"):
    value: Annotated[int, types.u16]


class MsgspecBytes4(msgspec.Struct, tag_field="kind", tag="raw"):
    value: Annotated[bytes, types.Bytes(4)]


class MsgspecBytes2(msgspec.Struct, tag_field="kind", tag="b2!"):
    value: Annotated[bytes, types.Bytes(2)]


class MsgspecIntTagA(msgspec.Struct, tag_field="kind", tag=1):
    value: Annotated[int, types.u8]


class MsgspecIntTagB(msgspec.Struct, tag_field="kind", tag=2):
    value: Annotated[bytes, types.Bytes(2)]


def test_tagged_union_msgspec_struct_roundtrip() -> None:
    fmt = types.TaggedUnion(
        tag=types.Str(3),
        fmt_map={
            100: MsgspecU16,
            101: MsgspecBytes4,
        },
    )

    data = encode(MsgspecU16(0x1234), fmt)
    assert data == b"u16\x12\x34"

    result = decode(data, fmt)
    assert result == MsgspecU16(0x1234)

    data = encode(MsgspecBytes4(b"test"), fmt)
    assert data == b"rawtest"

    result = decode(data, fmt)
    assert result == MsgspecBytes4(b"test")


def test_tagged_union_decode_consumes_only_selected_branch_bytes() -> None:
    tagged = types.TaggedUnion(
        tag=types.Str(3),
        fmt_map={
            1: MsgspecBytes2,
        },
    )
    fmt = {"value": tagged, "tail": types.u8}

    decoded = decode(b"b2!ab\xff", fmt)
    assert decoded == {"value": MsgspecBytes2(b"ab"), "tail": 0xFF}


def test_tagged_union_ref_tag_field_dispatch_mode() -> None:
    fmt = {
        "kind": types.Str(3),
        "body": types.TaggedUnion(
            tag=types.Ref("kind"),
            fmt_map={
                100: MsgspecU16,
                101: MsgspecBytes4,
            },
        ),
    }

    obj = {"kind": "u16", "body": MsgspecU16(0x1234)}
    data = encode(obj, fmt)
    assert data == b"u16\x12\x34"

    result = decode(data, fmt)
    assert result == obj


def test_tagged_union_ref_tag_field_mismatch_raises() -> None:
    fmt = {
        "kind": types.Str(3),
        "body": types.TaggedUnion(
            tag=types.Ref("kind"),
            fmt_map={
                100: MsgspecU16,
                101: MsgspecBytes4,
            },
        ),
    }

    obj = {"kind": "raw", "body": MsgspecU16(0x1234)}

    with pytest.raises(EncodeError, match="Tag mismatch"):
        encode(obj, fmt)


def test_tagged_union_unknown_tag_raises() -> None:
    fmt = types.TaggedUnion(
        tag=types.Str(3),
        fmt_map={
            100: MsgspecU16,
            101: MsgspecBytes4,
        },
    )

    with pytest.raises(DecodeError, match="Unknown tag: 'bad'"):
        decode(b"bad\x00", fmt)


def test_tagged_union_rejects_non_msgspec_branches() -> None:
    with pytest.raises(ValueError, match="msgspec tagged Struct"):
        types.TaggedUnion(
            tag=types.u8,
            fmt_map={
                1: Annotated[int, types.u8],
            },
        )


def test_tagged_union_msgspec_int_tags() -> None:
    fmt = types.TaggedUnion(
        tag=types.u8,
        fmt_map={
            100: MsgspecIntTagA,
            101: MsgspecIntTagB,
        },
    )

    data_a = encode(MsgspecIntTagA(0x2A), fmt)
    assert data_a == b"\x01\x2a"
    assert decode(data_a, fmt) == MsgspecIntTagA(0x2A)

    data_b = encode(MsgspecIntTagB(b"hi"), fmt)
    assert data_b == b"\x02hi"
    assert decode(data_b, fmt) == MsgspecIntTagB(b"hi")


def test_tagged_union_type_tag_mapping_input_with_inner_tag() -> None:
    fmt = types.TaggedUnion(
        tag=types.Str(3),
        fmt_map={
            100: MsgspecU16,
            101: MsgspecBytes4,
        },
    )

    data = encode({"kind": "u16", "value": 0x1234}, fmt)
    assert data == b"u16\x12\x34"
    assert decode(data, fmt) == MsgspecU16(0x1234)


def test_tagged_union_unknown_int_tag_raises_hex() -> None:
    fmt = types.TaggedUnion(
        tag=types.u8,
        fmt_map={
            100: MsgspecIntTagA,
            101: MsgspecIntTagB,
        },
    )

    with pytest.raises(DecodeError, match="Unknown tag: 0x03"):
        decode(b"\x03\x00", fmt)


def test_tagged_union_msgspec_int_tags_ref_dispatch() -> None:
    fmt = {
        "kind": types.u8,
        "body": types.TaggedUnion(
            tag=types.Ref("kind"),
            fmt_map={
                100: MsgspecIntTagA,
                101: MsgspecIntTagB,
            },
        ),
    }

    obj_a = {"kind": 1, "body": MsgspecIntTagA(0x2A)}
    data_a = encode(obj_a, fmt)
    assert data_a == b"\x01\x2a"
    assert decode(data_a, fmt) == obj_a

    obj_b = {"kind": 2, "body": MsgspecIntTagB(b"hi")}
    data_b = encode(obj_b, fmt)
    assert data_b == b"\x02hi"
    assert decode(data_b, fmt) == obj_b


def test_tagged_union_ref_tag_field_autocompute() -> None:
    fmt = {
        "kind": types.Str(3),
        "body": types.TaggedUnion(
            tag=types.Ref("kind"),
            fmt_map={
                100: MsgspecU16,
                101: MsgspecBytes4,
            },
        ),
    }

    obj = {"body": MsgspecU16(0x1234)}

    data = encode(obj, fmt)
    assert data == b"u16\x12\x34"
    assert decode(data, fmt) == {"kind": "u16", **obj}


def test_tagged_union_ref_tag_field_autocompute_int_tags() -> None:
    fmt = {
        "kind": types.u8,
        "body": types.TaggedUnion(
            tag=types.Ref("kind"),
            fmt_map={
                100: MsgspecIntTagA,
                101: MsgspecIntTagB,
            },
        ),
    }

    obj_a = {"body": MsgspecIntTagA(0x2A)}
    data_a = encode(obj_a, fmt)
    assert data_a == b"\x01\x2a"
    assert decode(data_a, fmt) == {"kind": 1, **obj_a}

    obj_b = {"body": MsgspecIntTagB(b"hi")}
    data_b = encode(obj_b, fmt)
    assert data_b == b"\x02hi"
    assert decode(data_b, fmt) == {"kind": 2, **obj_b}
