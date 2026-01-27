from io import BytesIO

import pytest

from fmtspec import DecodeError, decode, decode_stream, encode
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
    with pytest.raises(DecodeError, match="5 bytes") as exc:
        decode(data, fmt=u8, strict=True)
    assert exc.value.stream.read() == extra

    result = decode(data, fmt=u8, strict=False)
    assert result == 1
