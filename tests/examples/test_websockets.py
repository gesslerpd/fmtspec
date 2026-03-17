"""WebSocket frame format example using fmtspec.types.

Mirrors the Kaitai Struct websocket specification at:
https://formats.kaitai.io/websocket/

This intentionally follows the Kaitai model, including its 32-bit
``len_payload_extended_2`` field for primary length ``127``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from io import BytesIO
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from fmtspec import (
    DecodeError,
    EncodeError,
    decode,
    decode_inspect,
    encode,
    encode_inspect,
    format_tree,
    types,
)
from fmtspec.stream import decode_stream, encode_stream

if TYPE_CHECKING:
    from types import EllipsisType


class Opcode(IntEnum):
    CONTINUATION = 0
    TEXT = 1
    BINARY = 2

    CLOSE = 8
    PING = 9
    PONG = 0xA


FRAME_HEADER_FLAGS_FMT = types.Bitfields(
    fields={
        "opcode": types.Bitfield(bits=4, offset=0, enum=Opcode),
        "finished": types.Bitfield(bits=1, offset=7),
    }
)

FRAME_HEADER_LENGTH_FMT = types.Bitfields(
    fields={
        "len_payload_primary": types.Bitfield(bits=7, offset=0),
        "is_masked": types.Bitfield(bits=1, offset=7),
    }
)


def _payload_wire_length(payload: Any, *, is_text: bool) -> int:
    buf = BytesIO()
    if is_text:
        types.Str().encode(payload, buf)
    else:
        types.Bytes().encode(bytes(payload), buf)
    return len(buf.getvalue())


def _payload_fmt(*, is_text: bool, size: int):
    return types.Str(size) if is_text else types.Bytes(size)


def _encode_payload(payload: Any, stream, *, is_text: bool, context, key: str) -> None:
    size = _payload_wire_length(payload, is_text=is_text)
    payload_fmt = _payload_fmt(is_text=is_text, size=size)
    encode_stream(payload, payload_fmt, stream, context=context, key=key)


def _decode_payload(stream, *, is_text: bool, size: int, context, key: str) -> str | bytes:
    payload_fmt = _payload_fmt(is_text=is_text, size=size)
    return decode_stream(stream, payload_fmt, context=context, key=key)


@dataclass(frozen=True, slots=True)
class FrameHeader:
    size: ClassVar[EllipsisType] = ...

    def encode(self, value: dict[str, Any], stream, *, context) -> None:
        payload_len = value["len_payload"]
        if payload_len < 0:
            raise ValueError("Payload length must be non-negative")

        if payload_len <= 125:
            len_payload_primary = payload_len
            extended_key = None
        elif payload_len <= 0xFFFF:
            len_payload_primary = 126
            extended_key = "len_payload_extended_1"
        elif payload_len <= 0xFFFFFFFF:
            len_payload_primary = 127
            extended_key = "len_payload_extended_2"
        else:
            raise ValueError("Payload length exceeds Kaitai websocket u4 extended size")

        flags = {
            "opcode": value["opcode"],
            "finished": value["finished"],
        }
        is_masked = value.get("is_masked", False)
        length_info = {
            "len_payload_primary": len_payload_primary,
            "is_masked": is_masked,
        }

        context.push_path("flags")
        encode_stream(flags, FRAME_HEADER_FLAGS_FMT, stream, context=context, key="flags")
        context.pop_path()

        context.push_path("length")
        encode_stream(length_info, FRAME_HEADER_LENGTH_FMT, stream, context=context, key="length")
        context.pop_path()

        if extended_key == "len_payload_extended_1":
            context.push_path(extended_key)
            encode_stream(payload_len, types.u16, stream, context=context, key=extended_key)
            context.pop_path()
        elif extended_key == "len_payload_extended_2":
            context.push_path(extended_key)
            encode_stream(payload_len, types.u32, stream, context=context, key=extended_key)
            context.pop_path()

        if is_masked:
            if "mask_key" not in value:
                raise ValueError("Masked frames require mask_key")
            context.push_path("mask_key")
            encode_stream(value["mask_key"], types.u32, stream, context=context, key="mask_key")
            context.pop_path()

    def decode(self, stream, *, context) -> dict[str, Any]:
        context.push_path("flags")
        flags = decode_stream(stream, FRAME_HEADER_FLAGS_FMT, context=context, key="flags")
        context.pop_path()

        context.push_path("length")
        length_info = decode_stream(stream, FRAME_HEADER_LENGTH_FMT, context=context, key="length")
        context.pop_path()

        payload_len_primary = length_info["len_payload_primary"]

        header = {
            "opcode": Opcode(flags["opcode"]),
            "finished": flags["finished"],
            "len_payload_primary": payload_len_primary,
            "is_masked": length_info["is_masked"],
        }

        if payload_len_primary <= 125:
            payload_len = payload_len_primary
        elif payload_len_primary == 126:
            context.push_path("len_payload_extended_1")
            extended = decode_stream(
                stream, types.u16, context=context, key="len_payload_extended_1"
            )
            context.pop_path()
            header["len_payload_extended_1"] = extended
            payload_len = extended
        else:
            context.push_path("len_payload_extended_2")
            extended = decode_stream(
                stream, types.u32, context=context, key="len_payload_extended_2"
            )
            context.pop_path()
            header["len_payload_extended_2"] = extended
            payload_len = extended

        if header["is_masked"]:
            context.push_path("mask_key")
            header["mask_key"] = decode_stream(stream, types.u32, context=context, key="mask_key")
            context.pop_path()

        header["len_payload"] = payload_len
        return header


@dataclass(frozen=True, slots=True)
class InitialFrame:
    size: ClassVar[EllipsisType] = ...
    header_fmt: FrameHeader = FrameHeader()

    def encode(self, value: dict[str, Any], stream, *, context) -> None:
        header = dict(value["header"])
        is_text = header["opcode"] == Opcode.TEXT
        payload_key = "payload"
        if payload_key not in value:
            raise ValueError(f"Missing {payload_key!r} for initial frame")

        payload = value[payload_key]
        header["len_payload"] = _payload_wire_length(payload, is_text=is_text)
        context.push_path("header")
        encode_stream(header, self.header_fmt, stream, context=context, key="header")
        context.pop_path()

        context.push_path(payload_key)
        _encode_payload(payload, stream, is_text=is_text, context=context, key=payload_key)
        context.pop_path()

    def decode(self, stream, *, context) -> dict[str, Any]:
        context.push_path("header")
        header = decode_stream(stream, self.header_fmt, context=context, key="header")
        context.pop_path()

        is_text = header["opcode"] == Opcode.TEXT
        payload_key = "payload"
        context.push_path(payload_key)
        payload = _decode_payload(
            stream,
            is_text=is_text,
            size=header["len_payload"],
            context=context,
            key=payload_key,
        )
        context.pop_path()
        return {
            "header": header,
            payload_key: payload,
        }


@dataclass(frozen=True, slots=True)
class DataFrame:
    size: ClassVar[EllipsisType] = ...
    text_mode: bool
    header_fmt: FrameHeader = FrameHeader()

    def encode(self, value: dict[str, Any], stream, *, context) -> None:
        header = dict(value["header"])
        payload_key = "payload"
        if payload_key not in value:
            raise ValueError(f"Missing {payload_key!r} for trailing dataframe")

        payload = value[payload_key]
        header["len_payload"] = _payload_wire_length(payload, is_text=self.text_mode)
        context.push_path("header")
        encode_stream(header, self.header_fmt, stream, context=context, key="header")
        context.pop_path()

        context.push_path(payload_key)
        _encode_payload(payload, stream, is_text=self.text_mode, context=context, key=payload_key)
        context.pop_path()

    def decode(self, stream, *, context) -> dict[str, Any]:
        context.push_path("header")
        header = decode_stream(stream, self.header_fmt, context=context, key="header")
        context.pop_path()

        payload_key = "payload"
        context.push_path(payload_key)
        payload = _decode_payload(
            stream,
            is_text=self.text_mode,
            size=header["len_payload"],
            context=context,
            key=payload_key,
        )
        context.pop_path()
        return {
            "header": header,
            payload_key: payload,
        }


@dataclass(frozen=True, slots=True)
class WebSocket:
    size: ClassVar[EllipsisType] = ...
    initial_frame_fmt: InitialFrame = InitialFrame()

    def encode(self, value: dict[str, Any], stream, *, context) -> None:
        initial_frame = value["initial_frame"]
        trailing_frames = value.get("trailing_frames", [])

        context.push_path("initial_frame")
        encode_stream(
            initial_frame, self.initial_frame_fmt, stream, context=context, key="initial_frame"
        )
        context.pop_path()

        initial_header = initial_frame["header"]
        initial_finished = initial_header["finished"]
        if initial_finished:
            if trailing_frames:
                raise ValueError("Trailing frames are only valid when initial_frame is unfinished")
            return

        if not trailing_frames:
            raise ValueError("Fragmented websocket message requires trailing_frames")

        text_mode = initial_header["opcode"] == Opcode.TEXT
        trailing_fmt = DataFrame(text_mode=text_mode)
        trailing_frames_fmt = types.array(trailing_fmt)

        context.push_path("trailing_frames")
        encode_stream(
            trailing_frames, trailing_frames_fmt, stream, context=context, key="trailing_frames"
        )
        context.pop_path()

        if not trailing_frames[-1]["header"]["finished"]:
            raise ValueError("Trailing frames must terminate with a finished frame")

    def decode(self, stream, *, context) -> dict[str, Any]:
        result: dict[str, Any] = {
            "initial_frame": None,
        }
        context.push_path("initial_frame")
        result["initial_frame"] = decode_stream(
            stream,
            self.initial_frame_fmt,
            context=context,
            key="initial_frame",
        )
        context.pop_path()

        initial_header = result["initial_frame"]["header"]
        if initial_header["finished"]:
            return result

        text_mode = initial_header["opcode"] == Opcode.TEXT
        trailing_fmt = DataFrame(text_mode=text_mode)
        trailing_frames_fmt = types.array(trailing_fmt)
        # context.push_path("trailing_frames")
        result["trailing_frames"] = decode_stream(
            stream, trailing_frames_fmt, context=context, key="trailing_frames"
        )
        # context.pop_path()
        return result


websocket_fmt = WebSocket()


def test_single_text_frame_roundtrip() -> None:
    message = {
        "initial_frame": {
            "header": {
                "finished": True,
                "opcode": Opcode.TEXT,
                "is_masked": False,
            },
            "payload": "Hello",
        }
    }

    encoded = encode(message, websocket_fmt)
    assert encoded == b"\x81\x05Hello"

    decoded = decode(encoded, websocket_fmt)
    assert decoded == {
        "initial_frame": {
            "header": {
                "finished": True,
                "opcode": Opcode.TEXT,
                "is_masked": False,
                "len_payload_primary": 5,
                "len_payload": 5,
            },
            "payload": "Hello",
        }
    }
    assert encode(decoded, websocket_fmt) == encoded


def test_fragmented_text_message_roundtrip() -> None:
    message = {
        "initial_frame": {
            "header": {
                "finished": False,
                "opcode": Opcode.TEXT,
                "is_masked": False,
            },
            "payload": "Hel",
        },
        "trailing_frames": [
            {
                "header": {
                    "finished": True,
                    "opcode": Opcode.CONTINUATION,
                    "is_masked": False,
                },
                "payload": "lo",
            }
        ],
    }

    encoded = encode(message, websocket_fmt)
    _, tree = encode_inspect(message, websocket_fmt)
    print()
    print(format_tree(tree))
    assert encoded == b"\x01\x03Hel\x80\x02lo"

    decoded = decode(encoded, websocket_fmt)

    _, dec_tree = decode_inspect(encoded, websocket_fmt)
    print()
    print(format_tree(dec_tree))
    # assert format_tree(dec_tree) == format_tree(tree)
    assert decoded["initial_frame"]["header"]["finished"] is False
    assert decoded["initial_frame"]["header"]["opcode"] == Opcode.TEXT
    assert decoded["initial_frame"]["payload"] == "Hel"
    assert decoded["trailing_frames"] == [
        {
            "header": {
                "finished": True,
                "opcode": Opcode.CONTINUATION,
                "is_masked": False,
                "len_payload_primary": 2,
                "len_payload": 2,
            },
            "payload": "lo",
        }
    ]


def test_fragmented_text_message_inspect_tree() -> None:
    message = {
        "initial_frame": {
            "header": {
                "finished": False,
                "opcode": Opcode.TEXT,
                "is_masked": False,
            },
            "payload": "Hel",
        },
        "trailing_frames": [
            {
                "header": {
                    "finished": True,
                    "opcode": Opcode.CONTINUATION,
                    "is_masked": False,
                },
                "payload": "lo",
            }
        ],
    }

    encoded, encode_tree = encode_inspect(message, websocket_fmt)
    assert encoded == b"\x01\x03Hel\x80\x02lo"
    assert [child.key for child in encode_tree.children] == ["initial_frame", "trailing_frames"]

    initial_frame_node = encode_tree.children[0]
    trailing_frames_node = encode_tree.children[1]
    assert [child.key for child in initial_frame_node.children] == ["header", "payload"]
    assert [child.key for child in trailing_frames_node.children] == [0]
    assert [child.key for child in trailing_frames_node.children[0].children] == [
        "header",
        "payload",
    ]

    formatted_encode_tree = format_tree(encode_tree, only_leaf=False)
    assert "[initial_frame]" in formatted_encode_tree
    assert "[trailing_frames]" in formatted_encode_tree
    assert "[payload]" in formatted_encode_tree

    decoded, decode_tree = decode_inspect(encoded, websocket_fmt)
    assert decoded["initial_frame"]["payload"] == "Hel"
    assert decoded["trailing_frames"][0]["payload"] == "lo"
    assert [child.key for child in decode_tree.children] == ["initial_frame", "trailing_frames"]
    assert [child.key for child in decode_tree.children[1].children] == [0]

    formatted_decode_tree = format_tree(decode_tree, only_leaf=False)
    assert "[initial_frame]" in formatted_decode_tree
    assert "[trailing_frames]" in formatted_decode_tree
    assert "[payload]" in formatted_decode_tree


def test_binary_frame_with_16bit_extended_length() -> None:
    payload = b"A" * 126
    message = {
        "initial_frame": {
            "header": {
                "finished": True,
                "opcode": Opcode.BINARY,
                "is_masked": False,
            },
            "payload": payload,
        }
    }

    encoded = encode(message, websocket_fmt)
    assert encoded[:4] == b"\x82\x7e\x00\x7e"
    assert encoded[4:] == payload

    decoded = decode(encoded, websocket_fmt)
    header = decoded["initial_frame"]["header"]
    assert header["opcode"] == Opcode.BINARY
    assert header["len_payload_primary"] == 126
    assert header["len_payload_extended_1"] == 126
    assert header["len_payload"] == 126
    assert decoded["initial_frame"]["payload"] == payload


def test_masked_binary_frame_with_32bit_extended_length() -> None:
    payload = bytes(range(256)) * 274
    mask_key = 0x11223344
    message = {
        "initial_frame": {
            "header": {
                "finished": True,
                "opcode": Opcode.BINARY,
                "is_masked": True,
                "mask_key": mask_key,
            },
            "payload": payload,
        }
    }

    encoded = encode(message, websocket_fmt)
    assert encoded[:6] == b"\x82\xff\x00\x01\x12\x00"
    assert encoded[6:10] == b"\x11\x22\x33\x44"

    decoded = decode(encoded, websocket_fmt)
    header = decoded["initial_frame"]["header"]
    assert header["is_masked"] is True
    assert header["len_payload_primary"] == 127
    assert header["len_payload_extended_2"] == len(payload)
    assert header["len_payload"] == len(payload)
    assert header["mask_key"] == mask_key
    assert decoded["initial_frame"]["payload"] == payload
    assert encode(decoded, websocket_fmt) == encoded


def test_fragmented_message_requires_trailing_frames() -> None:
    message = {
        "initial_frame": {
            "header": {
                "finished": False,
                "opcode": Opcode.TEXT,
                "is_masked": False,
            },
            "payload": "partial",
        }
    }

    with pytest.raises(EncodeError, match="requires trailing_frames"):
        encode(message, websocket_fmt)


def test_trailing_frames_must_end_with_finished_frame() -> None:
    message = {
        "initial_frame": {
            "header": {
                "finished": False,
                "opcode": Opcode.TEXT,
                "is_masked": False,
            },
            "payload": "Hel",
        },
        "trailing_frames": [
            {
                "header": {
                    "finished": False,
                    "opcode": Opcode.CONTINUATION,
                    "is_masked": False,
                },
                "payload": "lo",
            }
        ],
    }

    with pytest.raises(EncodeError, match="terminate with a finished frame"):
        encode(message, websocket_fmt)


def test_decode_fragmented_binary_message() -> None:
    data = b"\x02\x03bin\x80\x02xy"

    decoded = decode(data, websocket_fmt)

    assert decoded == {
        "initial_frame": {
            "header": {
                "finished": False,
                "opcode": Opcode.BINARY,
                "is_masked": False,
                "len_payload_primary": 3,
                "len_payload": 3,
            },
            "payload": b"bin",
        },
        "trailing_frames": [
            {
                "header": {
                    "finished": True,
                    "opcode": Opcode.CONTINUATION,
                    "is_masked": False,
                    "len_payload_primary": 2,
                    "len_payload": 2,
                },
                "payload": b"xy",
            }
        ],
    }


def test_decode_truncated_extended_payload_raises() -> None:
    data = b"\x82\x7e\x00\x7e" + (b"A" * 125)

    with pytest.raises(DecodeError, match="Expected 126 bytes, got 125"):
        decode(data, websocket_fmt)
