"""CIP (Common Industrial Protocol) Get Attributes All request example.

Uses fmtspec CIP types to send a Get Attributes All request to an EtherNet/IP device.
"""

from __future__ import annotations

import argparse
import socket
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Annotated, cast

from fmtspec import DecodeError, decode, derive_fmt, encode, types
from fmtspec.types.cip import (
    LogicalSegment,
    LogicalSegmentType,
    short_sized_padded_epath,
    udint,
    uint,
    usint,
)

# EtherNet/IP Encapsulation Commands
ENCAP_CMD_REGISTER_SESSION = 0x0065
ENCAP_CMD_UNREGISTER_SESSION = 0x0066
ENCAP_CMD_SEND_RR_DATA = 0x006F

# CIP Service Codes
CIP_SERVICE_GET_ATTRIBUTES_ALL = 0x01

# Common CIP Classes
CIP_CLASS_IDENTITY = 0x01


@dataclass
class EncapsulationHeader:
    """EtherNet/IP encapsulation header (24 bytes)."""

    command: Annotated[int, uint] = 0
    length: Annotated[int, uint] = 0
    session_handle: Annotated[int, udint] = 0
    status: Annotated[int, udint] = 0
    sender_context: Annotated[bytes, types.Bytes(8)] = b"\x00" * 8
    options: Annotated[int, udint] = 0


ENCAP_HEADER_FMT = derive_fmt(EncapsulationHeader)


@dataclass
class CPFItemHeader:
    """Common Packet Format item header."""

    type_id: Annotated[int, uint] = 0
    length: Annotated[int, uint] = 0


CPF_ITEM_HEADER_FMT = derive_fmt(CPFItemHeader)


@dataclass
class RegisterSessionData:
    """RegisterSession request data."""

    protocol_version: Annotated[int, uint] = 1
    options_flags: Annotated[int, uint] = 0


REGISTER_SESSION_DATA_FMT = derive_fmt(RegisterSessionData)


@dataclass
class SendRRDataHeader:
    """SendRRData specific header."""

    interface_handle: Annotated[int, udint] = 0
    timeout: Annotated[int, uint] = 0
    item_count: Annotated[int, uint] = 0


SEND_RR_DATA_HEADER_FMT = derive_fmt(SendRRDataHeader)


@dataclass
class IdentityResponse:
    """CIP Identity object attributes."""

    vendor_id: Annotated[int, uint] = 0
    device_type: Annotated[int, uint] = 0
    product_code: Annotated[int, uint] = 0
    revision_major: Annotated[int, usint] = 0
    revision_minor: Annotated[int, usint] = 0
    status: Annotated[int, uint] = 0
    serial_number: Annotated[int, udint] = 0
    product_name: Annotated[str, types.Sized(usint, types.Str(encoding="ascii"))] = ""


IDENTITY_RESPONSE_FMT = derive_fmt(IdentityResponse)


def build_register_session() -> bytes:
    """Build a RegisterSession request."""
    data = encode(RegisterSessionData(), REGISTER_SESSION_DATA_FMT)
    header = EncapsulationHeader(
        command=ENCAP_CMD_REGISTER_SESSION,
        length=len(data),
    )
    return encode(header, ENCAP_HEADER_FMT) + data


def build_unregister_session(session_handle: int) -> bytes:
    """Build an UnregisterSession request."""
    header = EncapsulationHeader(
        command=ENCAP_CMD_UNREGISTER_SESSION,
        session_handle=session_handle,
    )
    return encode(header, ENCAP_HEADER_FMT)


def build_cip_request_path(class_id: int, instance_id: int) -> bytes:
    """Build a CIP request path using fmtspec types."""
    path = [
        LogicalSegment(type=LogicalSegmentType.type_class_id, value=class_id),
        LogicalSegment(type=LogicalSegmentType.type_instance_id, value=instance_id),
    ]
    return encode(path, short_sized_padded_epath)


def encode_cpf_item(type_id: int, data: bytes) -> bytes:
    """Encode a Common Packet Format item."""
    header = CPFItemHeader(type_id=type_id, length=len(data))
    return encode(header, CPF_ITEM_HEADER_FMT) + data


def decode_cpf_item(stream: BytesIO) -> tuple[int, bytes]:
    """Decode a Common Packet Format item from stream."""
    header = decode(stream.read(4), CPF_ITEM_HEADER_FMT)
    data = stream.read(header["length"])
    return header["type_id"], data


