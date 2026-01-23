from dataclasses import dataclass
from enum import IntEnum, IntFlag, auto
from typing import Annotated

import pytest

from fmtspec import DecodeError, EncodeError, decode, encode, sizeof
from fmtspec.types import Bitfield, Bitfields, u16


def test_bitfield_basic():
    """Test basic bitfield encoding/decoding."""
    bitfield = Bitfields(
        size=1,
        fields={
            "field": Bitfield(bits=8),
        },
    )

    # Should be 1 byte
    assert bitfield.size == 1

    value = {"field": 0xAB}
    data = encode(value, bitfield)

    assert data == b"\xab"

    result = decode(data, bitfield)
    assert result == value


def test_bitfield_with_offset():
    """Test bitfield with offset."""
    bitfield = Bitfields(
        size=1,
        fields={
            "field": Bitfield(bits=4, offset=4),
        },
    )

    # Should be 1 byte
    assert bitfield.size == 1

    value = {"field": 10}  # 0b1010
    data = encode(value, bitfield)

    # value << 4 = 0b10100000 = 0xA0
    assert data == b"\xa0"

    result = decode(data, bitfield)
    assert result == value


def test_bitfield_small():
    """Test small bitfield."""
    bitfield = Bitfields(
        size=1,
        fields={
            "field": Bitfield(bits=1, offset=0),
        },
    )

    assert bitfield.size == 1

    value = {"field": True}
    data = encode(value, bitfield)

    assert data == b"\x01"

    result = decode(data, bitfield)
    assert result == value


SPARSE_BITFIELDS_FMT = Bitfields(
    fields={
        "bit0": Bitfield(bits=1),
        # [1:6] index bits are gaps (exclusive)
        "end_bits": Bitfield(bits=2, offset=6),
    },
)


def test_auto_size():
    bitfield = Bitfields(
        fields={
            "field1": Bitfield(bits=3),
            "field2": Bitfield(bits=5),
        },
    )

    # 3 + 5 = 8 bits -> 1 byte
    assert bitfield.size == 1

    bitfield2 = Bitfields(
        fields={
            "field1": Bitfield(bits=10),
            "field2": Bitfield(bits=10),
        },
    )

    # 10 + 10 = 20 bits -> 3 bytes
    assert bitfield2.size == 4

    bitfield3 = Bitfields(
        fields={
            "field1": Bitfield(bits=20),
            "field2": Bitfield(bits=1, offset=63),
        },
    )
    assert bitfield3.size == 8


def test_sparse():
    obj = {
        "bit0": 1,
        "end_bits": 0b11,
    }
    data = encode(obj, SPARSE_BITFIELDS_FMT)

    # Binary: 0b11_00000_1
    assert data == b"\xc1"

    result = decode(data, SPARSE_BITFIELDS_FMT)
    assert result == obj


def test_tcp_flags():
    """Demonstrate TCP segment flags packed into a single byte."""
    tcp_flags = Bitfields(
        size=1,
        fields={
            # "fin": Bitfield(bits=1),
            "syn": Bitfield(bits=1, offset=1),
            "rst": Bitfield(bits=1),
            # "psh": Bitfield(bits=1),
            "ack": Bitfield(bits=1, offset=4),
            # "urg": Bitfield(bits=1),
            # "ece": Bitfield(bits=1),
            # "cwr": Bitfield(bits=1),
        },
    )

    flags = {
        # "fin": 0,
        "syn": 1,
        "rst": 1,
        "ack": 1,
    }

    data = encode(flags, tcp_flags)

    # TCP header from scapy with SYN, RST, ACK set `TCP(flags="SRA")`
    header_data = bytes.fromhex("0014005000000000000000005016200000000000")
    assert data == header_data[13:14]

    result = decode(data, tcp_flags)
    assert result == flags


def test_bitfield_invalid_bits():
    """Test that Bitfield rejects non-positive bits values."""
    with pytest.raises(ValueError, match="bits must be positive"):
        Bitfield(bits=0)

    with pytest.raises(ValueError, match="bits must be positive"):
        Bitfield(bits=-1)


def test_bitfield_invalid_offset():
    """Test that Bitfield rejects negative offset values."""
    with pytest.raises(ValueError, match="offset must be non-negative"):
        Bitfield(bits=1, offset=-1)


