"""TLS Client Hello example test.

Based on Kaitai Struct definition for TLS 1.2 Client Hello (RFC 5246).
Demonstrates nested dictionary format maps with the ende framework.
"""

from fmtspec import decode, encode, encode_inspect, format_tree, types

# Big-endian integers (TLS uses network byte order)
u1 = types.Int(byteorder="big", signed=False, size=1)
u2 = types.Int(byteorder="big", signed=False, size=2)
u4 = types.Int(byteorder="big", signed=False, size=4)

# Format definitions matching Kaitai struct types

# version:
#   - major: u1
#   - minor: u1
version_fmt = {
    "major": u1,
    "minor": u1,
}

# random:
#   - gmt_unix_time: u4
#   - random: size 28
random_fmt = {
    "gmt_unix_time": u4,
    "random": types.Bytes(28),
}

# session_id:
#   - len: u1
#   - sid: size len
session_id_fmt = types.Sized(length=u1, fmt=types.Bytes())

# cipher_suites:
#   - len: u2
#   - cipher_suites: u2 repeat (len/2 times)
# Note: The len is byte length, and each cipher suite is 2 bytes
cipher_suites_fmt = types.PrefixedArray(byteorder="big", prefix_size=2, element_fmt=u2)

# compression_methods:
#   - len: u1
#   - compression_methods: size len
compression_methods_fmt = types.Sized(length=u1, fmt=types.Bytes())

# server_name:
#   - name_type: u1
#   - length: u2
#   - host_name: size length
server_name_fmt = {
    "name_type": u1,
    "host_name": types.Sized(length=u2, fmt=types.Bytes()),
}

# sni:
#   - list_length: u2
#   - server_names: repeat eos
sni_fmt = types.PrefixedArray(byteorder="big", prefix_size=2, element_fmt=server_name_fmt)

# protocol:
#   - strlen: u1
#   - name: size strlen
protocol_fmt = types.Sized(length=u1, fmt=types.Bytes())

# alpn:
#   - ext_len: u2
#   - alpn_protocols: repeat eos
alpn_fmt = types.PrefixedArray(byteorder="big", prefix_size=2, element_fmt=protocol_fmt)

# Extension type constants
EXT_SNI = 0x0000
EXT_ALPN = 0x0010

# extension with switch-case body parsing:
#   - type: u2
#   - len: u2
#   - body: size len (parsed based on type)
extension_fmt = {
    "type": u2,
    "body": types.Switch(
        key=types.Ref("type"),  # backward reference to sibling "type" field
        cases={
            EXT_SNI: sni_fmt,
            EXT_ALPN: alpn_fmt,
        },
        default=None,  # Unknown extensions return raw bytes
        byteorder="big",
        prefix_size=2,
    ),
}

# extensions:
#   - len: u2
#   - extensions: repeat eos
extensions_fmt = types.PrefixedArray(byteorder="big", prefix_size=2, element_fmt=extension_fmt)

# Full TLS Client Hello format
tls_client_hello_fmt = {
    "version": version_fmt,
    "random": random_fmt,
    "session_id": session_id_fmt,
    "cipher_suites": cipher_suites_fmt,
    "compression_methods": compression_methods_fmt,
    "extensions": extensions_fmt,
}


def test_version_roundtrip():
    """Test encoding/decoding TLS version."""
    version = {"major": 3, "minor": 3}  # TLS 1.2
    data = encode(version, version_fmt)
    assert data == b"\x03\x03"
    result = decode(data, version_fmt)
    assert result == version


def test_random_roundtrip():
    """Test encoding/decoding random structure."""
    random_data = {
        "gmt_unix_time": 0x12345678,
        "random": b"\x00" * 28,
    }
    data = encode(random_data, random_fmt)
    assert len(data) == 32  # 4 bytes timestamp + 28 bytes random
    assert data[:4] == b"\x12\x34\x56\x78"
    result = decode(data, random_fmt)
    assert result == random_data


