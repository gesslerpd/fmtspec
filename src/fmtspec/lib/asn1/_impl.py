"""ASN.1 BER/DER-style TLV support built on fmtspec."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from io import BytesIO
from typing import TYPE_CHECKING, Any, ClassVar, Required, TypedDict

from fmtspec import Context, InspectNode, types
from fmtspec.stream import peek, read_exactly, write_all

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import EllipsisType


class ASN1Class(Enum):
    UNIVERSAL = "universal"
    APPLICATION = "application"
    CONTEXT = "context"
    PRIVATE = "private"


class TagClass(IntEnum):
    UNIVERSAL = 0b00
    APPLICATION = 0b01
    CONTEXT = 0b10
    PRIVATE = 0b11


class UniversalTag(IntEnum):
    BOOLEAN = 1
    INTEGER = 2
    BIT_STRING = 3
    OCTET_STRING = 4
    NULL = 5
    OBJECT_IDENTIFIER = 6
    UTF8_STRING = 12
    SEQUENCE = 16
    SET = 17
    PRINTABLE_STRING = 19
    IA5_STRING = 22
    UTC_TIME = 23
    GENERALIZED_TIME = 24


class ASN1Node(TypedDict, total=False):
    tag: Required[int]
    tag_class: ASN1Class
    constructed: bool
    value: Any


ASN1_TAG_OCTET = types.Bitfields(
    {
        "tag_low": types.Bitfield(bits=5),
        "constructed": types.Bitfield(bits=1),
        "tag_class": types.Bitfield(bits=2),
    },
)
TAG_MASK = 0x1F
SHORT_FORM_LENGTH_LIMIT = 0x80
OID_MIN_ARCS = 2
OID_MAX_FIRST_ARC = 2
OID_SECOND_ARC_LIMIT = 40
BIT_STRING_MAX_UNUSED_BITS = 7


@dataclass(frozen=True, slots=True)
class ASN1Tag:
    size: ClassVar[EllipsisType] = ...

    def encode(self, stream, value: tuple[ASN1Class, int, bool], **_) -> None:
        tag_class, tag, constructed = value
        ASN1_TAG_OCTET.encode(
            stream,
            {
                "tag_low": tag & TAG_MASK,
                "constructed": int(constructed),
                "tag_class": TagClass[tag_class.name],
            },
        )
        if tag >= TAG_MASK:
            write_all(stream, _encode_base128(tag))

    def decode(self, stream, **_) -> tuple[ASN1Class, int, bool]:
        first = ASN1_TAG_OCTET.decode(stream)
        tag_class = ASN1Class[TagClass(first["tag_class"]).name]
        constructed = bool(first["constructed"])
        low_tag = first["tag_low"]
        if low_tag < TAG_MASK:
            return tag_class, low_tag, constructed
        return tag_class, _decode_base128(stream), constructed


@dataclass(frozen=True, slots=True)
class ASN1Length:
    size: ClassVar[EllipsisType] = ...

    def encode(self, stream, value: int, **_) -> None:
        if value < 0:
            raise ValueError("Length must be non-negative")
        if value < SHORT_FORM_LENGTH_LIMIT:
            write_all(stream, bytes([value]))
            return

        octets = value.to_bytes((value.bit_length() + 7) // 8, "big")
        write_all(stream, bytes([SHORT_FORM_LENGTH_LIMIT | len(octets)]))
        write_all(stream, octets)

    def decode(self, stream, **_) -> int | None:
        first = read_exactly(stream, 1)[0]
        if first == SHORT_FORM_LENGTH_LIMIT:
            return None
        if first < SHORT_FORM_LENGTH_LIMIT:
            return first

        octet_count = first & 0x7F
        if octet_count == 0:
            raise ValueError("Invalid ASN.1 length: 0xFF reserved")
        return int.from_bytes(read_exactly(stream, octet_count), "big")


ASN1_TAG = ASN1Tag()
ASN1_LENGTH = ASN1Length()


def _encode_base128(value: int) -> bytes:
    if value < 0:
        raise ValueError("Tag number must be non-negative")
    if value == 0:
        return b"\x00"

    chunks: list[int] = []
    while value:
        chunks.append(value & 0x7F)
        value >>= 7

    chunks.reverse()
    for i in range(len(chunks) - 1):
        chunks[i] |= 0x80
    return bytes(chunks)


def _decode_base128(stream, *, first_byte: int | None = None) -> int:
    value = 0
    current = first_byte
    while True:
        if current is None:
            current = read_exactly(stream, 1)[0]
        value = (value << 7) | (current & 0x7F)
        if current & 0x80 == 0:
            return value
        current = None


def _encode_int_twos_complement(value: int) -> bytes:
    if value == 0:
        return b"\x00"

    nbytes = max(1, (value.bit_length() + 8) // 8)
    while True:
        encoded = value.to_bytes(nbytes, "big", signed=True)
        if int.from_bytes(encoded, "big", signed=True) == value:
            return encoded
        nbytes += 1


def _encode_oid(oid: str) -> bytes:
    arcs = [int(p) for p in oid.split(".")]
    if len(arcs) < OID_MIN_ARCS:
        raise ValueError("OID must have at least two arcs")
    if arcs[0] > OID_MAX_FIRST_ARC:
        raise ValueError("OID first arc must be 0, 1, or 2")
    if arcs[0] < OID_MIN_ARCS and arcs[1] >= OID_SECOND_ARC_LIMIT:
        raise ValueError("OID second arc must be < 40 when first arc is 0 or 1")

    out = bytearray([OID_SECOND_ARC_LIMIT * arcs[0] + arcs[1]])
    for arc in arcs[OID_MIN_ARCS:]:
        out.extend(_encode_base128(arc))
    return bytes(out)


def _decode_oid(data: bytes) -> str:
    if not data:
        raise ValueError("OID body must not be empty")

    first = data[0]
    first_arc = min(OID_MAX_FIRST_ARC, first // OID_SECOND_ARC_LIMIT)
    second_arc = first - OID_SECOND_ARC_LIMIT * first_arc
    arcs = [first_arc, second_arc]

    stream = BytesIO(data[1:])
    while stream.tell() < len(data) - 1:
        arcs.append(_decode_base128(stream))
    return ".".join(str(arc) for arc in arcs)


def _decode_universal_primitive(tag: int, data: bytes) -> Any:
    value: Any = data
    if tag == UniversalTag.BOOLEAN:
        if len(data) != 1:
            raise ValueError("BOOLEAN must be exactly 1 byte")
        value = data != b"\x00"
    elif tag == UniversalTag.INTEGER:
        if not data:
            raise ValueError("INTEGER body must not be empty")
        value = int.from_bytes(data, "big", signed=True)
    elif tag == UniversalTag.BIT_STRING:
        if not data:
            raise ValueError("BIT STRING body must include unused-bits byte")
        value = {"unused_bits": data[0], "data": data[1:]}
    elif tag == UniversalTag.NULL:
        if data:
            raise ValueError("NULL body must be empty")
        value = None
    elif tag == UniversalTag.OBJECT_IDENTIFIER:
        value = _decode_oid(data)
    elif tag == UniversalTag.UTF8_STRING:
        value = data.decode("utf-8")
    elif tag in ASCII_STRING_TAGS:
        value = data.decode("ascii")
    return value


def _encode_bit_string(value: Any) -> bytes:
    if not isinstance(value, dict):
        return b"\x00" + bytes(value)

    unused_bits = int(value.get("unused_bits", 0))
    data = bytes(value.get("data", b""))
    if not 0 <= unused_bits <= BIT_STRING_MAX_UNUSED_BITS:
        raise ValueError("BIT STRING unused_bits must be in range [0, 7]")
    return bytes([unused_bits]) + data


def _encode_boolean(value: Any) -> bytes:
    return b"\xff" if bool(value) else b"\x00"


def _encode_integer(value: Any) -> bytes:
    if not isinstance(value, int):
        raise TypeError("INTEGER value must be int")
    return _encode_int_twos_complement(value)


def _encode_null(value: Any) -> bytes:
    if value is not None:
        raise TypeError("NULL value must be None")
    return b""


def _encode_oid_value(value: Any) -> bytes:
    if not isinstance(value, str):
        raise TypeError("OID value must be str")
    return _encode_oid(value)


def _encode_utf8(value: Any) -> bytes:
    if not isinstance(value, str):
        raise TypeError("UTF8String value must be str")
    return value.encode("utf-8")


def _encode_ascii(value: Any) -> bytes:
    if not isinstance(value, str):
        raise TypeError("ASCII string/time value must be str")
    return value.encode("ascii")


ASCII_STRING_TAGS = {
    UniversalTag.PRINTABLE_STRING,
    UniversalTag.IA5_STRING,
    UniversalTag.UTC_TIME,
    UniversalTag.GENERALIZED_TIME,
}

CONSTRUCTED_TAGS = {
    UniversalTag.SEQUENCE,
    UniversalTag.SET,
}

PRIMITIVE_ENCODERS: dict[int, Any] = {
    UniversalTag.BOOLEAN: _encode_boolean,
    UniversalTag.INTEGER: _encode_integer,
    UniversalTag.BIT_STRING: _encode_bit_string,
    UniversalTag.NULL: _encode_null,
    UniversalTag.OBJECT_IDENTIFIER: _encode_oid_value,
    UniversalTag.UTF8_STRING: _encode_utf8,
}


def _encode_universal_primitive(tag: int, value: Any) -> bytes:
    if tag in ASCII_STRING_TAGS:
        return _encode_ascii(value)
    encoder = PRIMITIVE_ENCODERS.get(tag)
    if encoder is None:
        return bytes(value)
    return encoder(value)


@dataclass(frozen=True, slots=True)
class ASN1:
    size: ClassVar[EllipsisType] = ...

    def _encode_constructed_body_with_nodes(
        self, items: list[ASN1Node], context: Context
    ) -> tuple[bytes, Iterable[InspectNode]]:
        buf = BytesIO()
        child_context = Context(inspect=context.inspect)
        for i, item in enumerate(items):
            with child_context.inspect_scope(buf, i, self, item):
                self.encode(buf, item, context=child_context)

        return buf.getvalue(), child_context.inspect_children

    def _decode_constructed_items_greedy(self, stream, context: Context):
        i = 0
        while True:
            if peek(stream, 2) == b"\x00\x00":
                eoc_start = stream.tell()
                eoc_marker = read_exactly(stream, 2)
                context.inspect_leaf(stream, "--eoc--", types.Bytes(2), eoc_marker, eoc_start)
                return

            with context.inspect_scope(stream, i, self, None) as node:
                item = self.decode(stream, context=context)
                if node:
                    node.value = item

            yield item
            i += 1

    def _decode_constructed_items(self, stream, context: Context, length: int):
        i = 0
        end = stream.tell() + length

        while stream.tell() < end:
            with context.inspect_scope(stream, i, self, None) as node:
                item = self.decode(stream, context=context)
                if node:
                    node.value = item
            yield item
            i += 1

        if stream.tell() != end:
            raise ValueError("Constructed value length mismatch")

    def encode(self, stream, value: ASN1Node, *, context: Context) -> None:
        tag_class = ASN1Class(value.get("tag_class", ASN1Class.UNIVERSAL))
        tag: int = value["tag"]
        inner_value = value.get("value")

        constructed = value.get("constructed")
        if constructed is None:
            constructed = tag_class == ASN1Class.UNIVERSAL and tag in CONSTRUCTED_TAGS

        body_nodes = []
        if constructed:
            if not isinstance(inner_value, list):
                raise TypeError("Constructed ASN.1 node value must be a list of child nodes")
            body, body_nodes = self._encode_constructed_body_with_nodes(inner_value, context)
        elif tag_class == ASN1Class.UNIVERSAL:
            body = _encode_universal_primitive(tag, inner_value)
        else:
            body = bytes(inner_value)

        tag_start = stream.tell()
        tag_tuple = (tag_class, tag, constructed)
        ASN1_TAG.encode(stream, tag_tuple, context=context)
        context.inspect_leaf(stream, "tag", ASN1_TAG, tag_tuple, tag_start)

        length_start = stream.tell()
        ASN1_LENGTH.encode(stream, len(body), context=context)
        context.inspect_leaf(stream, "--len--", ASN1_LENGTH, len(body), length_start)

        write_all(stream, body)
        if body_nodes:
            context.inspect_children.extend(body_nodes)
        else:
            body_start = stream.tell() - len(body)
            context.inspect_leaf(stream, "value", types.Bytes(len(body)), inner_value, body_start)

    def decode(self, stream, *, context: Context) -> ASN1Node:
        tag_start = stream.tell()
        tag_tuple = ASN1_TAG.decode(stream, context=context)
        tag_class, tag, constructed = tag_tuple
        context.inspect_leaf(stream, "tag", ASN1_TAG, tag_tuple, tag_start)

        length_start = stream.tell()
        length = ASN1_LENGTH.decode(stream, context=context)
        context.inspect_leaf(stream, "--len--", ASN1_LENGTH, length, length_start)

        if constructed:
            if length is None:
                value = list(self._decode_constructed_items_greedy(stream, context=context))
            else:
                value = list(self._decode_constructed_items(stream, context=context, length=length))
        else:
            if length is None:
                raise ValueError("Indefinite length is only valid for constructed values")
            body_start = stream.tell()
            body = read_exactly(stream, length)
            if tag_class == ASN1Class.UNIVERSAL:
                value = _decode_universal_primitive(tag, body)
            else:
                value = body
            context.inspect_leaf(stream, "value", types.Bytes(length), value, body_start)

        return {
            "tag_class": tag_class,
            "tag": tag,
            "constructed": constructed,
            "value": value,
        }


asn1 = ASN1()
