# ruff: noqa: PLR0911, PLR0912, PLR0915

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, Literal

from fmtspec import (
    Context,
    decode,
    decode_inspect,
    decode_stream,
    encode,
    encode_inspect,
    format_tree,
    types,
)
from fmtspec.stream import decode_stream as decode_child_stream
from fmtspec.stream import read_exactly, seek_to, write_all
from fmtspec.types._pointer import Pointer

if TYPE_CHECKING:
    from types import EllipsisType


def _seek_exif_app1(stream: BinaryIO) -> int:
    if stream.read(2) != b"\xff\xd8":
        raise ValueError("Not a JPEG file")

    while True:
        marker_prefix = stream.read(1)
        if not marker_prefix:
            break
        if marker_prefix != b"\xff":
            raise ValueError("Invalid JPEG marker alignment")
        marker_raw = stream.read(1)
        if len(marker_raw) != 1:
            raise ValueError("Unexpected end of JPEG while reading marker")
        marker = marker_raw[0]
        if marker in {0xD9, 0xDA}:
            break
        segment_length_raw = stream.read(2)
        if len(segment_length_raw) != 2:
            raise ValueError("Unexpected end of JPEG while reading segment length")
        segment_length = int.from_bytes(segment_length_raw, "big")
        segment_start = stream.tell()
        if marker == 0xE1 and stream.read(len(EXIF_HEADER)) == EXIF_HEADER:
            stream.seek(segment_start)
            return segment_length - 2
        stream.seek(segment_start + segment_length - 2)

    raise ValueError("No EXIF APP1 segment found")


EXIF_HEADER = b"Exif\x00\x00"
EXIF_HEADER_FMT = types.Literal(EXIF_HEADER)
TIFF_MAGIC = 42


class ExifType(IntEnum):
    BYTE = 1
    ASCII = 2
    SHORT = 3
    LONG = 4
    RATIONAL = 5
    SBYTE = 6
    UNDEFINED = 7
    SSHORT = 8
    SLONG = 9
    SRATIONAL = 10
    FLOAT = 11
    DOUBLE = 12


class IfdTag(IntEnum):
    GPS_LATITUDE_REF = 0x0001
    GPS_LATITUDE = 0x0002
    GPS_LONGITUDE_REF = 0x0003
    GPS_LONGITUDE = 0x0004
    GPS_ALTITUDE_REF = 0x0005
    GPS_ALTITUDE = 0x0006
    GPS_TIME_STAMP = 0x0007
    GPS_DATE_STAMP = 0x001D
    IMAGE_WIDTH = 0x0100
    IMAGE_LENGTH = 0x0101
    COMPRESSION = 0x0103
    MAKE = 0x010F
    MODEL = 0x0110
    ORIENTATION = 0x0112
    X_RESOLUTION = 0x011A
    Y_RESOLUTION = 0x011B
    RESOLUTION_UNIT = 0x0128
    SOFTWARE = 0x0131
    DATE_TIME = 0x0132
    SUB_IFDS = 0x014A
    EXIF_IFD = 0x8769
    EXPOSURE_TIME = 0x829A
    F_NUMBER = 0x829D
    EXPOSURE_PROGRAM = 0x8822
    GPS_IFD = 0x8825
    ISO_SPEED_RATINGS = 0x8827
    EXIF_VERSION = 0x9000
    DATE_TIME_ORIGINAL = 0x9003
    DATE_TIME_DIGITIZED = 0x9004
    OFFSET_TIME = 0x9010
    OFFSET_TIME_ORIGINAL = 0x9011
    OFFSET_TIME_DIGITIZED = 0x9012
    COMPONENTS_CONFIGURATION = 0x9101
    SHUTTER_SPEED_VALUE = 0x9201
    APERTURE_VALUE = 0x9202
    BRIGHTNESS_VALUE = 0x9203
    EXPOSURE_BIAS_VALUE = 0x9204
    MAX_APERTURE_VALUE = 0x9205
    SUBJECT_DISTANCE = 0x9206
    METERING_MODE = 0x9207
    FLASH = 0x9209
    FOCAL_LENGTH = 0x920A
    SUBSEC_TIME = 0x9290
    SUBSEC_TIME_ORIGINAL = 0x9291
    SUBSEC_TIME_DIGITIZED = 0x9292
    FLASHPIX_VERSION = 0xA000
    COLOR_SPACE = 0xA001
    PIXEL_X_DIMENSION = 0xA002
    PIXEL_Y_DIMENSION = 0xA003
    INTEROPERABILITY_IFD = 0xA005
    SENSING_METHOD = 0xA217
    SCENE_TYPE = 0xA301
    CUSTOM_RENDERED = 0xA401
    EXPOSURE_MODE = 0xA402
    WHITE_BALANCE = 0xA403
    DIGITAL_ZOOM_RATIO = 0xA404
    FOCAL_LENGTH_IN_35MM_FILM = 0xA405
    SCENE_CAPTURE_TYPE = 0xA406
    CONTRAST = 0xA408
    SATURATION = 0xA409
    SHARPNESS = 0xA40A
    SUBJECT_DISTANCE_RANGE = 0xA40C
    LENS_MAKE = 0xA433
    LENS_MODEL = 0xA434
    YCBCR_POSITIONING = 0x0213
    THUMBNAIL_OFFSET = 0x0201
    THUMBNAIL_LENGTH = 0x0202