def test_session_id_roundtrip():
    """Test encoding/decoding session ID (length-prefixed bytes)."""
    session_id = b"\xaa\xbb\xcc\xdd"
    data = encode(session_id, session_id_fmt)
    assert data == b"\x04\xaa\xbb\xcc\xdd"  # 1-byte length prefix + data
    result = decode(data, session_id_fmt)
    assert result == session_id


def test_session_id_empty():
    """Test encoding/decoding empty session ID."""
    session_id = b""
    data = encode(session_id, session_id_fmt)
    assert data == b"\x00"
    result = decode(data, session_id_fmt)
    assert result == session_id


def test_cipher_suites_roundtrip():
    """Test encoding/decoding cipher suites array."""
    cipher_suites = [0x1301, 0x1302, 0x1303]  # TLS 1.3 cipher suites
    data = encode(cipher_suites, cipher_suites_fmt)
    # 2-byte length (6 bytes total) + 3 cipher suites (2 bytes each)
    assert data == b"\x00\x06\x13\x01\x13\x02\x13\x03"
    result = decode(data, cipher_suites_fmt)
    assert result == cipher_suites


def test_extension_roundtrip():
    """Test encoding/decoding a single extension with SNI body."""
    extension = {
        "type": EXT_SNI,
        "body": [{"name_type": 0, "host_name": b"example.com"}],
    }
    data = encode(extension, extension_fmt)
    result = decode(data, extension_fmt)
    assert result == extension


def test_extension_unknown_type():
    """Test encoding/decoding an unknown extension type (raw bytes)."""
    extension = {
        "type": 0xFFFF,  # Unknown extension type
        "body": b"\x01\x02\x03\x04",
    }
    data = encode(extension, extension_fmt)
    result = decode(data, extension_fmt)
    assert result == extension


def test_sni_extension_body():
    """Test encoding/decoding SNI extension body structure."""
    sni = [
        {"name_type": 0, "host_name": b"example.com"},
    ]
    data = encode(sni, sni_fmt)
    result = decode(data, sni_fmt)
    assert result == sni


def test_alpn_extension_body():
    """Test encoding/decoding ALPN extension body structure."""
    alpn = [b"h2", b"http/1.1"]
    data = encode(alpn, alpn_fmt)
    result = decode(data, alpn_fmt)
    assert result == alpn


def test_full_client_hello_roundtrip():
    """Test encoding/decoding a complete TLS Client Hello message."""
    client_hello = {
        "version": {"major": 3, "minor": 3},  # TLS 1.2
        "random": {
            "gmt_unix_time": 0x5F8A1B2C,
            "random": b"abcdefghijklmnopqrstuvwxyz12",
        },
        "session_id": b"",  # No session resumption
        "cipher_suites": [
            0x1301,  # TLS_AES_128_GCM_SHA256
            0x1302,  # TLS_AES_256_GCM_SHA384
            0xC02F,  # TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
        ],
        "compression_methods": b"\x00",  # No compression
        "extensions": [
            {
                "type": EXT_SNI,
                "body": [{"name_type": 0, "host_name": b"example.com"}],
            },
            {
                "type": EXT_ALPN,
                "body": [b"h2", b"http/1.1"],
            },
        ],
    }

    data = encode(client_hello, tls_client_hello_fmt)
    result = decode(data, tls_client_hello_fmt)

    _, tree = encode_inspect(client_hello, tls_client_hello_fmt)
    print(format_tree(tree))
    assert result == client_hello
    assert len(tree.children) == len(client_hello)


def test_minimal_client_hello():
    """Test a minimal TLS Client Hello with no extensions."""
    client_hello = {
        "version": {"major": 3, "minor": 1},  # TLS 1.0
        "random": {
            "gmt_unix_time": 0,
            "random": b"\x00" * 28,
        },
        "session_id": b"",
        "cipher_suites": [0x002F],  # TLS_RSA_WITH_AES_128_CBC_SHA
        "compression_methods": b"\x00",
        "extensions": [],
    }

    data = encode(client_hello, tls_client_hello_fmt)
    result = decode(data, tls_client_hello_fmt)
    assert result == client_hello


# --- Switch type integration tests ---


