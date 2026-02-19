"""ASN.1 BER/DER-style TLV example implementation using fmtspec.

This example implements a compact ASN.1 encoder/decoder that supports:
- Tag classes: universal/application/context/private
- Short and long-form tag numbers
- Definite lengths (encode/decode)
- Indefinite length decoding for constructed values
- Common universal types: BOOLEAN, INTEGER, OCTET STRING, NULL, OID,
  UTF8String, PrintableString, IA5String, UTCTime, GeneralizedTime,
  SEQUENCE, SET
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from fmtspec import decode, encode, types
from fmtspec._stream import peek, read_exactly, write_all

if TYPE_CHECKING:
    from types import EllipsisType

    from fmtspec._protocol import Context


type ASN1Class = Literal["universal", "application", "context", "private"]
type ASN1Node = dict[str, Any]


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


CLASS_TO_BITS: dict[ASN1Class, int] = {
    "universal": TagClass.UNIVERSAL,
    "application": TagClass.APPLICATION,
    "context": TagClass.CONTEXT,
    "private": TagClass.PRIVATE,
}
BITS_TO_CLASS: dict[TagClass, ASN1Class] = {
    TagClass.UNIVERSAL: "universal",
    TagClass.APPLICATION: "application",
    TagClass.CONTEXT: "context",
    TagClass.PRIVATE: "private",
}


ASN1_TAG_OCTET = types.Bitfields(
    fields={
        "tag_low": types.Bitfield(bits=5),
        "constructed": types.Bitfield(bits=1),
        "tag_class": types.Bitfield(bits=2),
    },
)
TAG_MASK = 0x1F


@dataclass(frozen=True, slots=True)
class ASN1Tag:
    size: ClassVar[EllipsisType] = ...

    def encode(self, value: tuple[ASN1Class, int, bool], stream, **_) -> None:
        tag_class, tag, constructed = value
        ASN1_TAG_OCTET.encode(
            {
                "tag_low": tag & TAG_MASK,
                "constructed": int(constructed),
                "tag_class": CLASS_TO_BITS[tag_class],
            },
            stream,
        )
        if tag >= TAG_MASK:
            write_all(stream, _encode_base128(tag))

    def decode(self, stream, **_) -> tuple[ASN1Class, int, bool]:
        first = ASN1_TAG_OCTET.decode(stream)
        tag_class = BITS_TO_CLASS[TagClass(first["tag_class"])]
        constructed = bool(first["constructed"])
        low_tag = first["tag_low"]
        if low_tag < TAG_MASK:
            return tag_class, low_tag, constructed
        return tag_class, _decode_base128(stream), constructed


@dataclass(frozen=True, slots=True)
class ASN1Length:
    size: ClassVar[EllipsisType] = ...

    def encode(self, value: int, stream, **_) -> None:
        if value < 0:
            raise ValueError("Length must be non-negative")
        if value < 0x80:
            write_all(stream, bytes([value]))
            return

        octets = value.to_bytes((value.bit_length() + 7) // 8, "big")
        write_all(stream, bytes([0x80 | len(octets)]))
        write_all(stream, octets)

    def decode(self, stream, **_) -> int | None:
        first = read_exactly(stream, 1)[0]
        if first == 0x80:
            return None
        if first < 0x80:
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
    if len(arcs) < 2:
        raise ValueError("OID must have at least two arcs")
    if arcs[0] > 2:
        raise ValueError("OID first arc must be 0, 1, or 2")
    if arcs[0] < 2 and arcs[1] >= 40:
        raise ValueError("OID second arc must be < 40 when first arc is 0 or 1")

    out = bytearray([40 * arcs[0] + arcs[1]])
    for arc in arcs[2:]:
        out.extend(_encode_base128(arc))
    return bytes(out)


def _decode_oid(data: bytes) -> str:
    if not data:
        raise ValueError("OID body must not be empty")

    first = data[0]
    first_arc = min(2, first // 40)
    second_arc = first - 40 * first_arc
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
    if not 0 <= unused_bits <= 7:
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
    """ASN.1 BER/DER-style TLV format implementation."""

    size: ClassVar[EllipsisType] = ...

    def encode(self, value: ASN1Node, stream, *, context: Context) -> None:
        tag_class: ASN1Class = value.get("tag_class", "universal")
        tag: int = value["tag"]
        inner_value = value.get("value")

        constructed = value.get("constructed")
        if constructed is None:
            constructed = tag_class == "universal" and tag in CONSTRUCTED_TAGS

        if constructed:
            if not isinstance(inner_value, list):
                raise TypeError("Constructed ASN.1 node value must be a list of child nodes")
            buf = BytesIO()
            for item in inner_value:
                self.encode(item, buf, context=context)
            body = buf.getvalue()
        elif tag_class == "universal":
            body = _encode_universal_primitive(tag, inner_value)
        else:
            body = bytes(inner_value)

        ASN1_TAG.encode((tag_class, tag, constructed), stream, context=context)
        ASN1_LENGTH.encode(len(body), stream, context=context)
        write_all(stream, body)

    def _decode_constructed_definite(self, data: bytes, context: Context):
        inner = BytesIO(data)
        while inner.tell() < len(data):
            yield self.decode(inner, context=context)

    def _decode_constructed_indefinite(self, stream, context: Context):
        while True:
            probe = peek(stream, 2)
            if probe == b"\x00\x00":
                read_exactly(stream, 2)
                return
            yield self.decode(stream, context=context)

    def decode(self, stream, *, context: Context) -> ASN1Node:
        tag_class, tag, constructed = ASN1_TAG.decode(stream, context=context)
        length = ASN1_LENGTH.decode(stream, context=context)

        if constructed:
            if length is None:
                value = list(self._decode_constructed_indefinite(stream, context))
            else:
                body = read_exactly(stream, length)
                value = list(self._decode_constructed_definite(body, context))
        else:
            if length is None:
                raise ValueError("Indefinite length is only valid for constructed values")
            body = read_exactly(stream, length)
            if tag_class == "universal":
                value = _decode_universal_primitive(tag, body)
            else:
                value = body

        return {
            "tag_class": tag_class,
            "tag": tag,
            "constructed": constructed,
            "value": value,
        }


asn1 = ASN1()


def test_integer_roundtrip() -> None:
    node = {
        "tag": UniversalTag.INTEGER,
        "value": 2026,
    }

    encoded = encode(node, asn1)
    assert encoded == b"\x02\x02\x07\xea"
    assert decode(encoded, asn1) == {
        "tag_class": "universal",
        "tag": UniversalTag.INTEGER,
        "constructed": False,
        "value": 2026,
    }


def test_sequence_roundtrip() -> None:
    node = {
        "tag": UniversalTag.SEQUENCE,
        "constructed": True,
        "value": [
            {"tag": UniversalTag.INTEGER, "value": 42},
            {"tag": UniversalTag.OCTET_STRING, "value": b"hello"},
            {"tag": UniversalTag.NULL, "value": None},
            {"tag": UniversalTag.BOOLEAN, "value": True},
        ],
    }

    encoded = encode(node, asn1)
    decoded = decode(encoded, asn1)

    assert decoded == {
        "tag_class": "universal",
        "tag": UniversalTag.SEQUENCE,
        "constructed": True,
        "value": [
            {
                "tag_class": "universal",
                "tag": UniversalTag.INTEGER,
                "constructed": False,
                "value": 42,
            },
            {
                "tag_class": "universal",
                "tag": UniversalTag.OCTET_STRING,
                "constructed": False,
                "value": b"hello",
            },
            {
                "tag_class": "universal",
                "tag": UniversalTag.NULL,
                "constructed": False,
                "value": None,
            },
            {
                "tag_class": "universal",
                "tag": UniversalTag.BOOLEAN,
                "constructed": False,
                "value": True,
            },
        ],
    }


def test_object_identifier_roundtrip() -> None:
    node = {
        "tag": UniversalTag.OBJECT_IDENTIFIER,
        "value": "1.2.840.113549",
    }

    encoded = encode(node, asn1)
    assert encoded == b"\x06\x06\x2a\x86\x48\x86\xf7\x0d"

    decoded = decode(encoded, asn1)
    assert decoded["value"] == "1.2.840.113549"


def test_context_specific_explicit_roundtrip() -> None:
    node = {
        "tag_class": "context",
        "tag": 0,
        "constructed": True,
        "value": [
            {"tag": UniversalTag.INTEGER, "value": 5},
        ],
    }

    encoded = encode(node, asn1)
    assert encoded == b"\xa0\x03\x02\x01\x05"
    assert decode(encoded, asn1) == {
        "tag_class": "context",
        "tag": 0,
        "constructed": True,
        "value": [
            {
                "tag_class": "universal",
                "tag": UniversalTag.INTEGER,
                "constructed": False,
                "value": 5,
            }
        ],
    }


def test_long_form_length_roundtrip() -> None:
    payload = b"A" * 130
    node = {
        "tag": UniversalTag.OCTET_STRING,
        "value": payload,
    }

    encoded = encode(node, asn1)
    assert encoded[:3] == b"\x04\x81\x82"

    decoded = decode(encoded, asn1)
    assert decoded["value"] == payload


def test_decode_known_der_sample() -> None:
    # SEQUENCE { INTEGER 42, OCTET STRING "hello" }
    sample = b"\x30\x0a\x02\x01\x2a\x04\x05hello"
    decoded = decode(sample, asn1)

    assert decoded["tag"] == UniversalTag.SEQUENCE
    assert decoded["constructed"] is True
    assert decoded["value"][0]["value"] == 42
    assert decoded["value"][1]["value"] == b"hello"

    assert encode(decoded, asn1) == sample


def test_decode_x509_certificate() -> None:
    certificate_der = Path(__file__).parent / "apple.der"
    certificate = decode(certificate_der.read_bytes(), asn1)

    assert certificate["tag"] == UniversalTag.SEQUENCE
    assert certificate["constructed"]
    assert len(certificate["value"]) == 3

    tbs_certificate, signature_algorithm, signature_value = certificate["value"]
    assert tbs_certificate["tag"] == UniversalTag.SEQUENCE
    assert signature_algorithm["tag"] == UniversalTag.SEQUENCE
    assert signature_value["tag"] == UniversalTag.BIT_STRING

    tbs_fields = tbs_certificate["value"]
    assert len(tbs_fields) >= 7

    issuer = tbs_fields[3]
    subject = tbs_fields[5]

    issuer_cn = issuer["value"][0]["value"][0]["value"][1]["value"]
    subject_cn = subject["value"][0]["value"][0]["value"][1]["value"]
    assert issuer_cn == "US"
    assert subject_cn == "US"

    issuer_org = issuer["value"][1]["value"][0]["value"][1]["value"]
    subject_org = subject["value"][1]["value"][0]["value"][1]["value"]
    assert issuer_org == "DigiCert Inc"
    assert subject_org == "Apple Inc."