def build_get_attributes_all(
    session_handle: int,
    class_id: int = CIP_CLASS_IDENTITY,
    instance_id: int = 1,
) -> bytes:
    """Build a SendRRData request with Get Attributes All CIP message."""
    # Build request path using fmtspec CIP types
    request_path = build_cip_request_path(class_id, instance_id)

    # CIP Message Router Request:
    # Service (1 byte) + Request Path
    cip_request = bytes([CIP_SERVICE_GET_ATTRIBUTES_ALL]) + request_path

    # Null Address Item (type 0x0000, required for UCMM)
    null_address_item = encode_cpf_item(0x0000, b"")

    # Unconnected Data Item (type 0x00B2)
    unconnected_data_item = encode_cpf_item(0x00B2, cip_request)

    # SendRRData specific data
    send_rr_header = SendRRDataHeader(item_count=2)
    send_rr_data = encode(send_rr_header, SEND_RR_DATA_HEADER_FMT)
    send_rr_data += null_address_item
    send_rr_data += unconnected_data_item

    header = EncapsulationHeader(
        command=ENCAP_CMD_SEND_RR_DATA,
        length=len(send_rr_data),
        session_handle=session_handle,
    )
    return encode(header, ENCAP_HEADER_FMT) + send_rr_data


def parse_identity_response(data: bytes) -> IdentityResponse:
    """Parse Identity object Get Attributes All response."""
    try:
        result = decode(data, IDENTITY_RESPONSE_FMT, shape=IdentityResponse)
    except DecodeError as e:
        print(f"Warning: Failed to parse IdentityResponse: {e}")
        result = cast("IdentityResponse", e.obj)
    return result


def send_cip_request(
    ip_address: str,
    port: int = 44818,
    class_id: int = CIP_CLASS_IDENTITY,
    instance_id: int = 1,
    timeout: float = 10.0,
) -> dict | None:
    """Send a CIP Get Attributes All request and return parsed response."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((ip_address, port))

        # Step 1: Register session
        sock.sendall(build_register_session())
        response = sock.recv(1024)

        if len(response) < 24:
            raise RuntimeError("Invalid RegisterSession response")

        header = decode(response[:24], ENCAP_HEADER_FMT)
        if header["status"] != 0:
            raise RuntimeError(f"RegisterSession failed with status: {header['status']}")

        session_handle = header["session_handle"]
        print(f"Session registered: 0x{session_handle:08X}")

        try:
            # Step 2: Send Get Attributes All request
            request = build_get_attributes_all(session_handle, class_id, instance_id)
            sock.sendall(request)
            response = sock.recv(4096)

            if len(response) < 24:
                raise RuntimeError("Invalid SendRRData response")

            header = decode(response[:24], ENCAP_HEADER_FMT)
            if header["status"] != 0:
                raise RuntimeError(f"SendRRData failed with status: {header['status']}")

            # Parse CPF items from response
            # Skip encap header (24) + interface handle (4) + timeout (2)
            stream = BytesIO(response[30:])
            item_count = decode(stream.read(2), uint)

            cip_response_data = None
            for _ in range(item_count):
                type_id, data = decode_cpf_item(stream)
                if type_id == 0x00B2:  # Unconnected Data Item
                    cip_response_data = data
                    break

            if cip_response_data is None:
                raise RuntimeError("No CIP response data in SendRRData response")

            # Parse CIP response header
            # Response: Service (1) + Reserved (1) + General Status (1) +
            #           Additional Status Size (1) + [Additional Status] + Data
            general_status = cip_response_data[2]
            additional_status_size = cip_response_data[3]

            if general_status != 0:
                raise RuntimeError(
                    f"CIP request failed with general status: 0x{general_status:02X}"
                )

            # Skip CIP header to get attribute data
            data_offset = 4 + (additional_status_size * 2)
            attribute_data = cip_response_data[data_offset:]

            # Parse Identity class response
            if class_id == CIP_CLASS_IDENTITY:
                return asdict(parse_identity_response(attribute_data))
            else:
                return {"raw_data": attribute_data.hex()}

        finally:
            # Step 3: Unregister session
            sock.sendall(build_unregister_session(session_handle))
            print("Session unregistered")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send CIP Get Attributes All request to an EtherNet/IP device"
    )
    parser.add_argument("ip_address", help="IP address of the target device")
    parser.add_argument("--port", "-p", type=int, default=44818, help="TCP port (default: 44818)")
    parser.add_argument(
        "--class-id",
        "-c",
        type=int,
        default=CIP_CLASS_IDENTITY,
        help="CIP class ID (default: 1 = Identity)",
    )
    parser.add_argument(
        "--instance-id", "-i", type=int, default=1, help="CIP instance ID (default: 1)"
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=10.0,
        help="Socket timeout in seconds (default: 10.0)",
    )
    args = parser.parse_args()

    try:
        result = send_cip_request(
            args.ip_address,
            args.port,
            args.class_id,
            args.instance_id,
            args.timeout,
        )
        if result:
            print("\nDevice Information:")
            for key, value in result.items():
                print(f"  {key}: {value}")
    except (OSError, TimeoutError) as e:
        print(f"Connection error: {e}")
    except RuntimeError as e:
        print(f"Protocol error: {e}")


if __name__ == "__main__":
    main()