IFD_POINTER_TAGS = {IfdTag.EXIF_IFD, IfdTag.GPS_IFD, IfdTag.SUB_IFDS}

TYPE_SIZES: dict[int, int] = {
    ExifType.BYTE: 1,
    ExifType.ASCII: 1,
    ExifType.SHORT: 2,
    ExifType.LONG: 4,
    ExifType.RATIONAL: 8,
    ExifType.SBYTE: 1,
    ExifType.UNDEFINED: 1,
    ExifType.SSHORT: 2,
    ExifType.SLONG: 4,
    ExifType.SRATIONAL: 8,
    ExifType.FLOAT: 4,
    ExifType.DOUBLE: 8,
}


@dataclass(slots=True)
class _Piece:
    data: bytearray
    patches: list[tuple[int, _Piece]] = field(default_factory=list)


@dataclass(slots=True)
class _DecodeState:
    fmt: Any
    byte_order: bytes
    context: Context
    base_offset: int
    payload_length: int
    seen: set[int]


@dataclass(frozen=True, slots=True)
class _IfdFormat:
    fmt: Any
    byte_order: bytes
    base_offset: int
    payload_length: int
    seen: set[int]
    size: ClassVar[EllipsisType] = ...

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        raise NotImplementedError("_IfdFormat is a decode-only EXIF helper")

    def decode(self, stream: BinaryIO, *, context: Context) -> dict[str, Any]:
        return _decode_ifd_body(
            stream,
            state=_DecodeState(
                fmt=self.fmt,
                byte_order=self.byte_order,
                context=context,
                base_offset=self.base_offset,
                payload_length=self.payload_length,
                seen=self.seen,
            ),
            context=context,
        )


def _normalize_byte_order(byte_order: bytes) -> tuple[bytes, str]:
    if byte_order in {b"II", b"little", b"<"}:
        return b"II", "<"
    if byte_order in {b"MM", b"big", b">"}:
        return b"MM", ">"
    raise ValueError("byte_order must be 'II' or 'MM'")


LITTLE_ENDIAN_FORMATS = {
    "u16": types.u16le,
    "u32": types.u32le,
    "i16": types.i16le,
    "i32": types.i32le,
    "f32": types.f32le,
    "f64": types.f64le,
}

BIG_ENDIAN_FORMATS = {
    "u16": types.u16,
    "u32": types.u32,
    "i16": types.i16,
    "i32": types.i32,
    "f32": types.f32,
    "f64": types.f64,
}


def _endian_formats(endian: str) -> dict[str, Any]:
    return LITTLE_ENDIAN_FORMATS if endian == "<" else BIG_ENDIAN_FORMATS


def _int_fmt(
    *,
    endian: str,
    size: Literal[1, 2, 4, 8, 16],
    signed: bool = False,
    enum: type[IntEnum] | None = None,
) -> Any:
    return types.Int(
        byteorder="little" if endian == "<" else "big",
        signed=signed,
        size=size,
        enum=enum,
    )


def _byte_value_fmt(typ: int, endian: str):
    scalar_formats = _endian_formats(endian)
    formats: dict[int, Any] = {
        ExifType.BYTE: types.u8,
        ExifType.SBYTE: types.i8,
        ExifType.SHORT: scalar_formats["u16"],
        ExifType.SSHORT: scalar_formats["i16"],
        ExifType.LONG: scalar_formats["u32"],
        ExifType.SLONG: scalar_formats["i32"],
        ExifType.FLOAT: scalar_formats["f32"],
        ExifType.DOUBLE: scalar_formats["f64"],
    }
    return formats.get(typ)


def _rational_fmt(typ: int, endian: str) -> tuple[Any, Any]:
    scalar_formats = _endian_formats(endian)
    if typ == ExifType.RATIONAL:
        return (scalar_formats["u32"], scalar_formats["u32"])
    if typ == ExifType.SRATIONAL:
        return (scalar_formats["i32"], scalar_formats["i32"])
    raise ValueError(f"Unsupported EXIF rational type: {typ}")


def _encode_repeated(items: list[Any], fmt: Any) -> bytes:
    if len(items) == 1:
        return encode(items[0], fmt)
    return encode(items, types.array(fmt, dims=len(items)))


def _decode_repeated(raw: bytes, count: int, fmt: Any) -> Any:
    if count == 1:
        return decode(raw, fmt)
    return decode(raw, types.array(fmt, dims=count))


def _value_payload_fmt(typ: int, count: int, endian: str) -> Any | None:
    if typ in {ExifType.ASCII, ExifType.UNDEFINED}:
        return None
    if typ in {ExifType.RATIONAL, ExifType.SRATIONAL}:
        elem_fmt = _rational_fmt(typ, endian)
    else:
        elem_fmt = _byte_value_fmt(typ, endian)
    if elem_fmt is None:
        return None
    if count == 1:
        return elem_fmt
    return types.array(elem_fmt, dims=count)


def _shift_inspect_offsets(node: Any, offset: int) -> None:
    node.offset += offset
    for child in node.children:
        _shift_inspect_offsets(child, offset)


