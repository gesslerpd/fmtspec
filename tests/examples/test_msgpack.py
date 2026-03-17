"""MessagePack serialization format implementation using fmtspec.

Implements the full MessagePack specification except Extensions.
https://github.com/msgpack/msgpack/blob/master/spec.md

Supported types:
- nil: None
- bool: True/False
- int: positive fixint, negative fixint, uint 8/16/32/64, int 8/16/32/64
- float: float 32/64
- str: fixstr, str 8/16/32
- bin: bin 8/16/32
- array: fixarray, array 16/32
- map: fixmap, map 16/32
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import NoneType
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Literal, Self

import pytest

from fmtspec import (
    Context,
    DecodeError,
    EncodeError,
    decode,
    decode_inspect,
    encode,
    encode_inspect,
    format_tree,
    types,
)

if TYPE_CHECKING:
    from types import EllipsisType


# =============
# Tag Constants
# =============
FLOAT32 = 0xCA
FLOAT64 = 0xCB
STR8 = 0xD9
STR16 = 0xDA
STR32 = 0xDB
BIN8 = 0xC4
BIN16 = 0xC5
BIN32 = 0xC6
ARRAY16 = 0xDC
ARRAY32 = 0xDD
MAP16 = 0xDE
MAP32 = 0xDF


# =============================================================================
# Primitive Type Instances (composed from fmtspec.types)
# =============================================================================

# Length-prefixed string/binary body formats (after the tag)
str8 = types.Sized(length=types.u8, fmt=types.Str())
str16 = types.Sized(length=types.u16, fmt=types.Str())
str32 = types.Sized(length=types.u32, fmt=types.Str())
bin8 = types.Sized(length=types.u8, fmt=types.Bytes())
bin16 = types.Sized(length=types.u16, fmt=types.Bytes())
bin32 = types.Sized(length=types.u32, fmt=types.Bytes())

# Self-referential format using Lazy
# msgpack_ref = types.Lazy(lambda: msgpack)

# Count-prefixed arrays/maps (after the tag)
# array16 = types.array(msgpack_ref, dims=types.u16)
# array32 = types.array(msgpack_ref, dims=types.u32)
# map16 = types.array((msgpack_ref, msgpack_ref), dims=types.u16)
# map32 = types.array((msgpack_ref, msgpack_ref), dims=types.u32)

# =============================================================================
# Encoding Helpers
# =============================================================================
BYTES = {i: bytes([i]) for i in range(256)}


def _encode_int(value: int, stream: BinaryIO) -> None:
    """Encode integer using smallest representation."""
    # 1-byte encodings (fixint)
    if 0 <= value <= 0x7F:
        stream.write(BYTES[value])  # positive fixint
    elif -0x20 <= value < 0:
        stream.write(BYTES[value & 0xFF])  # negative fixint
    # 2-byte encodings
    elif 0x80 <= value <= 0xFF:
        stream.write(b"\xcc")
        types.u8.encode(value, stream)
    elif -0x80 <= value < -0x20:
        stream.write(b"\xd0")
        types.i8.encode(value, stream)
    # 3-byte encodings
    elif 0x100 <= value <= 0xFFFF:
        stream.write(b"\xcd")
        types.u16.encode(value, stream)
    elif -0x8000 <= value < -0x80:
        stream.write(b"\xd1")
        types.i16.encode(value, stream)
    # 5-byte encodings
    elif 0x10000 <= value <= 0xFFFFFFFF:
        stream.write(b"\xce")
        types.u32.encode(value, stream)
    elif -0x80000000 <= value < -0x8000:
        stream.write(b"\xd2")
        types.i32.encode(value, stream)
    # 9-byte encodings
    elif 0x100000000 <= value <= 0xFFFFFFFFFFFFFFFF:
        stream.write(b"\xcf")
        types.u64.encode(value, stream)
    elif -0x8000000000000000 <= value < -0x80000000:
        stream.write(b"\xd3")
        types.i64.encode(value, stream)
    else:
        raise OverflowError(f"Integer {value} out of msgpack range")


def _encode_str(value: str, stream: BinaryIO, context) -> None:
    """Encode string using smallest representation."""
    data = value.encode("utf-8")
    n = len(data)
    if n <= 31:
        # avoid temporary concatenation
        # fixstr
        stream.write(BYTES[0xA0 | n])
        stream.write(data)
    elif n <= 0xFF:
        stream.write(b"\xd9")
        str8.encode(value, stream, context=context)
    elif n <= 0xFFFF:
        stream.write(b"\xda")
        str16.encode(value, stream, context=context)
    else:
        stream.write(b"\xdb")
        str32.encode(value, stream, context=context)


def _encode_bin(value: bytes, stream: BinaryIO, context) -> None:
    """Encode binary using smallest representation."""
    n = len(value)
    if n <= 0xFF:
        stream.write(b"\xc4")
        bin8.encode(value, stream, context=context)
    elif n <= 0xFFFF:
        stream.write(b"\xc5")
        bin16.encode(value, stream, context=context)
    else:
        stream.write(b"\xc6")
        bin32.encode(value, stream, context=context)


# =============================================================================
# MsgPack Type
# =============================================================================


_FLOAT_BY_TAG = {
    FLOAT32: types.f32,
    FLOAT64: types.f64,
}

_UINT_BY_TAG = {
    0xCC: types.u8,
    0xCD: types.u16,
    0xCE: types.u32,
    0xCF: types.u64,
}

_SINT_BY_TAG = {
    0xD0: types.i8,
    0xD1: types.i16,
    0xD2: types.i32,
    0xD3: types.i64,
}

_STR_BY_TAG = {
    STR8: str8,
    STR16: str16,
    STR32: str32,
}

_BIN_BY_TAG = {
    BIN8: bin8,
    BIN16: bin16,
    BIN32: bin32,
}


@dataclass(frozen=True, slots=True)
class MsgPack:
    """MessagePack serialization format using composed fmtspec.types."""

    size: ClassVar[EllipsisType] = ...  # dynamic size

    float_precision: Literal[4, 8] = 8
    """Float precision to use when encoding floats."""

    array_type: type = list
    map_type: type = dict

    _float_type: types.Float = field(init=False, repr=False, compare=False)
    _float_tag: int = field(init=False, repr=False, compare=False)
    # _map_by_tag: dict[int, types.Array] = field(
    #     init=False, repr=False, compare=False, default_factory=dict
    # )
    # _array_by_tag: dict[int, types.Array] = field(
    #     init=False, repr=False, compare=False, default_factory=dict
    # )
    _keysafe: Self = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        keysafe = self
        if self.array_type is not tuple and self.array_type is not tuple:
            # conditionalize to avoid infinite recursion
            keysafe = self.__class__(
                self.float_precision,
                tuple,
                tuple,
            )
        object.__setattr__(self, "_keysafe", keysafe)
        object.__setattr__(
            self,
            "_float_tag",
            FLOAT32 if self.float_precision == 4 else FLOAT64,
        )
        # will error if float_precision is invalid
        object.__setattr__(
            self,
            "_float_type",
            _FLOAT_BY_TAG[self._float_tag],
        )
        # defer these so they can reference `self`
        # self._map_by_tag[MAP16] = types.array((self._keysafe, self), dims=types.u16)
        # self._map_by_tag[MAP32] = types.array((self._keysafe, self), dims=types.u32)

        # self._array_by_tag[ARRAY16] = types.array(self, dims=types.u16)
        # self._array_by_tag[ARRAY32] = types.array(self, dims=types.u32)

    def encode(self, value: Any, stream: BinaryIO, *, context: Context) -> None:  # noqa: PLR0912
        """Encode a Python value to MessagePack format."""
        # fast checks for performance
        t = type(value)
        if t is NoneType:
            stream.write(b"\xc0")
        elif t is bool:
            stream.write(b"\xc3" if value else b"\xc2")
        elif t is int:
            _encode_int(value, stream)
        elif t is float:
            stream.write(BYTES[self._float_tag])
            self._float_type.encode(value, stream)
        elif t is str:
            _encode_str(value, stream, context)
        elif t is bytes or t is bytearray or t is memoryview:
            _encode_bin(bytes(value), stream, context)
        elif t is list or t is tuple:
            self._encode_array(list(value), stream, context)
        elif t is dict:
            self._encode_map(value, stream, context)

        # slower checks
        elif issubclass(t, NoneType):
            stream.write(b"\xc0")
        elif issubclass(t, bool):
            stream.write(b"\xc3" if value else b"\xc2")
        elif issubclass(t, int):
            _encode_int(value, stream)
        elif issubclass(t, float):
            stream.write(BYTES[self._float_tag])
            self._float_type.encode(value, stream)
        elif issubclass(t, str):
            _encode_str(value, stream, context)
        elif issubclass(t, (bytes, bytearray, memoryview)):
            _encode_bin(bytes(value), stream, context)
        elif issubclass(t, (list, tuple)):
            self._encode_array(list(value), stream, context)
        elif issubclass(t, dict):
            self._encode_map(value, stream, context)
        else:
            raise TypeError(f"Unsupported type for msgpack: {t.__name__}")

    def _encode_array(self, value: list, stream: BinaryIO, context: Context) -> None:
        n = len(value)
        if n <= 15:
            # fixarray
            stream.write(BYTES[0x90 | n])
        elif n <= 0xFFFF:
            stream.write(b"\xdc")
            # self._array_by_tag[ARRAY16].encode(value, stream, context=context)
            # don't use fmtspec.types.array here for performance
            start = stream.tell()
            types.u16.encode(n, stream)
            context.inspect_leaf(stream, "--len--", types.u16, n, start)
        else:
            stream.write(b"\xdd")
            # self._array_by_tag[ARRAY32].encode(value, stream, context=context)
            # don't use fmtspec.types.array here for performance
            start = stream.tell()
            types.u32.encode(n, stream)
            context.inspect_leaf(stream, "--len--", types.u32, n, start)

        for i, item in enumerate(value):
            # context.push_path(i)
            if context.inspect:
                with context.inspect_scope(stream, i, self, item):
                    self.encode(item, stream, context=context)
            else:
                self.encode(item, stream, context=context)
            # context.pop_path()

    def _encode_map(self, value: dict, stream: BinaryIO, context: Context) -> None:
        n = len(value)
        if n <= 15:
            stream.write(BYTES[0x80 | n])
        elif n <= 0xFFFF:
            stream.write(b"\xde")
            # self._map_by_tag[MAP16].encode(value.items(), stream, context=context)
            # don't use fmtspec.types.array here for performance
            start = stream.tell()
            types.u16.encode(n, stream)
            context.inspect_leaf(stream, "--len--", types.u16, n, start)
        else:
            stream.write(b"\xdf")
            # self._map_by_tag[MAP32].encode(value.items(), stream, context=context)
            # don't use fmtspec.types.array here for performance
            start = stream.tell()
            types.u32.encode(n, stream)
            context.inspect_leaf(stream, "--len--", types.u32, n, start)

        # perf: don't use enumerate
        i = 0
        for k, v in value.items():
            # context.push_path(i)
            if context.inspect:
                with context.inspect_scope(stream, i, self, (k, v)):
                    # context.push_path("key")
                    with context.inspect_scope(stream, None, self, k):
                        # don't need self._keysafe on encode
                        self.encode(k, stream, context=context)
                    # context.pop_path()

                    # context.push_path("value")
                    with context.inspect_scope(stream, k, self, v):
                        self.encode(v, stream, context=context)
            else:
                self.encode(k, stream, context=context)
                self.encode(v, stream, context=context)
            # context.pop_path()

            # context.pop_path()
            i += 1

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        """Decode a MessagePack value from stream."""
        b = stream.read(1)
        if not b:
            raise EOFError("Unexpected end of stream")
        tag = b[0]

        result: Any
        if tag <= 0x7F:
            result = tag  # positive fixint
        elif tag <= 0x8F:
            # fixmap
            # don't use fmtspec.types.array for performance
            result = self.map_type(self._decode_map(stream, context, tag & 0x0F))
        elif tag <= 0x9F:
            # fixarray
            # don't use fmtspec.types.array for performance
            result = self.array_type(self._decode_array(stream, context, tag & 0x0F))
        elif tag <= 0xBF:
            # result = types.Str(tag & 0x1F).decode(stream)
            # don't use fmtspec.types.Str for performance
            result = stream.read(tag & 0x1F).decode("utf-8")  # fixstr
        elif tag >= 0xE0:
            result = tag - 256  # negative fixint
        else:
            result = self._decode_tagged(stream, tag, context)

        return result

    def _decode_array(self, stream: BinaryIO, context: Context, n: int):
        for i in range(n):
            # context.push_path(i)
            if context.inspect:
                with context.inspect_scope(stream, i, self, None) as node:
                    item = self.decode(stream, context=context)
                    if node:
                        node.value = item
            else:
                item = self.decode(stream, context=context)
            # if node:
            #     node.value = item
            yield item
            # context.pop_path()

    def _decode_map(self, stream: BinaryIO, context: Context, n: int):
        for i in range(n):
            # context.push_path(i)
            if context.inspect:
                with context.inspect_scope(stream, i, self, None) as node:
                    # context.push_path("key")
                    with context.inspect_scope(stream, None, self, None) as key_node:
                        # use self._keysafe on decode
                        k = self._keysafe.decode(stream, context=context)
                        if key_node:
                            key_node.value = k
                    # context.pop_path()

                    # context.push_path("value")
                    with context.inspect_scope(stream, k, self, None) as value_node:
                        v = self.decode(stream, context=context)
                        if value_node:
                            value_node.value = v
                    if node:
                        node.value = k, v
            else:
                k = self._keysafe.decode(stream, context=context)
                v = self.decode(stream, context=context)
            # if value_node:
            #     value_node.value = v
            # context.pop_path()

            # if node:
            #     node.value = k, v
            yield k, v
            # context.pop_path()

    def _decode_tagged(self, stream: BinaryIO, tag: int, context: Context) -> Any:
        if tag == 0xC0:
            result = None
        elif tag == 0xC2:
            result = False
        elif tag == 0xC3:
            result = True
        elif BIN8 <= tag <= BIN32:
            result = _BIN_BY_TAG[tag].decode(stream, context=context)
        elif FLOAT32 <= tag <= FLOAT64:
            result = _FLOAT_BY_TAG[tag].decode(stream)
        elif 0xCC <= tag <= 0xCF:
            result = _UINT_BY_TAG[tag].decode(stream)
        elif 0xD0 <= tag <= 0xD3:
            result = _SINT_BY_TAG[tag].decode(stream)
        elif STR8 <= tag <= STR32:
            result = _STR_BY_TAG[tag].decode(stream, context=context)
        elif ARRAY16 <= tag <= ARRAY32:
            length_fmt = types.u16 if tag == ARRAY16 else types.u32
            start = stream.tell()
            length = length_fmt.decode(stream)
            context.inspect_leaf(stream, "--len--", length_fmt, length, start)
            result = self.array_type(self._decode_array(stream, context, length))
        elif MAP16 <= tag <= MAP32:
            length_fmt = types.u16 if tag == MAP16 else types.u32
            start = stream.tell()
            length = length_fmt.decode(stream)
            context.inspect_leaf(stream, "--len--", length_fmt, length, start)
            result = self.map_type(self._decode_map(stream, context, length))
        else:
            raise ValueError(f"Unknown msgpack tag: 0x{tag:02x}")

        return result


# Singleton instance
msgpack = MsgPack()
msgpack_f32 = MsgPack(float_precision=4)

# =============================================================================
# Tests
# =============================================================================


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
