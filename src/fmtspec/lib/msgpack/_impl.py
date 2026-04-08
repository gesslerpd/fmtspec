"""MessagePack serialization support built on fmtspec."""

# ruff: noqa: PLR0912, PLR2004

from __future__ import annotations

from dataclasses import dataclass, field
from types import NoneType
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Literal, Self

from fmtspec import Context, types

if TYPE_CHECKING:
    from types import EllipsisType


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

str8 = types.Sized(length=types.u8, fmt=types.Str())
str16 = types.Sized(length=types.u16, fmt=types.Str())
str32 = types.Sized(length=types.u32, fmt=types.Str())
bin8 = types.Sized(length=types.u8, fmt=types.Bytes())
bin16 = types.Sized(length=types.u16, fmt=types.Bytes())
bin32 = types.Sized(length=types.u32, fmt=types.Bytes())

BYTES = {i: bytes([i]) for i in range(256)}


def _encode_int(value: int, stream: BinaryIO) -> None:
    if 0 <= value <= 0x7F:
        stream.write(BYTES[value])
    elif -0x20 <= value < 0:
        stream.write(BYTES[value & 0xFF])
    elif 0x80 <= value <= 0xFF:
        stream.write(b"\xcc")
        types.u8.encode(stream, value)
    elif -0x80 <= value < -0x20:
        stream.write(b"\xd0")
        types.i8.encode(stream, value)
    elif 0x100 <= value <= 0xFFFF:
        stream.write(b"\xcd")
        types.u16.encode(stream, value)
    elif -0x8000 <= value < -0x80:
        stream.write(b"\xd1")
        types.i16.encode(stream, value)
    elif 0x10000 <= value <= 0xFFFFFFFF:
        stream.write(b"\xce")
        types.u32.encode(stream, value)
    elif -0x80000000 <= value < -0x8000:
        stream.write(b"\xd2")
        types.i32.encode(stream, value)
    elif 0x100000000 <= value <= 0xFFFFFFFFFFFFFFFF:
        stream.write(b"\xcf")
        types.u64.encode(stream, value)
    elif -0x8000000000000000 <= value < -0x80000000:
        stream.write(b"\xd3")
        types.i64.encode(stream, value)
    else:
        raise OverflowError(f"Integer {value} out of msgpack range")


def _encode_str(value: str, stream: BinaryIO, context) -> None:
    data = value.encode("utf-8")
    n = len(data)
    if n <= 31:
        stream.write(BYTES[0xA0 | n])
        stream.write(data)
    elif n <= 0xFF:
        stream.write(b"\xd9")
        str8.encode(stream, value, context=context)
    elif n <= 0xFFFF:
        stream.write(b"\xda")
        str16.encode(stream, value, context=context)
    else:
        stream.write(b"\xdb")
        str32.encode(stream, value, context=context)


def _encode_bin(value: bytes, stream: BinaryIO, context) -> None:
    n = len(value)
    if n <= 0xFF:
        stream.write(b"\xc4")
        bin8.encode(stream, value, context=context)
    elif n <= 0xFFFF:
        stream.write(b"\xc5")
        bin16.encode(stream, value, context=context)
    else:
        stream.write(b"\xc6")
        bin32.encode(stream, value, context=context)


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


