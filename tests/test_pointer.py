from io import BytesIO

from fmtspec import decode, decode_stream, encode, encode_inspect, types


def test_pointer_roundtrip_with_ref_base() -> None:
    fmt = {
        "base": types.u8,
        "payload": types.Pointer(offset=types.u8, fmt=types.Bytes(3), base=types.Ref("base")),
    }
    obj = {
        "base": 2,
        "payload": types.PointerValue(offset=2, value=b"XYZ"),
    }

    data = encode(obj, fmt)

    assert data == b"\x02\x02\x00\x00XYZ"
    assert decode_stream(BytesIO(data), fmt) == {"base": 2, "payload": b"XYZ"}


def test_pointer_accepts_mapping_encode_value() -> None:
    fmt = {
        "base": types.u8,
        "payload": types.Pointer(offset=types.u8, fmt=types.Bytes(3), base=types.Ref("base")),
    }
    obj = {
        "base": 2,
        "payload": {"offset": 2, "value": b"XYZ"},
    }

    assert encode(obj, fmt) == b"\x02\x02\x00\x00XYZ"


def test_pointer_inspect_exposes_offset_and_value_children() -> None:
    fmt = {
        "base": types.u8,
        "payload": types.Pointer(offset=types.u8, fmt=types.Bytes(3), base=types.Ref("base")),
    }
    obj = {
        "base": 2,
        "payload": types.PointerValue(offset=2, value=b"XYZ"),
    }

    encoded, tree = encode_inspect(obj, fmt)

    assert encoded == b"\x02\x02\x00\x00XYZ"
    assert [child.key for child in tree["payload"].children] == ["offset", "value"]
    assert tree["payload"]["offset"].value == 2
    assert tree["payload"]["value"].value == b"XYZ"
    assert tree["payload"]["value"].offset == 4


def test_pointer_null_offset_returns_null_value() -> None:
    fmt = types.Pointer(offset=types.u8, fmt=types.Bytes(2), allow_null=True, null_value=None)

    assert decode(b"\x00", fmt) is None
    assert encode(types.PointerValue(offset=0, value=b"XX"), fmt) == b"\x00"
