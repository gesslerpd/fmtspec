import math
import struct

from fmtspec import decode, encode, types


def test_f32_encode_decode_roundtrip():
    vals = [0.0, 1.5, -2.75, 123.5]
    for v in vals:
        data = encode(v, types.f32)
        res = decode(data, types.f32)
        assert math.isclose(res, v, rel_tol=1e-6, abs_tol=0.0)


def test_f64_encode_decode_roundtrip():
    vals = [0.0, 1.5, -2.75, 1e300]
    for v in vals:
        data = encode(v, types.f64)
        res = decode(data, types.f64)
        assert math.isclose(res, v, rel_tol=1e-12, abs_tol=0.0)


def test_endianness_matches_struct_pack():
    v = 1.5
    be = encode(v, types.f32)  # f32 is big-endian alias
    le = encode(v, types.f32le)
    assert be == struct.pack(">f", v)
    assert le == struct.pack("<f", v)


def test_nan_and_infinity_handling():
    # NaN roundtrips to NaN (cannot compare directly)
    nan_bytes = encode(float("nan"), types.f32)
    nan_val = decode(nan_bytes, types.f32)
    assert math.isnan(nan_val)

    pos_inf = encode(float("inf"), types.f64)
    neg_inf = encode(float("-inf"), types.f64)

    assert math.isinf(decode(pos_inf, types.f64))
    assert decode(pos_inf, types.f64) > 0
    assert math.isinf(decode(neg_inf, types.f64))
    assert decode(neg_inf, types.f64) < 0