def _inspect_decoded_value(
    raw: bytes,
    *,
    value_fmt: Any | None,
    value: Any,
    start_offset: int,
    context: Context,
) -> bool:
    if not context.inspect or value_fmt is None:
        return False

    child_context = Context(inspect=True)
    decode_child_stream(BytesIO(raw), value_fmt, context=child_context, key="value")
    node = child_context.inspect_node
    if node is None:
        return False

    _shift_inspect_offsets(node, start_offset)
    node.value = value
    context.inspect_children.append(node)
    return True


def _validate_absolute_offset(
    absolute_offset: int,
    *,
    payload_length: int,
    message: str,
) -> None:
    if absolute_offset >= payload_length:
        raise ValueError(message)


def _tiff_header_fmt(byte_order: bytes) -> dict[str, Any]:
    _, endian = _normalize_byte_order(byte_order)
    scalar_formats = _endian_formats(endian)
    return {
        "byte_order": types.Bytes(2),
        "magic": scalar_formats["u16"],
        "ifd0_offset": scalar_formats["u32"],
    }


def _ifd_entry_fmt(endian: str) -> dict[str, Any]:
    return {
        "tag": _int_fmt(endian=endian, size=2, enum=IfdTag),
        "type": _int_fmt(endian=endian, size=2, enum=ExifType),
        "count": _int_fmt(endian=endian, size=4),
        "value": types.Bytes(4),
    }


def _pack_u16(value: int, endian: str) -> bytes:
    return encode(value, _endian_formats(endian)["u16"])


def _pack_u32(value: int, endian: str) -> bytes:
    return encode(value, _endian_formats(endian)["u32"])


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        return [value]
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return value
    return [value]


def _infer_type_and_count(value: Any) -> tuple[int, int]:
    if isinstance(value, str):
        encoded = value.encode("ascii")
        return ExifType.ASCII, len(encoded) + 1
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ExifType.UNDEFINED, len(value)
    if isinstance(value, float):
        return ExifType.FLOAT, 1
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, int) for item in value)
    ):
        if any(item < 0 for item in value):
            return ExifType.SRATIONAL, 1
        return ExifType.RATIONAL, 1
    if (
        isinstance(value, list)
        and value
        and all(
            isinstance(item, tuple)
            and len(item) == 2
            and all(isinstance(part, int) for part in item)
            for item in value
        )
    ):
        if any(part < 0 for item in value for part in item):
            return ExifType.SRATIONAL, len(value)
        return ExifType.RATIONAL, len(value)
    if isinstance(value, list) and value and all(isinstance(item, int) for item in value):
        if any(item < 0 for item in value):
            return ExifType.SLONG, len(value)
        if max(value, default=0) <= 0xFFFF:
            return ExifType.SHORT, len(value)
        return ExifType.LONG, len(value)
    if isinstance(value, int):
        if value < 0:
            return ExifType.SLONG, 1
        if value <= 0xFFFF:
            return ExifType.SHORT, 1
        return ExifType.LONG, 1
    raise TypeError(f"Cannot infer EXIF type for value of type {type(value).__name__}")


def _encode_inline_data(raw: bytes) -> bytes:
    if len(raw) > 4:
        raise ValueError("Inline EXIF values must be 4 bytes or smaller")
    return raw.ljust(4, b"\x00")


def _encode_value_bytes(typ: int, value: Any, endian: str) -> tuple[bytes, int]:
    if typ == ExifType.ASCII:
        if isinstance(value, bytes):
            raw = value if value.endswith(b"\x00") else value + b"\x00"
        else:
            raw = str(value).encode("ascii")
            if not raw.endswith(b"\x00"):
                raw += b"\x00"
        return raw, len(raw)

    if typ in {ExifType.BYTE, ExifType.SBYTE, ExifType.UNDEFINED}:
        if isinstance(value, (bytes, bytearray, memoryview)):
            raw = encode(bytes(value), types.Bytes(len(value)))
            return raw, len(raw)
        items = _as_list(value)
        if typ == ExifType.UNDEFINED:
            raw = encode(bytes(items), types.Bytes(len(items)))
            return raw, len(raw)
        items = [int(item) & 0xFF for item in items]
        return _encode_repeated(items, types.u8), len(items)

    if typ in {ExifType.RATIONAL, ExifType.SRATIONAL}:
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and all(isinstance(item, int) for item in value)
        ):
            items = [value]
        else:
            items = _as_list(value)
        raw = _encode_repeated(items, _rational_fmt(typ, endian))
        return raw, len(items)

    elem_fmt = _byte_value_fmt(typ, endian)
    if elem_fmt is not None:
        items = _as_list(value)
        raw = _encode_repeated(items, elem_fmt)
        return raw, len(items)

    raise ValueError(f"Unsupported EXIF type: {typ}")


def _decode_value_bytes(typ: int, count: int, raw: bytes, endian: str) -> Any:
    if typ == ExifType.ASCII:
        return raw.rstrip(b"\x00").decode("ascii")
    if typ == ExifType.BYTE:
        value = decode(raw, types.Bytes(len(raw)))
        if count == 1:
            return value[0] if value else 0
        return value
    if typ == ExifType.SBYTE:
        return _decode_repeated(raw, count, _byte_value_fmt(typ, endian))
    if typ == ExifType.UNDEFINED:
        return decode(raw, types.Bytes(len(raw)))
    if typ in {ExifType.RATIONAL, ExifType.SRATIONAL}:
        pair_fmt = _rational_fmt(typ, endian)
        if count == 1:
            return tuple(decode(raw, pair_fmt))
        values = [tuple(item) for item in decode(raw, types.array(pair_fmt, dims=count))]
        return values[0] if count == 1 else values
    elem_fmt = _byte_value_fmt(typ, endian)
    if elem_fmt is not None:
        return _decode_repeated(raw, count, elem_fmt)

    raise ValueError(f"Unsupported EXIF type: {typ}")