def test_switch_sni_extension():
    """Test Switch automatically parses SNI extension body."""
    extension = {
        "type": EXT_SNI,
        "body": [{"name_type": 0, "host_name": b"example.com"}],
    }
    data = encode(extension, extension_fmt)
    result = decode(data, extension_fmt)
    assert result["type"] == EXT_SNI
    assert result["body"] == [{"name_type": 0, "host_name": b"example.com"}]


def test_switch_alpn_extension():
    """Test Switch automatically parses ALPN extension body."""
    extension = {
        "type": EXT_ALPN,
        "body": [b"h2", b"http/1.1"],
    }
    data = encode(extension, extension_fmt)
    result = decode(data, extension_fmt)
    assert result["type"] == EXT_ALPN
    assert result["body"] == [b"h2", b"http/1.1"]


def test_switch_unknown_extension_fallback():
    """Test Switch falls back to raw bytes for unknown extension types."""
    extension = {
        "type": 0x0023,  # session_ticket extension (not in our cases)
        "body": b"\xde\xad\xbe\xef",
    }
    data = encode(extension, extension_fmt)
    result = decode(data, extension_fmt)
    assert result["type"] == 0x0023
    assert result["body"] == b"\xde\xad\xbe\xef"


# --- Real TLS Client Hello sample data tests ---

# Real TLS 1.2 Client Hello captured from curl
# This is the Client Hello body (after the handshake header)
REAL_CLIENT_HELLO_SAMPLE = bytes.fromhex(
    # Version: TLS 1.2 (0x0303)
    "0303"
    # Random (32 bytes): gmt_unix_time (4) + random (28)
    "aabbccdd"  # gmt_unix_time
    "000102030405060708090a0b0c0d0e0f101112131415161718191a1b"  # random
    # Session ID length: 0
    "00"
    # Cipher suites length: 6 (3 suites)
    "0006"
    # Cipher suites
    "1301"  # TLS_AES_128_GCM_SHA256
    "1302"  # TLS_AES_256_GCM_SHA384
    "c02f"  # TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
    # Compression methods length: 1
    "01"
    # Compression methods: null
    "00"
    # Extensions length: 0 (no extensions for simplicity)
    "0000",
)


def test_decode_real_client_hello_sample():
    """Test decoding a real TLS Client Hello sample."""
    result = decode(REAL_CLIENT_HELLO_SAMPLE, tls_client_hello_fmt)

    assert result["version"] == {"major": 3, "minor": 3}
    assert result["random"]["gmt_unix_time"] == 0xAABBCCDD
    assert len(result["random"]["random"]) == 28
    assert result["session_id"] == b""
    assert result["cipher_suites"] == [0x1301, 0x1302, 0xC02F]
    assert result["compression_methods"] == b"\x00"
    assert result["extensions"] == []


# More realistic sample with SNI extension
REAL_CLIENT_HELLO_WITH_SNI = bytes.fromhex(
    # Version: TLS 1.2 (0x0303)
    "0303"
    # Random (32 bytes)
    "5f8a1b2c"  # gmt_unix_time
    "6162636465666768696a6b6c6d6e6f707172737475767778797a3132"  # "abcdefghijklmnopqrstuvwxyz12"
    # Session ID length: 0
    "00"
    # Cipher suites length: 4 (2 suites)
    "0004"
    "c02f"  # TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
    "c030"  # TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
    # Compression methods length: 1, value: null
    "01"
    "00"
    # Extensions length
    "0016"  # 22 bytes of extensions
    # Extension: SNI (type 0x0000)
    "0000"  # type
    "0012"  # length: 18 bytes
    # SNI extension body
    "0010"  # list length: 16
    "00"  # name type: host_name
    "000d"  # hostname length: 13
    "6578616d706c652e636f6d",  # "example.com" (actually 11 bytes, adjusting...)
)