def test_bitfields_invalid_size():
    """Test that Bitfields rejects non-positive size values."""
    with pytest.raises(ValueError, match="Unsupported size"):
        Bitfields(size=9, fields={})

    with pytest.raises(ValueError, match="Unsupported size"):
        Bitfields(size=-1, fields={})


def test_bitfields_overlapping_offsets():
    """Test detection of overlapping bitfield offsets."""
    with pytest.raises(ValueError, match="Bitfield offsets overlap"):
        Bitfields(
            size=1,
            fields={
                "field1": Bitfield(bits=4, offset=0),
                "field2": Bitfield(bits=4, offset=2),  # overlaps with field1
            },
        )


def test_bitfields_exceeds_size():
    """Test that bitfields exceeding total size are rejected."""
    with pytest.raises(ValueError, match="Bitfield exceeds total size"):
        Bitfields(
            size=1,  # 8 bits
            fields={
                "field1": Bitfield(bits=4, offset=0),
                "field2": Bitfield(bits=5, offset=4),  # 4 + 5 = 9 > 8
            },
        )


def test_bitfields_auto_offset_exceeds_size():
    """Test auto-calculated offsets that exceed size."""
    with pytest.raises(ValueError, match="Bitfield exceeds total size"):
        Bitfields(
            size=1,  # 8 bits
            fields={
                "field1": Bitfield(bits=4),  # offset=0, bits=4
                "field2": Bitfield(bits=5),  # offset=4, 4+5=9 > 8
            },
        )

    Bitfields(
        size=2,  # 16 bits
        fields={
            "field1": Bitfield(bits=4),  # offset=0, bits=4
            "field2": Bitfield(bits=5),  # offset=4, 4+5=9 > 8
        },
    )


def test_encode_missing_field():
    """Test encoding with missing required fields."""
    bitfield = Bitfields(
        size=1,
        fields={
            "field1": Bitfield(bits=3, offset=1),
            "field2": Bitfield(bits=4),
        },
    )

    with pytest.raises(EncodeError, match="Missing field 'field2'"):
        encode({"field1": 1}, bitfield)


def test_encode_invalid_value_type():
    """Test encoding with non-integer values."""
    bitfield = Bitfields(
        size=1,
        fields={
            "field": Bitfield(bits=1),
        },
    )

    with pytest.raises(EncodeError, match="not supported between instances"):
        encode({"field": "not_an_int"}, bitfield)


def test_encode_value_out_of_range():
    """Test encoding with values outside bitfield range."""
    bitfield = Bitfields(
        size=1,
        fields={
            "field": Bitfield(bits=2),  # range 0-3
        },
    )

    with pytest.raises(EncodeError, match="Value 4 for field 'field' out of range"):
        encode({"field": 4}, bitfield)

    with pytest.raises(EncodeError, match="Value -1 for field 'field' out of range"):
        encode({"field": -1}, bitfield)


def test_decode_insufficient_data():
    """Test decoding with insufficient bytes."""
    bitfield = Bitfields(
        size=2,  # expects 2 bytes
        fields={
            "field": Bitfield(bits=8),
        },
    )

    with pytest.raises(DecodeError, match="Expected 2 bytes, got 1"):
        decode(b"\x00", bitfield)


class Permissions(IntFlag):
    READ = auto()
    WRITE = auto()
    EXECUTE = auto()


class Integers(IntEnum):
    ONE = 1
    TWO = 2


@dataclass
class Struct:
    first: Annotated[int, u16]
    flag: Annotated[bool, Bitfield(bits=1, align=2)]  # [0:1] index bit (exclusive)
    other_flag: Annotated[Permissions, Bitfield(bits=3, offset=4)]  # [4:7] index bits (exclusive)


def test_bitfield_dataclass():
    obj = Struct(
        first=0x1234,
        flag=True,
        other_flag=Permissions.EXECUTE,
    )
    data = encode(obj)

    assert data == b"\x12\x34\x00\x41"

    result = decode(data, shape=Struct)
    assert result == obj


MIXED_BITFIELDS_FMT = {
    "first": u16,
    "flag": Bitfield(bits=1, offset=0),  # [0:1] index bit (exclusive)
    "other_flag": Bitfield(bits=3, offset=4),  # [4:7] index bits (exclusive)
    "mid": u16,
    "flag2": Bitfield(bits=1),  # [0:1] index bit (exclusive)
    "other_flag2": Bitfield(bits=3, offset=12),  # [4:7] index bits (exclusive)
    "last": u16,
}