def _build_ifd_piece(ifd: dict[str, Any], byte_order: bytes) -> _Piece:
    _, endian = _normalize_byte_order(byte_order)
    entry_fmt = _ifd_entry_fmt(endian)
    entries = ifd.get("entries")
    if not isinstance(entries, list):
        raise TypeError("IFD entries must be provided as a list")

    data = bytearray()
    patches: list[tuple[int, _Piece]] = []
    data.extend(_pack_u16(len(entries), endian))

    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("Each EXIF entry must be a mapping")
        tag = int(entry["tag"])
        value = entry.get("value")
        typ = entry.get("type")
        count = entry.get("count")

        if isinstance(value, dict) and "entries" in value:
            if tag not in IFD_POINTER_TAGS:
                raise ValueError(f"Tag 0x{tag:04x} cannot point to a nested IFD")
            if typ is None:
                typ = ExifType.LONG
            if count is None:
                count = 1
            if typ != ExifType.LONG or count != 1:
                raise ValueError("Nested IFD pointers must use type LONG with count 1")
            child_piece = _build_ifd_piece(value, byte_order)
            patch_offset = len(data) + 8
            data.extend(
                encode(
                    {"tag": tag, "type": typ, "count": count, "value": b"\x00\x00\x00\x00"},
                    entry_fmt,
                )
            )
            patches.append((patch_offset, child_piece))
        else:
            if typ is None:
                typ, inferred_count = _infer_type_and_count(value)
                if count is None:
                    count = inferred_count
            elif count is None:
                _, count = _infer_type_and_count(value)

            raw, inferred_count = _encode_value_bytes(typ, value, endian)
            if count is None:
                count = inferred_count

            if len(raw) <= 4:
                value_field = _encode_inline_data(raw)
            else:
                child_piece = _Piece(bytearray(raw))
                patch_offset = len(data) + 8
                value_field = b"\x00\x00\x00\x00"
                patches.append((patch_offset, child_piece))
            data.extend(
                encode(
                    {"tag": tag, "type": typ, "count": count, "value": value_field},
                    entry_fmt,
                )
            )

    next_ifd = ifd.get("next_ifd")
    data.extend(b"\x00\x00\x00\x00")
    if next_ifd is not None:
        if not isinstance(next_ifd, dict):
            raise TypeError("next_ifd must be a mapping or None")
        next_ifd_piece = _build_ifd_piece(next_ifd, byte_order)
        patches.append((len(data) - 4, next_ifd_piece))

    return _Piece(data, patches)


def _flatten_pieces(piece: _Piece) -> list[_Piece]:
    pieces = [piece]
    for _, child in piece.patches:
        pieces.extend(_flatten_pieces(child))
    return pieces


def _patch_offsets(root_piece: _Piece, *, start_offset: int, endian: str) -> bytes:
    pieces = _flatten_pieces(root_piece)
    offsets: dict[int, int] = {}
    current_offset = start_offset
    for piece in pieces:
        offsets[id(piece)] = current_offset
        current_offset += len(piece.data)

    for piece in pieces:
        for patch_offset, child_piece in piece.patches:
            child_offset = offsets[id(child_piece)]
            piece.data[patch_offset : patch_offset + 4] = _pack_u32(child_offset, endian)

    return b"".join(bytes(piece.data) for piece in pieces)


def _decode_ifd_entry(
    stream: BinaryIO,
    *,
    state: _DecodeState,
    index: int,
) -> dict[str, Any]:
    _, endian = _normalize_byte_order(state.byte_order)
    scalar_formats = _endian_formats(endian)
    entry_formats = _ifd_entry_fmt(endian)
    context = state.context

    with context.inspect_scope(stream, index, state.fmt, None) as entry_node:
        tag = decode_child_stream(stream, entry_formats["tag"], context=context, key="tag")
        typ = decode_child_stream(stream, entry_formats["type"], context=context, key="type")
        count = decode_child_stream(stream, entry_formats["count"], context=context, key="count")

        value_field_start = stream.tell()
        value_field = read_exactly(stream, 4)

        item_size = TYPE_SIZES.get(typ)
        if item_size is None:
            raise ValueError(f"Unsupported EXIF type: {typ}")

        data_length = item_size * count
        if tag in IFD_POINTER_TAGS and typ == ExifType.LONG and count == 1:
            stream.seek(value_field_start)
            value = Pointer(
                offset=scalar_formats["u32"],
                fmt=_IfdFormat(
                    fmt=state.fmt,
                    byte_order=state.byte_order,
                    base_offset=state.base_offset,
                    payload_length=state.payload_length,
                    seen=state.seen,
                ),
                base=state.base_offset,
                allow_null=True,
                null_value=0,
                offset_key="offset",
                value_key="value",
                validate_target=lambda absolute_offset: _validate_absolute_offset(
                    absolute_offset,
                    payload_length=state.payload_length,
                    message="EXIF IFD offset is out of range",
                ),
            ).decode(stream, context=context)
        elif data_length <= 4:
            raw = value_field[:data_length]
            value = _decode_value_bytes(typ, count, raw, endian)
            if not _inspect_decoded_value(
                raw,
                value_fmt=_value_payload_fmt(typ, count, endian),
                value=value,
                start_offset=value_field_start,
                context=context,
            ):
                context.inspect_leaf(stream, "value", types.Bytes(4), value, value_field_start)
        else:
            value_offset = decode(value_field, scalar_formats["u32"])
            context.inspect_leaf(
                stream, "offset", scalar_formats["u32"], value_offset, value_field_start
            )
            absolute_offset = state.base_offset + value_offset
            if absolute_offset + data_length > state.payload_length:
                raise ValueError("EXIF entry value exceeds payload length")
            with seek_to(stream, absolute_offset):
                raw_start = stream.tell()
                raw = read_exactly(stream, data_length)
                value = _decode_value_bytes(typ, count, raw, endian)
                if not _inspect_decoded_value(
                    raw,
                    value_fmt=_value_payload_fmt(typ, count, endian),
                    value=value,
                    start_offset=raw_start,
                    context=context,
                ):
                    context.inspect_leaf(
                        stream, "value", types.Bytes(data_length), value, raw_start
                    )

        entry = {"tag": tag, "type": typ, "count": count, "value": value}
        if entry_node:
            entry_node.value = entry
        return entry


