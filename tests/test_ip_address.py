import ipaddress
from dataclasses import dataclass
from typing import Annotated

from fmtspec import decode, derive_fmt, encode, types


@dataclass
class IPv4Holder:
    ipv4: Annotated[ipaddress.IPv4Address, types.u32]


@dataclass
class IPv6Holder:
    ipv6: Annotated[ipaddress.IPv6Address, types.u128]


def test_ipv4_field_u32():
    addr = ipaddress.IPv4Address("127.0.0.1")
    obj = IPv4Holder(ipv4=addr)

    fmt = derive_fmt(IPv4Holder)

    data = encode(obj, fmt)

    assert data == b"\x7f\x00\x00\x01"

    result = decode(data, fmt, shape=IPv4Holder)
    assert result.ipv4 == obj.ipv4
    assert isinstance(result.ipv4, ipaddress.IPv4Address)

    data = encode({"ipv4": addr}, fmt)

    assert data == b"\x7f\x00\x00\x01"

    result = decode(data, shape=IPv4Holder)
    assert result.ipv4 == obj.ipv4
    assert isinstance(result.ipv4, ipaddress.IPv4Address)

    data = encode(obj)

    assert data == b"\x7f\x00\x00\x01"

    result = decode(data, fmt, shape=IPv4Holder)
    assert result.ipv4 == obj.ipv4
    assert isinstance(result.ipv4, ipaddress.IPv4Address)


def test_ipv6_field_u128():
    addr = ipaddress.IPv6Address("::1")
    obj = IPv6Holder(ipv6=addr)

    fmt = derive_fmt(IPv6Holder)

    data = encode(obj, fmt)

    assert data == b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"

    result = decode(data, fmt, shape=IPv6Holder)
    assert result.ipv6 == obj.ipv6
    assert isinstance(result.ipv6, ipaddress.IPv6Address)

    data = encode({"ipv6": addr}, fmt)

    assert data == b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"

    result = decode(data, shape=IPv6Holder)
    assert result.ipv6 == obj.ipv6
    assert isinstance(result.ipv6, ipaddress.IPv6Address)

    data = encode(obj)

    assert data == b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"

    result = decode(data, fmt, shape=IPv6Holder)
    assert result.ipv6 == obj.ipv6
    assert isinstance(result.ipv6, ipaddress.IPv6Address)
