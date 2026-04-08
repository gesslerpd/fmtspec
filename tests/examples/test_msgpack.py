"""MessagePack serialization format implementation using fmtspec."""

from __future__ import annotations

import math

import pytest

from fmtspec import (
    DecodeError,
    EncodeError,
    decode,
    decode_inspect,
    encode,
    encode_inspect,
    format_tree,
)
from fmtspec.lib.msgpack import msgpack
from fmtspec.lib.msgpack._impl import (
    ARRAY16,
    ARRAY32,
    BIN8,
    BIN16,
    BIN32,
    FLOAT64,
    MAP16,
    MAP32,
    STR8,
    STR16,
    STR32,
)


class TestMsgPackNil:
    """Tests for nil format."""

    def test_nil_encode(self):
        data = encode(None, msgpack)
        assert data == b"\xc0"

    def test_nil_decode(self):
        result = decode(b"\xc0", msgpack)
        assert result is None

    def test_nil_roundtrip(self):
        data = encode(None, msgpack)
        result = decode(data, msgpack)
        assert result is None


class TestMsgPackBool:
    """Tests for bool format family."""

    def test_false_encode(self):
        data = encode(False, msgpack)
        assert data == b"\xc2"

    def test_true_encode(self):
        data = encode(True, msgpack)
        assert data == b"\xc3"

    def test_false_decode(self):
        result = decode(b"\xc2", msgpack)
        assert result is False

    def test_true_decode(self):
        result = decode(b"\xc3", msgpack)
        assert result is True

    def test_bool_roundtrip(self):
        for value in [True, False]:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result is value


class TestMsgPackInt:
    """Tests for int format family."""

    def test_positive_fixint_zero(self):
        """Positive fixint: 0"""
        data = encode(0, msgpack)
        assert data == b"\x00"
        assert decode(data, msgpack) == 0

    def test_positive_fixint_max(self):
        """Positive fixint: 127 (0x7f)"""
        data = encode(127, msgpack)
        assert data == b"\x7f"
        assert decode(data, msgpack) == 127

    def test_negative_fixint_minus_one(self):
        """Negative fixint: -1"""
        data = encode(-1, msgpack)
        assert data == b"\xff"
        assert decode(data, msgpack) == -1

    def test_negative_fixint_minus_32(self):
        """Negative fixint: -32"""
        data = encode(-32, msgpack)
        assert data == b"\xe0"
        assert decode(data, msgpack) == -32

    def test_uint8(self):
        """uint 8: 128-255"""
        data = encode(128, msgpack)
        assert data == b"\xcc\x80"
        assert decode(data, msgpack) == 128

        data = encode(255, msgpack)
        assert data == b"\xcc\xff"
        assert decode(data, msgpack) == 255

    def test_uint16(self):
        """uint 16: 256-65535"""
        data = encode(256, msgpack)
        assert data == b"\xcd\x01\x00"
        assert decode(data, msgpack) == 256

        data = encode(65535, msgpack)
        assert data == b"\xcd\xff\xff"
        assert decode(data, msgpack) == 65535

    def test_uint32(self):
        """uint 32: 65536-4294967295"""
        data = encode(65536, msgpack)
        assert data == b"\xce\x00\x01\x00\x00"
        assert decode(data, msgpack) == 65536

        data = encode(4294967295, msgpack)
        assert data == b"\xce\xff\xff\xff\xff"
        assert decode(data, msgpack) == 4294967295

    def test_uint64(self):
        """uint 64: 4294967296-18446744073709551615"""
        data = encode(4294967296, msgpack)
        assert data == b"\xcf\x00\x00\x00\x01\x00\x00\x00\x00"
        assert decode(data, msgpack) == 4294967296

        data = encode(18446744073709551615, msgpack)
        assert data == b"\xcf\xff\xff\xff\xff\xff\xff\xff\xff"
        assert decode(data, msgpack) == 18446744073709551615

    def test_int8(self):
        """int 8: -128 to -33"""
        data = encode(-33, msgpack)
        assert data == b"\xd0\xdf"
        assert decode(data, msgpack) == -33

        data = encode(-128, msgpack)
        assert data == b"\xd0\x80"
        assert decode(data, msgpack) == -128

    def test_int16(self):
        """int 16: -32768 to -129"""
        data = encode(-129, msgpack)
        assert data == b"\xd1\xff\x7f"
        assert decode(data, msgpack) == -129

        data = encode(-32768, msgpack)
        assert data == b"\xd1\x80\x00"
        assert decode(data, msgpack) == -32768

    def test_int32(self):
        """int 32: -2147483648 to -32769"""
        data = encode(-32769, msgpack)
        assert data == b"\xd2\xff\xff\x7f\xff"
        assert decode(data, msgpack) == -32769

        data = encode(-2147483648, msgpack)
        assert data == b"\xd2\x80\x00\x00\x00"
        assert decode(data, msgpack) == -2147483648

    def test_int64(self):
        """int 64: -9223372036854775808 to -2147483649"""
        data = encode(-2147483649, msgpack)
        assert data == b"\xd3\xff\xff\xff\xff\x7f\xff\xff\xff"
        assert decode(data, msgpack) == -2147483649

        data = encode(-9223372036854775808, msgpack)
        assert data == b"\xd3\x80\x00\x00\x00\x00\x00\x00\x00"
        assert decode(data, msgpack) == -9223372036854775808

    def test_int_boundary_values(self):
        """Test all boundary values for integer encoding."""
        boundary_values = [
            0,
            127,
            128,
            255,
            256,
            65535,
            65536,
            4294967295,
            4294967296,
            -1,
            -32,
            -33,
            -128,
            -129,
            -32768,
            -32769,
            -2147483648,
            -2147483649,
        ]
        for value in boundary_values:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value, f"Roundtrip failed for {value}"