def _decode_ifd(
    stream: BinaryIO,
    *,
    state: _DecodeState,
    key: str,
) -> dict[str, Any]:
    with state.context.inspect_scope(stream, key, state.fmt, None) as ifd_node:
        ifd = _decode_ifd_body(stream, state=state, context=state.context)
        if ifd_node:
            ifd_node.value = ifd
        return ifd


def _decode_ifd_body(
    stream: BinaryIO,
    *,
    state: _DecodeState,
    context: Context,
) -> dict[str, Any]:
    _, endian = _normalize_byte_order(state.byte_order)
    scalar_formats = _endian_formats(endian)
    offset = stream.tell() - state.base_offset
    if offset in state.seen:
        raise ValueError("Circular EXIF IFD reference detected")
    state.seen.add(offset)

    entry_count = decode_child_stream(
        stream,
        scalar_formats["u16"],
        context=context,
        key="entry_count",
    )

    entries = [
        _decode_ifd_entry(
            stream,
            state=state,
            index=i,
        )
        for i in range(entry_count)
    ]

    next_ifd = Pointer(
        offset=scalar_formats["u32"],
        fmt=_IfdFormat(
            fmt=state.fmt,
            byte_order=state.byte_order,
            base_offset=state.base_offset,
            payload_length=state.payload_length,
            seen=state.seen,
        ),
        base=state.base_offset,
        allow_null=True,
        null_value=None,
        offset_key="next_ifd_offset",
        value_key="next_ifd",
        validate_target=lambda absolute_offset: _validate_absolute_offset(
            absolute_offset,
            payload_length=state.payload_length,
            message="EXIF IFD0 offset is out of range",
        ),
    ).decode(stream, context=context)

    return {"entries": entries, "next_ifd": next_ifd}


def _decode_exif_payload(
    payload: bytes,
    *,
    fmt: Any,
    include_header: bool,
    context: Context,
) -> dict[str, Any]:
    stream = BytesIO(payload)
    base_offset = 0

    if payload.startswith(EXIF_HEADER):
        decode_child_stream(stream, EXIF_HEADER_FMT, context=context, key="app1_header")
        base_offset = stream.tell()
    elif include_header:
        raise ValueError("Missing EXIF APP1 header")

    if len(payload) - stream.tell() < 8:
        raise ValueError("EXIF payload is too short")

    with context.inspect_scope(stream, "header", fmt, None) as header_node:
        byte_order = decode_child_stream(stream, types.Bytes(2), context=context, key="byte_order")

        _, endian = _normalize_byte_order(byte_order)
        scalar_formats = _endian_formats(endian)

        magic = decode_child_stream(stream, scalar_formats["u16"], context=context, key="magic")
        if magic != TIFF_MAGIC:
            raise ValueError("Invalid EXIF TIFF magic")

        ifd0_offset = decode_child_stream(
            stream,
            scalar_formats["u32"],
            context=context,
            key="ifd0_offset",
        )
        if header_node:
            header_node.value = {
                "byte_order": byte_order,
                "magic": magic,
                "ifd0_offset": ifd0_offset,
            }

    absolute_ifd0_offset = base_offset + ifd0_offset
    if absolute_ifd0_offset >= len(payload):
        raise ValueError("EXIF IFD0 offset is out of range")

    stream.seek(absolute_ifd0_offset)
    state = _DecodeState(
        fmt=fmt,
        byte_order=byte_order,
        context=context,
        base_offset=base_offset,
        payload_length=len(payload),
        seen=set(),
    )
    ifd0 = _decode_ifd(stream, state=state, key="ifd0")
    return {"byte_order": byte_order, "ifd0": ifd0}


