from pathlib import Path

from fmtspec import decode, decode_inspect, encode, encode_inspect, format_tree
from fmtspec.lib.asn1 import ASN1Class, ASN1Node, UniversalTag, asn1

DEFAULTS = {
    "value": None,
    "constructed": False,
    "tag_class": ASN1Class.UNIVERSAL,
}


def test_integer_roundtrip() -> None:
    node: ASN1Node = {
        "tag": UniversalTag.INTEGER,
        "value": 2026,
    }

    encoded = encode(node, asn1)
    assert encoded == b"\x02\x02\x07\xea"
    assert decode(encoded, asn1) == {
        **DEFAULTS,
        **node,
    }


def test_sequence_roundtrip() -> None:
    node = {
        **DEFAULTS,
        "tag": UniversalTag.SEQUENCE,
        "constructed": True,
        "value": [
            {**DEFAULTS, "tag": UniversalTag.INTEGER, "value": 42},
            {**DEFAULTS, "tag": UniversalTag.OCTET_STRING, "value": b"hello"},
            {**DEFAULTS, "tag": UniversalTag.NULL, "value": None},
            {**DEFAULTS, "tag": UniversalTag.BOOLEAN, "value": True},
        ],
    }

    encoded = encode(node, asn1)
    decoded = decode(encoded, asn1)

    assert decoded == node


def test_object_identifier_roundtrip() -> None:
    node = {
        **DEFAULTS,
        "tag": UniversalTag.OBJECT_IDENTIFIER,
        "value": "1.2.840.113549",
    }

    encoded = encode(node, asn1)
    assert encoded == b"\x06\x06\x2a\x86\x48\x86\xf7\x0d"

    decoded = decode(encoded, asn1)
    assert decoded == node


def test_context_specific_explicit_roundtrip() -> None:
    node = {
        "tag_class": ASN1Class.CONTEXT,
        "tag": 0,
        "constructed": True,
        "value": [
            {**DEFAULTS, "tag": UniversalTag.INTEGER, "value": 5},
        ],
    }

    encoded = encode(node, asn1)
    assert encoded == b"\xa0\x03\x02\x01\x05"
    assert decode(encoded, asn1) == node


def test_long_form_length_roundtrip() -> None:
    payload = b"A" * 130
    node = {
        **DEFAULTS,
        "tag": UniversalTag.OCTET_STRING,
        "value": payload,
    }

    encoded = encode(node, asn1)
    assert encoded[:3] == b"\x04\x81\x82"

    decoded = decode(encoded, asn1)
    assert decoded == node


def test_decode_known_der_sample() -> None:
    # SEQUENCE { INTEGER 42, OCTET STRING "hello" }
    sample = b"\x30\x0a\x02\x01\x2a\x04\x05hello"
    decoded = decode(sample, asn1)

    assert decoded["tag"] == UniversalTag.SEQUENCE
    assert decoded["constructed"] is True
    assert decoded["value"][0]["value"] == 42
    assert decoded["value"][1]["value"] == b"hello"

    assert encode(decoded, asn1) == sample


def test_inspect_sequence_has_tlv_children() -> None:
    node = {
        **DEFAULTS,
        "tag": UniversalTag.SEQUENCE,
        "constructed": True,
        "value": [
            {**DEFAULTS, "tag": UniversalTag.INTEGER, "value": 42},
            {**DEFAULTS, "tag": UniversalTag.OCTET_STRING, "value": b"hi"},
        ],
    }

    encoded, encode_tree = encode_inspect(node, asn1)
    assert encoded == b"\x30\x07\x02\x01\x2a\x04\x02hi"
    encode_keys = [child.key for child in encode_tree.children]
    assert encode_keys[2:] == [0, 1]

    decoded, decode_tree = decode_inspect(encoded, asn1)
    assert decoded == node
    decode_keys = [child.key for child in decode_tree.children]
    assert decode_keys[2:] == [0, 1]


def test_inspect_constructed_context_tree_encode_decode() -> None:
    node = {
        "tag_class": ASN1Class.CONTEXT,
        "tag": 1,
        "constructed": True,
        "value": [
            {**DEFAULTS, "tag": UniversalTag.INTEGER, "value": 7},
            {**DEFAULTS, "tag": UniversalTag.OCTET_STRING, "value": b"ok"},
        ],
    }

    encoded, encode_tree = encode_inspect(node, asn1)
    assert encoded == b"\xa1\x07\x02\x01\x07\x04\x02ok"

    encode_keys = [child.key for child in encode_tree.children]
    assert encode_keys[0] in {"tag", "--tag--"}
    assert encode_keys[1] == "--len--"
    assert encode_keys[2:] == [0, 1]

    first_child_keys = [child.key for child in encode_tree.children[2].children]
    second_child_keys = [child.key for child in encode_tree.children[3].children]
    assert first_child_keys[0] in {"tag", "--tag--"}
    assert second_child_keys[0] in {"tag", "--tag--"}
    assert first_child_keys[1:] == ["--len--", "value"]
    assert second_child_keys[1:] == ["--len--", "value"]

    decoded, decode_tree = decode_inspect(encoded, asn1)
    assert decoded == node

    decode_keys = [child.key for child in decode_tree.children]
    assert decode_keys[0] in {"tag", "--tag--"}
    assert decode_keys[1] == "--len--"
    assert decode_keys[2:] == [0, 1]

    encode_nodes = list(encode_tree.children)
    decode_nodes = list(decode_tree.children)
    encode_layout = [[child.key for child in node.children] for node in encode_nodes[2:]]
    decode_layout = [[child.key for child in node.children] for node in decode_nodes[2:]]
    assert encode_layout == decode_layout
    assert format_tree(encode_tree) == format_tree(decode_tree)
    print()
    print(format_tree(encode_tree))


def test_decode_x509_certificate() -> None:
    certificate_der = Path(__file__).parent / "apple.der"
    data = certificate_der.read_bytes()
    certificate, tree = decode_inspect(data, asn1)

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

    print("Certificate decoded successfully with inspection:")
    dec_tree = format_tree(tree)
    print(dec_tree)

    encoded_data, tree = encode_inspect(certificate, asn1)
    print("Certificate encoded successfully with inspection:")
    enc_tree = format_tree(tree)
    print(enc_tree)
    assert encoded_data == data
    assert len(data) == 1314
    assert dec_tree == enc_tree
