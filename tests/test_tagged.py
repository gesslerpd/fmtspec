from dataclasses import dataclass
from typing import Annotated

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, types


@dataclass
class DataclassExample:
    value: Annotated[int, types.u8]
    name: Annotated[str, types.String(4)]


def test_tagged_union() -> None:
    fmt = types.TaggedUnion(
        tag=types.u8,
        fmt_map={
            0: DataclassExample,
            1: Annotated[int, types.u16],
            2: Annotated[bytes, types.Bytes(4)],
        },
    )
    obj = DataclassExample(42, "test")

    data = encode(obj, fmt)
    assert data == b"\x00\x2a\x74\x65\x73\x74"

    result = decode(data, fmt)
    assert encode(result, fmt) == data

    obj = 0x1234

    data = encode(obj, fmt)
    assert data == b"\x01\x12\x34"

    result = decode(data, fmt)
    assert encode(result, fmt) == data

    obj = b"test"

    data = encode(obj, fmt)
    assert data == b"\x02test"

    result = decode(data, fmt)
    assert encode(result, fmt) == data

    with pytest.raises(EncodeError, match="Unknown type"):
        encode("string", fmt)

    with pytest.raises(DecodeError, match="Unknown tag"):
        decode(b"\xffexcess", fmt)