@dataclass(frozen=True, slots=True)
class Exif:
    size: ClassVar[EllipsisType] = ...
    include_header: bool = True

    def encode(self, stream: BinaryIO, value: dict[str, Any], *, context: Context) -> None:
        byte_order = value.get("byte_order", b"II")
        byte_order_bytes, endian = _normalize_byte_order(byte_order)
        header_fmt = _tiff_header_fmt(byte_order)
        ifd0 = value.get("ifd0")
        if not isinstance(ifd0, dict):
            raise TypeError("EXIF value must include an 'ifd0' mapping")

        ifd0_piece = _build_ifd_piece(ifd0, byte_order)
        payload = bytearray()
        if self.include_header:
            payload.extend(EXIF_HEADER)
        payload.extend(
            encode(
                {
                    "byte_order": byte_order_bytes,
                    "magic": TIFF_MAGIC,
                    "ifd0_offset": 8,
                },
                header_fmt,
            )
        )
        payload.extend(_patch_offsets(ifd0_piece, start_offset=8, endian=endian))
        write_all(stream, payload)
        if context.inspect:
            _decode_exif_payload(
                bytes(payload),
                fmt=self,
                include_header=self.include_header,
                context=context,
            )

    def decode(self, stream: BinaryIO, *, context: Context) -> dict[str, Any]:
        payload = stream.read()
        return _decode_exif_payload(
            payload,
            fmt=self,
            include_header=self.include_header,
            context=context,
        )


IMG_PATH = Path(__file__).parent / "sample.jpg"


def _normalize(value: object) -> object:
    if isinstance(value, list):
        return [
            _normalize(item)
            for item in value
            if not (isinstance(item, dict) and item.get("tag") == 37500)
        ]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


