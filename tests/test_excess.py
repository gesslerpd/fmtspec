from io import BytesIO

import pytest

from fmtspec import ExcessDecodeError, decode, decode_stream, encode
from fmtspec.types import u8


def test_decode_default_allows_excess_bytes_stream():
    extra = b"EXTRA"
    data = encode(1, fmt=u8) + extra
    stream = BytesIO(data)
    result = decode_stream(stream, fmt=u8)
    assert result == 1
    assert stream.read() == extra


def test_decode_errors_on_excess_bytes_top_level():
    extra = b"EXTRA"
    data = encode(1, fmt=u8) + extra
    with pytest.raises(ExcessDecodeError, match="5 bytes") as exc:
        decode(data, fmt=u8)
    assert exc.value.remaining == 5
    assert exc.value.stream.read() == extra
    assert exc.value.start_offset == 0
    assert exc.value.offset == 1  # after decoding 1 byte


def test_excess_stream_error_stream_can_be_decoded_further():
    """The stream on ExcessDataError is positioned at the excess data,
    allowing further decode_stream calls to consume it."""
    header = encode(1, fmt=u8)
    trailer = encode(2, fmt=u8)
    data = header + trailer
    with pytest.raises(ExcessDecodeError) as exc:
        decode(data, fmt=u8)
    next_value = decode_stream(exc.value.stream, fmt=u8)
    assert next_value == 2