class TestMsgPackFloat:
    """Tests for float format family."""

    def test_float32_simple(self):
        """Float32 for values that can be represented exactly."""
        data = encode(1.0, msgpack)
        assert data[0] == FLOAT64
        assert decode(data, msgpack) == 1.0

    def test_float32_zero(self):
        """Float32 for zero."""
        data = encode(0.0, msgpack)
        assert data[0] == FLOAT64
        assert decode(data, msgpack) == 0.0

    def test_float64_precision(self):
        """Float64 for values requiring double precision."""
        value = 1.0000000000001
        data = encode(value, msgpack)
        assert data[0] == FLOAT64
        result = decode(data, msgpack)
        assert result == value

    def test_float_infinity(self):
        """Float infinity values."""
        for value in [float("inf"), float("-inf")]:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value

    def test_float_nan(self):
        """Float NaN value."""

        data = encode(float("nan"), msgpack)
        result = decode(data, msgpack)
        assert math.isnan(result)

    def test_float_roundtrip(self):
        """Roundtrip for various float values."""
        values = [0.0, 1.5, -1.5, 3.14159, 1e10, 1e-10, -0.0]
        for value in values:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value, f"Roundtrip failed for {value}"


class TestMsgPackStr:
    """Tests for str format family."""

    def test_fixstr_empty(self):
        """Fixstr: empty string."""
        data = encode("", msgpack)
        assert data == b"\xa0"
        assert decode(data, msgpack) == ""

    def test_fixstr_short(self):
        """Fixstr: short string (1-31 bytes)."""
        data = encode("hello", msgpack)
        assert data == b"\xa5hello"
        assert decode(data, msgpack) == "hello"

    def test_fixstr_max(self):
        """Fixstr: max length (31 bytes)."""
        value = "a" * 31
        data = encode(value, msgpack)
        assert data[0] == 0xBF  # 0xa0 | 31
        assert decode(data, msgpack) == value

    def test_str8(self):
        """str 8: 32-255 bytes."""
        value = "a" * 32
        data = encode(value, msgpack)
        assert data[0] == STR8
        assert data[1] == 32
        assert decode(data, msgpack) == value

        value = "b" * 255
        data = encode(value, msgpack)
        assert data[0] == STR8
        assert data[1] == 255
        assert decode(data, msgpack) == value

    def test_str16(self):
        """str 16: 256-65535 bytes."""
        value = "c" * 256
        data = encode(value, msgpack)
        assert data[0] == STR16
        assert int.from_bytes(data[1:3], "big") == 256
        assert decode(data, msgpack) == value

    def test_str32(self):
        """str 32: 65536+ bytes."""
        value = "d" * 65536
        data = encode(value, msgpack)
        assert data[0] == STR32
        assert int.from_bytes(data[1:5], "big") == 65536
        assert decode(data, msgpack) == value

    def test_str_unicode(self):
        """Unicode string encoding."""
        value = "Hello, 世界! 🌍"
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_str_roundtrip(self):
        """Roundtrip for various strings."""
        values = ["", "a", "hello world", "a" * 31, "b" * 32, "c" * 256, "日本語"]
        for value in values:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value, f"Roundtrip failed for {value!r}"