SAMPLE_DATA = {
    "byte_order": b"MM",
    "ifd0": {
        "entries": [
            {"tag": IfdTag.MAKE, "type": ExifType.ASCII, "count": 6, "value": "Apple"},
            {
                "tag": IfdTag.MODEL,
                "type": ExifType.ASCII,
                "count": 14,
                "value": "iPhone 15 Pro",
            },
            {"tag": IfdTag.ORIENTATION, "type": ExifType.SHORT, "count": 1, "value": 1},
            {
                "tag": IfdTag.X_RESOLUTION,
                "type": ExifType.RATIONAL,
                "count": 1,
                "value": (72, 1),
            },
            {
                "tag": IfdTag.Y_RESOLUTION,
                "type": ExifType.RATIONAL,
                "count": 1,
                "value": (72, 1),
            },
            {"tag": IfdTag.RESOLUTION_UNIT, "type": ExifType.SHORT, "count": 1, "value": 2},
            {
                "tag": IfdTag.SOFTWARE,
                "type": ExifType.ASCII,
                "count": 7,
                "value": "18.7.2",
            },
            {
                "tag": IfdTag.DATE_TIME,
                "type": ExifType.ASCII,
                "count": 20,
                "value": "2026:03:04 10:08:49",
            },
            {"tag": 316, "type": ExifType.ASCII, "count": 14, "value": "iPhone 15 Pro"},
            {"tag": IfdTag.YCBCR_POSITIONING, "type": ExifType.SHORT, "count": 1, "value": 1},
            {
                "tag": IfdTag.EXIF_IFD,
                "type": ExifType.LONG,
                "count": 1,
                "value": {
                    "entries": [
                        {
                            "tag": IfdTag.EXPOSURE_TIME,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (1, 723),
                        },
                        {
                            "tag": IfdTag.F_NUMBER,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (1244236, 699009),
                        },
                        {
                            "tag": IfdTag.EXPOSURE_PROGRAM,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 2,
                        },
                        {
                            "tag": IfdTag.ISO_SPEED_RATINGS,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 80,
                        },
                        {
                            "tag": IfdTag.EXIF_VERSION,
                            "type": ExifType.UNDEFINED,
                            "count": 4,
                            "value": b"0232",
                        },
                        {
                            "tag": IfdTag.DATE_TIME_ORIGINAL,
                            "type": ExifType.ASCII,
                            "count": 20,
                            "value": "2026:03:04 10:08:49",
                        },
                        {
                            "tag": IfdTag.DATE_TIME_DIGITIZED,
                            "type": ExifType.ASCII,
                            "count": 20,
                            "value": "2026:03:04 10:08:49",
                        },
                        {
                            "tag": IfdTag.OFFSET_TIME,
                            "type": ExifType.ASCII,
                            "count": 7,
                            "value": "-06:00",
                        },
                        {
                            "tag": IfdTag.OFFSET_TIME_ORIGINAL,
                            "type": ExifType.ASCII,
                            "count": 7,
                            "value": "-06:00",
                        },
                        {
                            "tag": IfdTag.OFFSET_TIME_DIGITIZED,
                            "type": ExifType.ASCII,
                            "count": 7,
                            "value": "-06:00",
                        },
                        {
                            "tag": IfdTag.COMPONENTS_CONFIGURATION,
                            "type": ExifType.UNDEFINED,
                            "count": 4,
                            "value": b"\x01\x02\x03\x00",
                        },
                        {
                            "tag": IfdTag.SHUTTER_SPEED_VALUE,
                            "type": ExifType.SRATIONAL,
                            "count": 1,
                            "value": (37247, 3922),
                        },
                        {
                            "tag": IfdTag.APERTURE_VALUE,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (42657, 25639),
                        },
                        {
                            "tag": IfdTag.BRIGHTNESS_VALUE,
                            "type": ExifType.SRATIONAL,
                            "count": 1,
                            "value": (130919, 18705),
                        },
                        {
                            "tag": IfdTag.EXPOSURE_BIAS_VALUE,
                            "type": ExifType.SRATIONAL,
                            "count": 1,
                            "value": (0, 1),
                        },
                        {
                            "tag": IfdTag.METERING_MODE,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 5,
                        },
                        {"tag": IfdTag.FLASH, "type": ExifType.SHORT, "count": 1, "value": 16},
                        {
                            "tag": IfdTag.FOCAL_LENGTH,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (251773, 37217),
                        },
                        {
                            "tag": 37396,
                            "type": ExifType.SHORT,
                            "count": 4,
                            "value": [2849, 2137, 3291, 1884],
                        },
                        {
                            "tag": IfdTag.SUBSEC_TIME_ORIGINAL,
                            "type": ExifType.ASCII,
                            "count": 4,
                            "value": "610",
                        },
                        {
                            "tag": IfdTag.SUBSEC_TIME_DIGITIZED,
                            "type": ExifType.ASCII,
                            "count": 4,
                            "value": "610",
                        },
                        {
                            "tag": IfdTag.FLASHPIX_VERSION,
                            "type": ExifType.UNDEFINED,
                            "count": 4,
                            "value": b"0100",
                        },
                        {
                            "tag": IfdTag.COLOR_SPACE,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 65535,
                        },
                        {
                            "tag": IfdTag.PIXEL_X_DIMENSION,
                            "type": ExifType.LONG,
                            "count": 1,
                            "value": 2048,
                        },
                        {
                            "tag": IfdTag.PIXEL_Y_DIMENSION,
                            "type": ExifType.LONG,
                            "count": 1,
                            "value": 1536,
                        },
                        {
                            "tag": IfdTag.SENSING_METHOD,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 2,
                        },
                        {
                            "tag": IfdTag.SCENE_TYPE,
                            "type": ExifType.UNDEFINED,
                            "count": 1,
                            "value": b"\x01",
                        },
                        {
                            "tag": IfdTag.EXPOSURE_MODE,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 0,
                        },
                        {
                            "tag": IfdTag.WHITE_BALANCE,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 0,
                        },
                        {
                            "tag": IfdTag.FOCAL_LENGTH_IN_35MM_FILM,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 24,
                        },
                        {
                            "tag": IfdTag.SCENE_CAPTURE_TYPE,
                            "type": ExifType.SHORT,
                            "count": 1,
                            "value": 0,
                        },
                        {
                            "tag": 42034,
                            "type": ExifType.RATIONAL,
                            "count": 4,
                            "value": [(1551800, 699009), (9, 1), (1244236, 699009), (14, 5)],
                        },
                        {
                            "tag": IfdTag.LENS_MAKE,
                            "type": ExifType.ASCII,
                            "count": 6,
                            "value": "Apple",
                        },
                        {
                            "tag": IfdTag.LENS_MODEL,
                            "type": ExifType.ASCII,
                            "count": 48,
                            "value": "iPhone 15 Pro back triple camera 6.765mm f/1.78",
                        },
                        {"tag": 42080, "type": ExifType.SHORT, "count": 1, "value": 2},
                    ],
                    "next_ifd": None,
                },
            },
            {
                "tag": IfdTag.GPS_IFD,
                "type": ExifType.LONG,
                "count": 1,
                "value": {
                    "entries": [
                        {
                            "tag": IfdTag.GPS_LATITUDE_REF,
                            "type": ExifType.ASCII,
                            "count": 2,
                            "value": "N",
                        },
                        {
                            "tag": IfdTag.GPS_LATITUDE,
                            "type": ExifType.RATIONAL,
                            "count": 3,
                            "value": [(9, 1), (22, 1), (5229, 100)],
                        },
                        {
                            "tag": IfdTag.GPS_LONGITUDE_REF,
                            "type": ExifType.ASCII,
                            "count": 2,
                            "value": "W",
                        },
                        {
                            "tag": IfdTag.GPS_LONGITUDE,
                            "type": ExifType.RATIONAL,
                            "count": 3,
                            "value": [(84, 1), (8, 1), (4462, 100)],
                        },
                        {
                            "tag": IfdTag.GPS_ALTITUDE_REF,
                            "type": ExifType.BYTE,
                            "count": 1,
                            "value": 1,
                        },
                        {
                            "tag": IfdTag.GPS_ALTITUDE,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (65921, 12847),
                        },
                        {
                            "tag": IfdTag.GPS_TIME_STAMP,
                            "type": ExifType.RATIONAL,
                            "count": 3,
                            "value": [(16, 1), (8, 1), (46, 1)],
                        },
                        {"tag": 12, "type": ExifType.ASCII, "count": 2, "value": "K"},
                        {
                            "tag": 13,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (0, 1),
                        },
                        {"tag": 16, "type": ExifType.ASCII, "count": 2, "value": "M"},
                        {
                            "tag": 17,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (309661, 1467),
                        },
                        {"tag": 23, "type": ExifType.ASCII, "count": 2, "value": "M"},
                        {
                            "tag": 24,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (309661, 1467),
                        },
                        {
                            "tag": IfdTag.GPS_DATE_STAMP,
                            "type": ExifType.ASCII,
                            "count": 11,
                            "value": "2026:03:04",
                        },
                        {
                            "tag": 31,
                            "type": ExifType.RATIONAL,
                            "count": 1,
                            "value": (42506, 2099),
                        },
                    ],
                    "next_ifd": None,
                },
            },
        ],
        "next_ifd": {
            "entries": [
                {"tag": IfdTag.COMPRESSION, "type": ExifType.SHORT, "count": 1, "value": 6},
                {
                    "tag": IfdTag.X_RESOLUTION,
                    "type": ExifType.RATIONAL,
                    "count": 1,
                    "value": (72, 1),
                },
                {
                    "tag": IfdTag.Y_RESOLUTION,
                    "type": ExifType.RATIONAL,
                    "count": 1,
                    "value": (72, 1),
                },
                {"tag": IfdTag.RESOLUTION_UNIT, "type": ExifType.SHORT, "count": 1, "value": 2},
                {
                    "tag": IfdTag.THUMBNAIL_OFFSET,
                    "type": ExifType.LONG,
                    "count": 1,
                    "value": 3040,
                },
                {
                    "tag": IfdTag.THUMBNAIL_LENGTH,
                    "type": ExifType.LONG,
                    "count": 1,
                    "value": 10955,
                },
            ],
            "next_ifd": None,
        },
    },
}


