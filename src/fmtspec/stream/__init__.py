"""Public low-level stream helpers for custom fmtspec types."""

from ._impl import peek as peek
from ._impl import read_exactly as read_exactly
from ._impl import seek_to as seek_to
from ._impl import write_all as write_all
from ._impl import decode_stream as decode_stream
from ._impl import encode_stream as encode_stream