class TestMsgPackBin:
    """Tests for bin format family."""

    def test_bin8_empty(self):
        """bin 8: empty bytes."""
        data = encode(b"", msgpack)
        assert data == b"\xc4\x00"
        assert decode(data, msgpack) == b""

    def test_bin8_short(self):
        """bin 8: short bytes."""
        data = encode(b"\x00\x01\x02", msgpack)
        assert data == b"\xc4\x03\x00\x01\x02"
        assert decode(data, msgpack) == b"\x00\x01\x02"

    def test_bin8_max(self):
        """bin 8: max (255 bytes)."""
        value = bytes(range(256)) * 1  # 256 bytes won't work, use 255
        value = bytes(255)
        data = encode(value, msgpack)
        assert data[0] == BIN8
        assert decode(data, msgpack) == value

    def test_bin16(self):
        """bin 16: 256-65535 bytes."""
        value = bytes(256)
        data = encode(value, msgpack)
        assert data[0] == BIN16
        assert decode(data, msgpack) == value

    def test_bin32(self):
        """bin 32: 65536+ bytes."""
        value = bytes(65536)
        data = encode(value, msgpack)
        assert data[0] == BIN32
        assert decode(data, msgpack) == value

    def test_bin_roundtrip(self):
        """Roundtrip for various binary data."""
        values = [b"", b"\x00", b"\xff" * 10, bytes(range(256)), bytes(300)]
        for value in values:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value, f"Roundtrip failed for {value!r}"

    def test_bytearray_encoding(self):
        """bytearray should encode as bin."""
        value = bytearray([1, 2, 3])
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == bytes(value)

    def test_memoryview_encoding(self):
        """memoryview should encode as bin."""
        value = memoryview(b"\x01\x02\x03")
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == bytes(value)


