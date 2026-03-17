from __future__ import annotations

from io import SEEK_CUR, BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO

from .._stream import _decode_stream, _encode_stream

if TYPE_CHECKING:
    from collections.abc import Buffer

    from .._protocol import Context, Format


def encode_stream(
    obj: Any,
    fmt: Format,
    stream: BinaryIO,
    *,
    context: Context,
    key: str | int | None = None,
) -> None:
    """Encode a nested value with an existing Context.

    This is the public low-level entry point for custom format implementations
    that need to delegate part of their work back to fmtspec's traversal engine.
    """
    _encode_stream(obj, fmt, stream, context=context, key=key)


def decode_stream(
    stream: BinaryIO,
    fmt: Format,
    *,
    context: Context,
    key: str | int | None = None,
) -> Any:
    """Decode a nested value with an existing Context.

    This is the public low-level entry point for custom format implementations
    that need to delegate part of their work back to fmtspec's traversal engine.
    """
    return _decode_stream(stream, fmt, context=context, key=key)[0]


# perf: force positional-only to avoid unnecessary kwargs parsing overhead in hot paths
def write_all(stream: BinaryIO, data: Buffer, /) -> None:
    """Write all bytes from ``data`` to ``stream`` or raise ``EOFError``."""
    # perf: fast path for BytesIO
    if type(stream) is BytesIO:
        stream.write(data)
        return
    total = len(data)
    write = stream.write
    n = write(data)
    if n < total:
        # FUTURE: optimize by only writing part of remaining data? based on the first `n` value?
        mv = memoryview(data)
        while n < total:
            written = write(mv[n:])
            n += written
        mv.release()  # not required but explicitly release memoryview


# perf: force positional-only to avoid unnecessary kwargs parsing overhead in hot paths
def read_exactly(stream: BinaryIO, size: int, /) -> bytes:
    """Read exactly ``size`` bytes from ``stream`` or raise ``EOFError``."""
    # perf: fast path for BytesIO
    if type(stream) is BytesIO:
        data = stream.read(size)
        data_size = len(data)
        if data_size != size:
            raise EOFError(f"Expected {size} bytes, got {data_size}")
        return data

    # perf: pre-allocate and fill via readinto to avoid per-chunk allocations
    out = bytearray(size)
    mv = memoryview(out)
    try:
        n = 0
        readinto = getattr(stream, "readinto", None)
        if readinto is not None:
            while n < size:
                got = readinto(mv[n:])
                if not got:
                    raise EOFError(f"Expected {size} bytes, got {n}")
                n += got
        else:
            read = stream.read
            while n < size:
                chunk = read(size - n)
                if not chunk:
                    raise EOFError(f"Expected {size} bytes, got {n}")
                chunk_size = len(chunk)
                n_next = n + chunk_size
                mv[n:n_next] = chunk
                n = n_next
    finally:
        mv.release()
    return out


# perf: force positional-only to avoid unnecessary kwargs parsing overhead in hot paths
def peek(stream: BinaryIO, size: int, /) -> bytes:
    """Peek exactly ``size`` bytes from ``stream`` without advancing the position."""
    data = read_exactly(stream, size)
    stream.seek(-size, SEEK_CUR)
    return data