@dataclass(frozen=True, slots=True, kw_only=True)
class MsgPack:
    size: ClassVar[EllipsisType] = ...
    float_precision: Literal[4, 8] = 8
    array_type: type = list
    map_type: type = dict

    _float_type: types.Float = field(init=False, repr=False, compare=False)
    _float_tag: int = field(init=False, repr=False, compare=False)
    _keysafe: Self | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.array_type is tuple and self.array_type is tuple:
            keysafe = None
        else:
            keysafe = self.__class__(
                float_precision=self.float_precision,
                array_type=tuple,
                map_type=tuple,
            )
        object.__setattr__(self, "_keysafe", keysafe)
        object.__setattr__(
            self,
            "_float_tag",
            FLOAT32 if self.float_precision == 4 else FLOAT64,
        )
        object.__setattr__(
            self,
            "_float_type",
            _FLOAT_BY_TAG[self._float_tag],
        )

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        t = type(value)
        if t is NoneType:
            stream.write(b"\xc0")
        elif t is bool:
            stream.write(b"\xc3" if value else b"\xc2")
        elif t is int:
            _encode_int(value, stream)
        elif t is float:
            stream.write(BYTES[self._float_tag])
            self._float_type.encode(stream, value)
        elif t is str:
            _encode_str(value, stream, context)
        elif t is bytes or t is bytearray or t is memoryview:
            _encode_bin(bytes(value), stream, context)
        elif t is list or t is tuple:
            self._encode_array(list(value), stream, context)
        elif t is dict:
            self._encode_map(value, stream, context)
        elif issubclass(t, NoneType):
            stream.write(b"\xc0")
        elif issubclass(t, bool):
            stream.write(b"\xc3" if value else b"\xc2")
        elif issubclass(t, int):
            _encode_int(value, stream)
        elif issubclass(t, float):
            stream.write(BYTES[self._float_tag])
            self._float_type.encode(stream, value)
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
            stream.write(BYTES[0x90 | n])
        elif n <= 0xFFFF:
            stream.write(b"\xdc")
            start = stream.tell()
            types.u16.encode(stream, n)
            context.inspect_leaf(stream, "--len--", types.u16, n, start)
        else:
            stream.write(b"\xdd")
            start = stream.tell()
            types.u32.encode(stream, n)
            context.inspect_leaf(stream, "--len--", types.u32, n, start)

        for i, item in enumerate(value):
            if context.inspect:
                with context.inspect_scope(stream, i, self, item):
                    self.encode(stream, item, context=context)
            else:
                self.encode(stream, item, context=context)

    def _encode_map(self, value: dict, stream: BinaryIO, context: Context) -> None:
        n = len(value)
        if n <= 15:
            stream.write(BYTES[0x80 | n])
        elif n <= 0xFFFF:
            stream.write(b"\xde")
            start = stream.tell()
            types.u16.encode(stream, n)
            context.inspect_leaf(stream, "--len--", types.u16, n, start)
        else:
            stream.write(b"\xdf")
            start = stream.tell()
            types.u32.encode(stream, n)
            context.inspect_leaf(stream, "--len--", types.u32, n, start)

        i = 0
        for k, v in value.items():
            if context.inspect:
                with context.inspect_scope(stream, i, self, (k, v)):
                    with context.inspect_scope(stream, None, self, k):
                        self.encode(stream, k, context=context)
                    with context.inspect_scope(stream, k, self, v):
                        self.encode(stream, v, context=context)
            else:
                self.encode(stream, k, context=context)
                self.encode(stream, v, context=context)
            i += 1

    def decode(self, stream: BinaryIO, *, context: Context) -> Any:
        b = stream.read(1)
        if not b:
            raise EOFError("Unexpected end of stream")
        tag = b[0]

        result: Any
        if tag <= 0x7F:
            result = tag
        elif tag <= 0x8F:
            result = self.map_type(self._decode_map(stream, context, tag & 0x0F))
        elif tag <= 0x9F:
            result = self.array_type(self._decode_array(stream, context, tag & 0x0F))
        elif tag <= 0xBF:
            result = stream.read(tag & 0x1F).decode("utf-8")
        elif tag >= 0xE0:
            result = tag - 256
        else:
            result = self._decode_tagged(stream, tag, context)

        return result

    def _decode_array(self, stream: BinaryIO, context: Context, n: int):
        for i in range(n):
            if context.inspect:
                with context.inspect_scope(stream, i, self, None) as node:
                    item = self.decode(stream, context=context)
                    if node:
                        node.value = item
            else:
                item = self.decode(stream, context=context)
            yield item

    def _keysafe_decode(self, stream: BinaryIO, *, context: Context) -> Any:
        if self._keysafe:
            return self._keysafe.decode(stream, context=context)
        return self.decode(stream, context=context)

    def _decode_map(self, stream: BinaryIO, context: Context, n: int):
        for i in range(n):
            if context.inspect:
                with context.inspect_scope(stream, i, self, None) as node:
                    with context.inspect_scope(stream, None, self, None) as key_node:
                        k = self._keysafe_decode(stream, context=context)
                        if key_node:
                            key_node.value = k
                    with context.inspect_scope(stream, k, self, None) as value_node:
                        v = self.decode(stream, context=context)
                        if value_node:
                            value_node.value = v
                    if node:
                        node.value = k, v
            else:
                k = self._keysafe_decode(stream, context=context)
                v = self.decode(stream, context=context)
            yield k, v

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


msgpack = MsgPack()
msgpack_f32 = MsgPack(float_precision=4)