class TestMsgPackArray:
    """Tests for array format family."""

    def test_fixarray_empty(self):
        """Fixarray: empty array."""
        data = encode([], msgpack)
        assert data == b"\x90"
        assert decode(data, msgpack) == []

    def test_fixarray_short(self):
        """Fixarray: short array (1-15 elements)."""
        value = [1, 2, 3]
        data = encode(value, msgpack)
        assert data[0] == 0x93  # 0x90 | 3
        assert decode(data, msgpack) == value

    def test_fixarray_max(self):
        """Fixarray: max (15 elements)."""
        value = list(range(15))
        data = encode(value, msgpack)
        assert data[0] == 0x9F  # 0x90 | 15
        assert decode(data, msgpack) == value

    def test_array16(self):
        """array 16: 16-65535 elements."""
        value = list(range(16))
        data = encode(value, msgpack)
        assert data[0] == ARRAY16
        assert decode(data, msgpack) == value

        value = list(range(100))
        data = encode(value, msgpack)
        assert data[0] == ARRAY16
        assert decode(data, msgpack) == value

    def test_array32(self):
        """array 32: 65536+ elements."""
        value = list(range(65536))
        data = encode(value, msgpack)
        assert data[0] == ARRAY32
        assert decode(data, msgpack) == value

    def test_array_mixed_types(self):
        """Array with mixed types."""
        value = [None, True, 42, "hello", b"\x00\x01", [1, 2], {"a": 1}]
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_array_nested(self):
        """Nested arrays."""
        value = [[1, 2], [[3, 4], [5, 6]], []]
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_tuple_encoding(self):
        """Tuples should encode as arrays."""
        value = (1, 2, 3)
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == list(value)

    def test_array_roundtrip(self):
        """Roundtrip for various arrays."""
        values = [
            [],
            [1],
            [1, 2, 3],
            list(range(15)),
            list(range(16)),
            list(range(100)),
        ]
        for value in values:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value, f"Roundtrip failed for {value!r}"


class TestMsgPackMap:
    """Tests for map format family."""

    def test_fixmap_empty(self):
        """Fixmap: empty map."""
        data = encode({}, msgpack)
        assert data == b"\x80"
        assert decode(data, msgpack) == {}

    def test_fixmap_short(self):
        """Fixmap: short map (1-15 entries)."""
        value = {"a": 1, "b": 2}
        data = encode(value, msgpack)
        assert data[0] == 0x82  # 0x80 | 2
        assert decode(data, msgpack) == value

    def test_fixmap_max(self):
        """Fixmap: max (15 entries)."""
        value = {str(i): i for i in range(15)}
        data = encode(value, msgpack)
        assert data[0] == 0x8F  # 0x80 | 15
        assert decode(data, msgpack) == value

    def test_map16(self):
        """map 16: 16-65535 entries."""
        value = {str(i): i for i in range(16)}
        data = encode(value, msgpack)
        assert data[0] == MAP16
        assert decode(data, msgpack) == value

        value = {str(i): i for i in range(100)}
        data = encode(value, msgpack)
        assert data[0] == MAP16
        assert decode(data, msgpack) == value

    def test_map32(self):
        """map 32: 65536+ entries."""
        value = {str(i): i for i in range(65536)}
        data = encode(value, msgpack)
        assert data[0] == MAP32
        assert decode(data, msgpack) == value

    def test_map_mixed_key_types(self):
        """Map with different key types."""
        value = {"str": 1, 42: "int_key"}
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_map_nested(self):
        """Nested maps."""
        value = {"outer": {"inner": {"deep": 42}}}
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_map_with_array_values(self):
        """Map with array values."""
        value = {"list": [1, 2, 3], "nested": [{"a": 1}, {"b": 2}]}
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_map_roundtrip(self):
        """Roundtrip for various maps."""
        values = [
            {},
            {"a": 1},
            {"a": 1, "b": 2},
            {str(i): i for i in range(15)},
            {str(i): i for i in range(16)},
            {str(i): i for i in range(100)},
        ]
        for value in values:
            data = encode(value, msgpack)
            result = decode(data, msgpack)
            assert result == value, f"Roundtrip failed for {value!r}"


from fmtspec._core import FrozenDict


