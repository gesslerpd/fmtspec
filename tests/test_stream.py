from io import BytesIO
from pathlib import Path

from fmtspec import decode_stream, encode_stream, types


def test_roundtrip():
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    stream = BytesIO()
    encode_stream(obj, stream, fmt)
    data = stream.getvalue()

    assert data == b"value\0\x2a\x00\x00\x00"

    stream = BytesIO(data)
    result = decode_stream(stream, fmt)
    assert result == obj


def test_encode_to_file(tmp_path: Path):
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    file_path = tmp_path / "test_data.bin"

    with open(file_path, "wb") as f:
        encode_stream(obj, f, fmt)

    # Verify the file contents
    with open(file_path, "rb") as f:
        data = f.read()

    assert data == b"value\0\x2a\x00\x00\x00"


def test_decode_from_file(tmp_path: Path):
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    file_path = tmp_path / "test_data.bin"

    # Write test data to file
    with open(file_path, "wb") as f:
        f.write(b"value\0\x2a\x00\x00\x00")

    # Decode from file
    with open(file_path, "rb") as f:
        result = decode_stream(f, fmt)

    assert result == {"key": "value", "number": 42}


def test_file_roundtrip(tmp_path: Path):
    obj = {"key": "value", "number": 42}
    fmt = {
        "key": types.TakeUntil(types.Str(), b"\0"),
        "number": types.Int(byteorder="little", signed=False, size=4),
    }

    file_path = tmp_path / "test_roundtrip.bin"

    # Encode to file
    with open(file_path, "wb") as f:
        encode_stream(obj, f, fmt)

    # Decode from file
    with open(file_path, "rb") as f:
        result = decode_stream(f, fmt)

    assert result == obj