def test_bitfield_mixed():
    obj = {
        "first": 0x1234,
        "flag": Integers.ONE,
        "other_flag": 5,
        "mid": 0x5678,
        "flag2": 1,
        "other_flag2": 6,
        "last": 0xABCD,
    }
    data = encode(obj, MIXED_BITFIELDS_FMT)

    assert data == b"\x12\x34\x51\x56\x78\x60\x01\xab\xcd"

    result = decode(data, MIXED_BITFIELDS_FMT)
    assert result == obj


def test_bitfield_align_starts_sized_group():
    fmt = {
        "head": u16,
        "a": Bitfield(bits=4, align=8),
        "b": Bitfield(bits=4),
        "c": Bitfield(bits=8, align=1),
        "d": Bitfield(bits=4, align=1),
        "tail": u16,
    }

    obj = {"head": 0x1234, "a": 0xA, "b": 0xB, "c": 0xFF, "d": 0xF, "tail": 0x5678}
    data = encode(obj, fmt)

    assert data == b"\x12\x34\x00\x00\x00\x00\x00\x00\x00\xba\xff\x0f\x56\x78"

    result = decode(data, fmt)
    assert result == obj


def test_bitfields_align_direct():
    bf = Bitfields(
        fields={
            "a": Bitfield(bits=4, align=2),
            "b": Bitfield(bits=4),
        }
    )

    assert bf.size == 2

    obj = {"a": 0xA, "b": 0xB}
    data = encode(obj, bf)

    # a occupies low 4 bits, b occupies next 4 bits -> 0xBA
    assert data == b"\x00\xba"

    result = decode(data, bf)
    assert result == obj


def test_bitfields_multi_align_direct():
    bf = Bitfields(
        fields={
            "a": Bitfield(bits=9, align=8),
            "b": Bitfield(bits=4, offset=16),
            "c": Bitfield(bits=4),
        }
    )

    # real size is 4 but forced to align of 8
    assert bf.size == 8

    obj = {"a": 0b1, "b": 0b1, "c": 0b1}
    data = encode(obj, bf)

    assert data == bytes(
        [
            0b00000000,
            0b00000000,
            0b00000000,
            0b00000000,
            0b00000000,
            0b00010001,
            0b00000000,
            0b00000001,
        ]
    )

    result = decode(data, bf)
    assert result == obj


def test_bitfield_direct():
    bf = Bitfield(bits=3)

    assert bf.size == sizeof(bf) == 1

    obj = Permissions.READ | Permissions.WRITE | Permissions.EXECUTE
    data = encode(obj, bf)

    assert data == b"\x07"

    result = decode(data, bf)
    assert result == obj

    with pytest.raises(EncodeError, match="Value 8 for field '' out of range"):
        encode(obj + 1, bf)


def test_bitfield_direct_aligned():
    bf = Bitfield(bits=3, offset=9, align=2)

    assert bf.size == sizeof(bf) == 2

    obj = Permissions.READ | Permissions.WRITE | Permissions.EXECUTE
    data = encode(obj, bf)

    assert data == b"\x0e\x00"

    result = decode(data, bf)
    assert result == obj

    with pytest.raises(EncodeError, match="Value 8 for field '' out of range"):
        encode(obj + 1, bf)

    bf = Bitfield(bits=3, offset=9)

    assert bf.size == sizeof(bf) == 2


def test_align_on_non_first_field_raises() -> None:
    """Using `align` on a non-first field in an auto-placement group should fail."""
    with pytest.raises(
        ValueError, match="Bitfield align is only allowed on the first field of a group"
    ):
        Bitfields(
            fields={
                "a": Bitfield(bits=1),
                "b": Bitfield(bits=1, align=2),
            }
        )


def test_forced_align_group_size_exceeded() -> None:
    """A forced-align group whose total bits exceed the aligned size should fail."""
    with pytest.raises(ValueError, match="Bitfield exceeds forced align group size"):
        Bitfields(
            fields={
                "a": Bitfield(bits=5, align=1),  # forced_bits = 8
                "b": Bitfield(bits=4),
            }
        )