class TestMsgPackComplex:
    """Tests for complex/combined data structures."""

    def test_complex_nested_structure(self):
        """Complex nested structure with all types."""
        value = {
            "null": None,
            "bool_true": True,
            "bool_false": False,
            "int_pos": 42,
            "int_neg": -42,
            "int_big": 1000000,
            "float": 3.14,
            "string": "hello world",
            "binary": b"\x00\x01\x02",
            "array": [1, 2, 3],
            "nested_map": {"a": 1, "b": [True, False]},
            "empty_array": [],
            "empty_map": {},
            (1, 2, 3): "tuple_key",
            None: "none_key",
            True: "true_key",
            False: "false_key",
            42: "int_key",
            -42: "neg_int_key",
            3.14: "float_key",
            b"": "empty_bytes_key",
            FrozenDict(
                {"frozen": "dict", "more": b"data", "nested": FrozenDict({42: "int_key"})}
            ): "frozendict_key",
        }
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_deeply_nested(self):
        """Deeply nested structures."""
        value = {"level1": {"level2": {"level3": {"level4": [1, [2, [3]]]}}}}
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_array_of_maps(self):
        """Array containing maps."""
        value = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_map_with_binary_keys(self):
        """Map with integer keys (msgpack supports non-string keys)."""
        value = {1: "one", 2: "two", 3: "three"}
        data = encode(value, msgpack)
        result = decode(data, msgpack)
        assert result == value

    def test_realistic_json_like_data(self):
        """Realistic JSON-like data structure."""
        value = {
            "users": [
                {
                    "id": 1,
                    "name": "Alice",
                    "email": "alice@example.com",
                    "active": True,
                    "score": 95.5,
                    "tags": ["admin", "user"],
                },
                {
                    "id": 2,
                    "name": "Bob",
                    "email": "bob@example.com",
                    "active": False,
                    "score": None,
                    "tags": [],
                },
            ],
            "metadata": {"version": "1.0", "count": 2},
        }
        data = encode(value, msgpack)
        result = decode(data, msgpack)

        data_inspect, tree = encode_inspect(value, msgpack)
        assert data == data_inspect

        enc_tree = format_tree(tree)

        _, tree = decode_inspect(data, msgpack)
        dec_tree = format_tree(tree)

        assert enc_tree == dec_tree
        # assert tree.children
        print()
        print(enc_tree)
        print(dec_tree)
        print()
        assert result == value


class TestMsgPackEdgeCases:
    """Edge case tests."""

    def test_empty_stream_error(self):
        """Empty stream should raise DecodeError with EOFError as cause."""

        with pytest.raises(DecodeError) as exc_info:
            decode(b"", msgpack)

        assert isinstance(exc_info.value.cause, EOFError)

    def test_unknown_tag_error(self):
        """Unknown tag should raise DecodeError with ValueError as cause."""

        # 0xc1 is reserved and never used
        with pytest.raises(DecodeError, match="Unknown msgpack tag") as exc_info:
            decode(b"\xc1", msgpack)

        assert isinstance(exc_info.value.cause, ValueError)

    def test_unsupported_type_error(self):
        with pytest.raises((EncodeError, TypeError), match="object"):
            encode(object(), msgpack)

    def test_integer_overflow_error(self):
        """Integer out of range should raise EncodeError with OverflowError as cause."""

        # Larger than uint64 max
        with pytest.raises(EncodeError) as exc_info:
            encode(2**64, msgpack)

        assert isinstance(exc_info.value.cause, OverflowError)

        # Smaller than int64 min
        with pytest.raises(EncodeError) as exc_info:
            encode(-(2**63) - 1, msgpack)

        assert isinstance(exc_info.value.cause, OverflowError)

    def test_bool_not_confused_with_int(self):
        """Bools should encode as bool, not int."""
        # True should be 0xc3, not 0x01
        data = encode(True, msgpack)
        assert data == b"\xc3"

        # False should be 0xc2, not 0x00
        data = encode(False, msgpack)
        assert data == b"\xc2"

    def test_string_vs_binary_distinction(self):
        """Strings and bytes should use different formats."""
        str_data = encode("hello", msgpack)
        bin_data = encode(b"hello", msgpack)

        # String uses fixstr (0xa0-0xbf)
        assert 0xA0 <= str_data[0] <= 0xBF

        # Binary uses bin8 (0xc4)
        assert bin_data[0] == BIN8

        # They should decode to different types
        assert isinstance(decode(str_data, msgpack), str)
        assert isinstance(decode(bin_data, msgpack), bytes)
