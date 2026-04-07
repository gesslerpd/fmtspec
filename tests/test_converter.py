from __future__ import annotations

from io import BytesIO

import pytest

from fmtspec import DecodeError, EncodeError, decode, decode_inspect, decode_stream, encode, types
from fmtspec.types._converter import Converter, scale


def test_transform_roundtrip() -> None:
    fmt = Converter(types.u8, decode_fn=lambda raw: raw + 1, encode_fn=lambda value: value - 1)

    assert encode(6, fmt) == b"\x05"
    assert decode(b"\x05", fmt) == 6


def test_transform_preserves_inner_size() -> None:
    assert Converter(types.u16).size == 2


def test_transform_ref_fmt_has_dynamic_size() -> None:
    assert Converter(types.Ref("kind")).size is ...


def test_transform_composes_inside_mapping() -> None:
    fmt = {
        "count": Converter(
            types.u8, decode_fn=lambda raw: raw + 10, encode_fn=lambda value: value - 10
        )
    }

    assert encode({"count": 15}, fmt) == b"\x05"
    assert decode(b"\x05", fmt) == {"count": 15}


def test_transform_decode_inspect_keeps_semantic_and_wire_values() -> None:
    fmt = Converter(types.u8, decode_fn=lambda raw: raw + 1)

    value, tree = decode_inspect(b"\x05", fmt)

    assert value == 6
    assert tree.value == 6
    assert len(tree.children) == 1
    assert tree.children[0].value == 5


def test_transform_encode_errors_are_wrapped() -> None:
    fmt = Converter(types.u8, encode_fn=lambda value: value["missing"])

    with pytest.raises(EncodeError) as exc_info:
        encode({}, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_transform_decode_errors_are_wrapped() -> None:
    fmt = Converter(types.u8, decode_fn=lambda _raw: (_ for _ in ()).throw(ValueError("boom")))

    with pytest.raises(DecodeError) as exc_info:
        decode(b"\x05", fmt)

    assert isinstance(exc_info.value.cause, ValueError)


def test_converter_supports_ref_based_fmt_encode_and_decode() -> None:
    fmt = {
        "wide": types.u8,
        "value": Converter(
            types.Ref("wide", cast=lambda wide: types.u16 if wide else types.u8),
        ),
    }

    assert encode({"wide": 0, "value": 5}, fmt) == b"\x00\x05"
    assert decode(b"\x00\x05", fmt) == {"wide": 0, "value": 5}

    assert encode({"wide": 1, "value": 300}, fmt) == b"\x01\x01\x2c"
    assert decode(b"\x01\x01\x2c", fmt) == {"wide": 1, "value": 300}


def test_converter_ref_fmt_missing_key_is_wrapped_on_encode() -> None:
    fmt = {
        "value": Converter(types.Ref("bad")),
    }

    with pytest.raises(EncodeError) as exc_info:
        encode({"value": 8}, fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_converter_ref_fmt_missing_key_is_wrapped_on_decode() -> None:
    fmt = {
        "value": Converter(types.Ref("bad")),
    }

    with pytest.raises(DecodeError) as exc_info:
        decode(b"\x05", fmt)

    assert isinstance(exc_info.value.cause, KeyError)


def test_scale_converter_roundtrip() -> None:
    fmt = scale(types.u8, 4)

    assert encode(12, fmt) == b"\x03"
    assert decode(b"\x03", fmt) == 12


def test_scale_converter_requires_exact_division_on_encode() -> None:
    fmt = scale(types.u8, 4)

    assert encode(4, fmt) == b"\x01"


def test_scale_converter_rejects_non_positive_factors() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        scale(types.u8, 0)

    with pytest.raises(ValueError, match="positive integer"):
        scale(types.u8, -1)


def test_scale_converter_with_sized_length_field() -> None:
    fmt = types.Sized(length=scale(types.u8, 2), fmt=types.Bytes())

    assert encode(b"abcd", fmt) == b"\x02abcd"
    assert decode(b"\x02abcd", fmt) == b"abcd"


def test_scale_converter_with_sized_length_field_requires_exact_division() -> None:
    fmt = types.Sized(length=scale(types.u8, 2), fmt=types.Bytes())

    assert encode(b"abc", fmt) == b"\x01abc"


@pytest.mark.parametrize("payload", [b"", b"ab", b"abcd", b"abcdef"])
def test_scale_converter_with_sized_length_field_roundtrips_even_lengths(payload: bytes) -> None:
    fmt = types.Sized(length=scale(types.u8, 2), fmt=types.Bytes())

    encoded = encode(payload, fmt)

    assert decode(encoded, fmt) == payload


def test_scale_converter_with_sized_length_field_in_mapping_roundtrips() -> None:
    fmt = {
        "payload": types.Sized(length=scale(types.u8, 2), fmt=types.Bytes()),
        "tail": types.u8,
    }
    obj = {"payload": b"abcd", "tail": 7}

    encoded = encode(obj, fmt)

    assert encoded == b"\x02abcd\x07"
    assert decode(encoded, fmt) == obj


def test_scale_converter_with_sized_length_field_decodes_semantic_length_in_inspect_tree() -> None:
    fmt = types.Sized(length=scale(types.u8, 2), fmt=types.Bytes())

    value, tree = decode_inspect(b"\x02abcd", fmt)

    assert value == b"abcd"
    assert len(tree.children) == 3
    assert tree.children[0].value == 2
    assert tree.children[1].key == "--size--"
    assert tree.children[1].value == 4


def test_scale_converter_with_sized_length_field_decode_stream_leaves_trailing_bytes() -> None:
    fmt = types.Sized(length=scale(types.u8, 2), fmt=types.Bytes())
    stream = BytesIO(b"\x01abc")

    assert decode_stream(stream, fmt) == b"ab"
    assert stream.read() == b"c"
