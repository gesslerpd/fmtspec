"""ZIP central-directory listing example using fmtspec.

This decoder intentionally reads only the end-of-central-directory record and
central-directory entries. It does not decode local file headers or file data.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar

from fmtspec import Context, format_tree, types
from fmtspec._core import _decode_stream_impl
from fmtspec._inspect import _attach_buffer_tree
from fmtspec.stream import decode_stream as decode_child_stream
from fmtspec.stream import read_exactly, seek_to

if TYPE_CHECKING:
    from types import EllipsisType


ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
ZIP_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
ZIP_UTF8_FLAG = 0x0800
ZIP_EOCD_MIN_SIZE = 22
ZIP_EOCD_MAX_TAIL = ZIP_EOCD_MIN_SIZE + 0xFFFF

ZIP_EOCD_FMT = {
    "signature": types.Literal(ZIP_EOCD_SIGNATURE),
    "disk_number": types.u16le,
    "central_dir_disk": types.u16le,
    "disk_entries": types.u16le,
    "total_entries": types.u16le,
    "central_dir_size": types.u32le,
    "central_dir_offset": types.u32le,
    "comment_length": types.u16le,
}

ZIP_CENTRAL_DIRECTORY_ENTRY_FMT = {
    "signature": types.Literal(ZIP_CENTRAL_DIRECTORY_SIGNATURE),
    "version_made_by": types.u16le,
    "version_needed": types.u16le,
    "flags": types.u16le,
    "compression_method": types.u16le,
    "last_mod_time": types.u16le,
    "last_mod_date": types.u16le,
    "crc32": types.u32le,
    "compressed_size": types.u32le,
    "uncompressed_size": types.u32le,
    "name_length": types.u16le,
    "extra_length": types.u16le,
    "comment_length": types.u16le,
    "disk_number_start": types.u16le,
    "internal_attrs": types.u16le,
    "external_attrs": types.u32le,
    "local_header_offset": types.u32le,
}


def _stream_size(stream: BinaryIO) -> int:
    current = stream.tell()
    end = stream.seek(0, io.SEEK_END)
    stream.seek(current)
    return end


def _find_end_of_central_directory(stream: BinaryIO) -> int:
    size = _stream_size(stream)
    max_search = min(size, ZIP_EOCD_MAX_TAIL)
    scanned = 0
    tail = b""

    while scanned < max_search:
        chunk_size = min(64, max_search - scanned)
        chunk_offset = size - scanned - chunk_size

        with seek_to(stream, chunk_offset):
            chunk = read_exactly(stream, chunk_size)

        tail = chunk + tail
        eocd_index = tail.rfind(ZIP_EOCD_SIGNATURE)
        if eocd_index >= 0:
            return chunk_offset + eocd_index

        scanned += chunk_size

    raise ValueError("ZIP end-of-central-directory record not found")


def _decode_zip_name(raw: bytes, *, flags: int) -> str:
    encoding = "utf-8" if flags & ZIP_UTF8_FLAG else "cp437"
    return raw.decode(encoding)


def _new_tree_node() -> dict[str, Any]:
    return {"dirs": {}, "files": []}


def _build_tree(names: list[str]) -> dict[str, Any]:
    root = _new_tree_node()

    for name in names:
        parts = [part for part in name.split("/") if part]
        if not parts:
            continue

        cursor = root
        for part in parts[:-1]:
            cursor = cursor["dirs"].setdefault(part, _new_tree_node())

        leaf = parts[-1]
        if name.endswith("/"):
            cursor["dirs"].setdefault(leaf, _new_tree_node())
        else:
            cursor["files"].append(leaf)

    return root


def _decode_central_directory_entry(
    stream: BinaryIO,
    *,
    context: Context,
    index: int,
) -> dict[str, Any]:
    with context.inspect_scope(stream, index, ZIP_CENTRAL_DIRECTORY_ENTRY_FMT, None) as node:
        context.push_path("header")
        header = decode_child_stream(
            stream,
            ZIP_CENTRAL_DIRECTORY_ENTRY_FMT,
            context=context,
            key="header",
        )
        context.pop_path()

        name_start = stream.tell()
        name_raw = read_exactly(stream, header["name_length"])
        name = _decode_zip_name(name_raw, flags=header["flags"])
        context.inspect_leaf(
            stream,
            "name",
            types.Bytes(header["name_length"]),
            name,
            name_start,
        )

        if header["extra_length"]:
            stream.seek(header["extra_length"], io.SEEK_CUR)
        if header["comment_length"]:
            stream.seek(header["comment_length"], io.SEEK_CUR)

        entry = {
            "name": name,
            "is_dir": name.endswith("/"),
            "compression_method": header["compression_method"],
            "compressed_size": header["compressed_size"],
            "uncompressed_size": header["uncompressed_size"],
            "local_header_offset": header["local_header_offset"],
        }
        if node:
            node.value = entry
        return entry


@dataclass(frozen=True, slots=True)
class ZipCentralDirectory:
    """Decode a ZIP archive by reading only central-directory metadata."""

    size: ClassVar[EllipsisType] = ...

    def encode(self, stream: BinaryIO, value: Any, *, context: Context) -> None:
        raise NotImplementedError("ZipCentralDirectory is a decode-only example")

    def decode(self, stream: BinaryIO, *, context: Context) -> dict[str, Any]:
        eocd_offset = _find_end_of_central_directory(stream)

        with seek_to(stream, eocd_offset):
            context.push_path("eocd")
            eocd = decode_child_stream(stream, ZIP_EOCD_FMT, context=context, key="eocd")
            context.pop_path()

            comment = b""
            if eocd["comment_length"]:
                comment = read_exactly(stream, eocd["comment_length"])

        if eocd["disk_number"] != 0 or eocd["central_dir_disk"] != 0:
            raise ValueError("Multi-disk ZIP archives are not supported")
        if eocd["disk_entries"] != eocd["total_entries"]:
            raise ValueError("Split ZIP central directories are not supported")
        if eocd["total_entries"] == 0xFFFF:
            raise ValueError("ZIP64 archives are not supported by this example")

        entries = []
        with seek_to(stream, eocd["central_dir_offset"]):
            context.push_path("entries")
            for index in range(eocd["total_entries"]):
                context.push_path(index)
                entry = _decode_central_directory_entry(stream, context=context, index=index)
                entries.append(entry)
                context.pop_path()
            context.pop_path()

        names = [entry["name"] for entry in entries]
        return {
            "entries": entries,
            "names": names,
            "tree": _build_tree(names),
            "comment": comment,
        }


ZIP_ARCHIVE = ZipCentralDirectory()


def test_zip_decoder_skips_local_file_data():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder/", b"")
        zf.writestr("folder/alpha.txt", "alpha" * 100)
        zf.writestr("folder/beta.txt", "beta" * 100)

    archive, tree = _decode_stream_impl(stream, ZIP_ARCHIVE, inspect=True)
    _attach_buffer_tree(tree, stream.getbuffer())

    print(format_tree(tree))

    assert archive["names"] == [
        "folder/",
        "folder/alpha.txt",
        "folder/beta.txt",
    ]