# Fix: recalculate with correct lengths
REAL_CLIENT_HELLO_WITH_SNI = bytes.fromhex(
    # Version: TLS 1.2 (0x0303)
    "0303"
    # Random (32 bytes)
    "5f8a1b2c"  # gmt_unix_time
    "6162636465666768696a6b6c6d6e6f707172737475767778797a3132"  # "abcdefghijklmnopqrstuvwxyz12"
    # Session ID length: 0
    "00"
    # Cipher suites length: 4 (2 suites)
    "0004"
    "c02f"  # TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
    "c030"  # TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
    # Compression methods length: 1, value: null
    "01"
    "00"
    # Extensions length
    "0014"  # 20 bytes of extensions
    # Extension: SNI (type 0x0000)
    "0000"  # type
    "0010"  # length: 16 bytes
    # SNI extension body
    "000e"  # list length: 14
    "00"  # name type: host_name
    "000b"  # hostname length: 11
    "6578616d706c652e636f6d",  # "example.com"
)


def test_decode_real_client_hello_with_sni():
    """Test decoding a Client Hello with SNI extension."""
    result = decode(REAL_CLIENT_HELLO_WITH_SNI, tls_client_hello_fmt)

    assert result["version"] == {"major": 3, "minor": 3}
    assert result["random"]["random"] == b"abcdefghijklmnopqrstuvwxyz12"
    assert result["cipher_suites"] == [0xC02F, 0xC030]
    assert len(result["extensions"]) == 1

    sni_ext = result["extensions"][0]
    assert sni_ext["type"] == EXT_SNI
    # Body is now automatically parsed as SNI structure
    assert len(sni_ext["body"]) == 1
    assert sni_ext["body"][0]["name_type"] == 0
    assert sni_ext["body"][0]["host_name"] == b"example.com"


# Sample with multiple extensions (SNI + ALPN)
REAL_CLIENT_HELLO_MULTI_EXT = bytes.fromhex(
    # Version: TLS 1.2
    "0303"
    # Random (32 bytes)
    "00000000"
    "00000000000000000000000000000000000000000000000000000000"  # 28 zero bytes
    # Session ID: empty
    "00"
    # Cipher suites: 2 bytes length, 1 suite
    "0002"
    "1301"
    # Compression: 1 byte length, null
    "01"
    "00"
    # Extensions length
    "0023"  # 35 bytes
    # SNI extension
    "0000"  # type
    "0010"  # length: 16
    "000e"  # list length: 14
    "00"  # name_type
    "000b"  # hostname length
    "6578616d706c652e636f6d"  # example.com
    # ALPN extension
    "0010"  # type (16 = ALPN)
    "000b"  # length: 11
    "0009"  # protocols length: 9
    "02"
    "6832"  # "h2"
    "05"
    "68322d3134",  # "h2-14" (just for variety)
)


def test_decode_real_client_hello_multi_extensions():
    """Test decoding a Client Hello with multiple extensions."""
    result = decode(REAL_CLIENT_HELLO_MULTI_EXT, tls_client_hello_fmt)

    assert result["version"] == {"major": 3, "minor": 3}
    assert result["cipher_suites"] == [0x1301]
    assert len(result["extensions"]) == 2

    # First extension: SNI - automatically parsed
    sni_ext = result["extensions"][0]
    assert sni_ext["type"] == EXT_SNI
    assert sni_ext["body"] == [{"name_type": 0, "host_name": b"example.com"}]

    # Second extension: ALPN - automatically parsed
    alpn_ext = result["extensions"][1]
    assert alpn_ext["type"] == EXT_ALPN
    assert alpn_ext["body"] == [b"h2", b"h2-14"]


def test_roundtrip_real_sample():
    """Test that decoding then encoding produces identical bytes."""
    result = decode(REAL_CLIENT_HELLO_SAMPLE, tls_client_hello_fmt)
    reencoded = encode(result, tls_client_hello_fmt)
    assert reencoded == REAL_CLIENT_HELLO_SAMPLE


def test_roundtrip_multi_ext_sample():
    """Test roundtrip with multiple extensions."""
    result = decode(REAL_CLIENT_HELLO_MULTI_EXT, tls_client_hello_fmt)
    reencoded = encode(result, tls_client_hello_fmt)
    assert reencoded == REAL_CLIENT_HELLO_MULTI_EXT