def test_exif_inspect_has_nested_ifd_nodes() -> None:
    fmt = Exif()
    value = {
        "byte_order": b"II",
        "ifd0": {
            "entries": [
                {"tag": IfdTag.IMAGE_WIDTH, "type": ExifType.LONG, "count": 1, "value": 640},
                {
                    "tag": IfdTag.EXIF_IFD,
                    "type": ExifType.LONG,
                    "count": 1,
                    "value": {
                        "entries": [
                            {
                                "tag": IfdTag.EXPOSURE_TIME,
                                "type": ExifType.RATIONAL,
                                "count": 1,
                                "value": (1, 125),
                            }
                        ],
                        "next_ifd": None,
                    },
                },
            ],
            "next_ifd": {
                "entries": [
                    {"tag": IfdTag.IMAGE_LENGTH, "type": ExifType.LONG, "count": 1, "value": 480}
                ],
                "next_ifd": None,
            },
        },
    }

    encoded, encode_tree = encode_inspect(value, fmt)
    decoded, decode_tree = decode_inspect(encoded, fmt)

    assert decoded == value
    assert decode_tree == encode_tree
    assert decoded["ifd0"]["entries"][0]["tag"] is IfdTag.IMAGE_WIDTH
    assert decoded["ifd0"]["entries"][0]["type"] is ExifType.LONG
    assert decoded["ifd0"]["entries"][1]["tag"] is IfdTag.EXIF_IFD
    assert decoded["ifd0"]["entries"][1]["type"] is ExifType.LONG

    root_keys = [child.key for child in encode_tree.children]
    assert root_keys == ["app1_header", "header", "ifd0"]

    header_keys = [child.key for child in encode_tree["header"].children]
    assert header_keys == ["byte_order", "magic", "ifd0_offset"]

    ifd0_keys = [child.key for child in encode_tree["ifd0"].children]
    assert ifd0_keys == ["entry_count", 0, 1, "next_ifd_offset", "next_ifd"]

    nested_ifd_entry = encode_tree["ifd0"][1]
    assert [child.key for child in nested_ifd_entry.children] == [
        "tag",
        "type",
        "count",
        "offset",
        "value",
    ]

    nested_ifd = nested_ifd_entry["value"]
    assert [child.key for child in nested_ifd.children] == ["entry_count", 0, "next_ifd_offset"]

    nested_value = nested_ifd[0]["value"]
    assert [child.key for child in nested_value.children] == [0, 1]

    next_ifd = encode_tree["ifd0"]["next_ifd"]
    assert [child.key for child in next_ifd.children] == ["entry_count", 0, "next_ifd_offset"]


def test_exif_inspect_decodes_repeated_rational_value_nodes() -> None:
    fmt = Exif()
    value = {
        "byte_order": b"II",
        "ifd0": {
            "entries": [
                {
                    "tag": IfdTag.GPS_IFD,
                    "type": ExifType.LONG,
                    "count": 1,
                    "value": {
                        "entries": [
                            {
                                "tag": IfdTag.GPS_LONGITUDE,
                                "type": ExifType.RATIONAL,
                                "count": 3,
                                "value": [(87, 1), (54, 1), (1224, 100)],
                            }
                        ],
                        "next_ifd": None,
                    },
                }
            ],
            "next_ifd": None,
        },
    }

    _, tree = decode_inspect(encode_inspect(value, fmt)[0], fmt)

    gps_value = tree["ifd0"][0]["value"][0]["value"]
    assert gps_value.value == [(87, 1), (54, 1), (1224, 100)]
    assert [child.key for child in gps_value.children] == [0, 1, 2]
    assert [child.key for child in gps_value[0].children] == [0, 1]


def test_exif_sample_photo() -> None:
    fmt = Exif()
    with IMG_PATH.open("rb") as stream:
        original_payload_length = _seek_exif_app1(stream)
        decoded = decode_stream(stream, fmt)

    assert _normalize(decoded) == _normalize(SAMPLE_DATA)

    reencoded, en_tree = encode_inspect(decoded, fmt)
    assert len(reencoded) < original_payload_length
    result, de_tree = decode_inspect(reencoded, fmt)
    assert de_tree == en_tree
    print("encode tree:")
    print(format_tree(en_tree))
    print("decode tree:")
    print(format_tree(de_tree))
    assert _normalize(result) == _normalize(decoded)
