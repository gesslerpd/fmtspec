import math

import pytest

from fmtspec import DecodeError, EncodeError, ExcessDecodeError, decode, encode, types


def test_iterable_array():
    obj = [
        (1, 2),
        (3, 4),
        (5, 6),
    ]
    array_fmt = types.array(types.u16, dims=(3, 2))

    assert array_fmt == types.array(types.u16, dims=(3, 2))

    data = encode(
        obj,
        array_fmt,
    )

    assert data == b"\x00\x01\x00\x02\x00\x03\x00\x04\x00\x05\x00\x06"

    result = decode(
        data,
        array_fmt,
    )

    assert result == [
        [1, 2],
        [3, 4],
        [5, 6],
    ]


def test_1d_array_roundtrip():
    arr = types.array(types.u8, dims=3)
    obj = [1, 2, 3]

    data = encode(obj, arr)
    assert data == b"\x01\x02\x03"

    res = decode(data, arr)
    assert res == obj


def test_array_size_and_equality():
    arr = types.array(types.u16, dims=(3, 2))

    # 3*2 elements * 2 bytes each == 12
    assert arr.size == 12
    assert arr == types.array(types.u16, dims=(3, 2))


def test_array_wrong_shape_raises_on_encode():
    arr = types.array(types.u16, dims=(2, 2))

    # outer length wrong
    with pytest.raises(EncodeError):
        encode([(1, 2), (3, 4), (5, 6)], arr)

    # inner length wrong
    with pytest.raises(EncodeError):
        encode([(1,), (2,)], arr)


def test_array_invalid_dims_raises():
    u8 = types.u8le
    with pytest.raises(ValueError, match="positive integers"):
        types.array(u8, dims=(0, 3))

    with pytest.raises(ValueError, match="positive integers"):
        types.array(u8, dims=(-1,))


def test_array_zero_leaf_dim_1d_roundtrip():
    u8 = types.u8le
    arr = types.array(u8, dims=0)

    data = encode([], arr)
    assert data == b""
    assert arr.size == 0

    res = decode(b"", arr)
    assert res == []


def test_array_zero_leaf_dim_2d_roundtrip():
    u8 = types.u8le
    arr = types.array(u8, dims=(3, 0))

    obj = [[], [], []]
    data = encode(obj, arr)
    assert data == b""
    assert arr.size == 0

    res = decode(b"", arr)
    assert res == obj


def test_array_zero_leaf_dim_encode_mismatch_raises():
    u8 = types.u8

    arr0 = types.array(u8, dims=0)
    with pytest.raises(EncodeError, match=r"dims\[0\]=0, got 1"):
        encode([1], arr0)

    arr_3_0 = types.array(u8, dims=(3, 0))
    with pytest.raises(EncodeError, match=r"dims\[0\]=3, got 2"):
        encode([[], []], arr_3_0)

    with pytest.raises(EncodeError, match=r"dims\[1\]=0, got 1"):
        encode([[], [1], []], arr_3_0)


def test_array_decode_insufficient_bytes_raises():
    u8 = types.u8
    arr = types.array(u8, dims=3)

    # third element is missing
    with pytest.raises(DecodeError, match=r"didn't return enough bytes"):
        decode(b"\x01\x02", arr)


def test_array_zero_leaf_dim_decode_strict_excess_raises():
    u8 = types.u8le
    arr0 = types.array(u8, dims=0)

    with pytest.raises(ExcessDecodeError, match=r"Excess data"):
        decode(b"\x01", arr0)


def test_prefixed_array_roundtrip():
    u16 = types.u16be
    p = types.Array(element_fmt=u16, dims=(u16,))

    obj = [10, 20, 30]
    data = encode(obj, p)

    # prefix (2 bytes) + three u16 values
    assert data == b"\x00\x03\x00\n\x00\x14\x00\x1e"

    res = decode(data, p)
    assert res == obj


def test_size_attribute_various():
    u16 = types.u16be
    arr = types.array(u16, dims=(3, 2))
    assert arr.size == 12

    p = types.Array(element_fmt=u16, dims=(u16,))
    assert p.size is ...

    arr2 = types.array(p, dims=(2, 2))
    assert arr2.size is ...

    u8 = types.u8le
    nested = types.array(u8, dims=4)
    assert nested.size == 4

    arr3 = types.array(nested, dims=2)
    assert arr3.size == 8


def test_array_wrong_shape_raises_on_encode_deep():
    arr3 = types.array(types.u16, dims=(2, 2, 2))

    obj = [
        [[1, 2], [3, 4], [5, 6]],
        [[5, 6], [7, 8]],
    ]

    with pytest.raises(EncodeError, match="dims\\[1\\]=2, got 3"):
        encode(obj, arr3)


def test_array_wrong_outer_length_raises_on_encode():
    u8 = types.u8le
    arr = types.array(u8, dims=2)

    with pytest.raises(EncodeError, match="dims\\[0\\]=2, got 3"):
        encode([1, 2, 3], arr)


def test_array_mixed_dims_roundtrip():
    u8 = types.u8be

    fmt = {
        "n": u8,
        "arr": types.array(u8, dims=(types.Ref("n"), 2)),
    }

    obj = {"n": 3, "arr": [[1, 2], [3, 4], [5, 6]]}

    data = encode(obj, fmt)
    assert data == b"\x03\x01\x02\x03\x04\x05\x06"

    res = decode(data, fmt)
    assert res == obj


def test_greedy_array_roundtrip():
    u16 = types.u16be
    arr = types.array(u16, dims=())

    obj = [10, 20, 30]
    data = encode(obj, arr)

    assert data == b"\x00\n\x00\x14\x00\x1e"

    res = decode(data, arr)
    assert res == obj


def test_greedy_array_size_is_none():
    u8 = types.u8be
    arr = types.array(u8, dims=())
    assert arr.size is None


def test_array_mixed_dims_wrong_shape_raises():
    u8 = types.u8be

    fmt = {
        "n": u8,
        "arr": types.array(u8, dims=(types.Ref("n"), 2)),
    }

    # provided n=2 but arr has inner length 3 -> should raise EncodeError
    with pytest.raises(EncodeError, match="dims\\[1\\]=2, got 3"):
        encode({"n": 2, "arr": [[1, 2, 3], [4, 5, 6]]}, fmt)


def test_array_mixed_dims_size_is_dynamic():
    u8 = types.u8be
    arr = types.array(u8, dims=(types.Ref("n"), 2))
    assert arr.size is ...


def test_array_dims_from_context_roundtrip():
    u8 = types.u8be

    fmt = {
        "length": u8,
        "data": types.array(u8, dims=types.Ref("length")),
    }

    obj = {"length": 3, "data": [1, 2, 3]}

    data = encode(obj, fmt)
    assert data == b"\x03\x01\x02\x03"

    res = decode(data, fmt)
    assert res == obj


def test_array_dims_from_context_wrong_shape_raises():
    u8 = types.u8be

    fmt = {
        "n": u8,
        "arr": types.array(u8, dims=(types.Ref("n"),)),
    }

    # provided n=2 but arr has length 3 -> should raise EncodeError
    with pytest.raises(EncodeError, match="dims\\[0\\]=2, got 3"):
        encode({"n": 2, "arr": [1, 2, 3]}, fmt)


def test_image():
    fmt = {
        "height": types.u16be,
        "width": types.u8be,
        "pixels": types.array(
            {
                "r": types.u8be,
                "g": types.u8be,
                "b": types.u8be,
            },
            dims=(types.Ref("height"), types.Ref("width")),
        ),
    }
    obj = {
        "height": 2,
        "width": 3,
        "pixels": [
            [
                {"r": 0, "g": 0, "b": 0},
                {"r": 1, "g": 1, "b": 1},
                {"r": 2, "g": 2, "b": 2},
            ],
            [
                {"r": 3, "g": 3, "b": 3},
                {"r": 4, "g": 4, "b": 4},
                {"r": 5, "g": 5, "b": 5},
            ],
        ],
    }
    data = encode(obj, fmt)

    assert data == (
        b"\x00\x02"  # height=2
        b"\x03"  # width=3
        b"\x00\x00\x00"
        b"\x01\x01\x01"
        b"\x02\x02\x02"
        b"\x03\x03\x03"
        b"\x04\x04\x04"
        b"\x05\x05\x05"
    )
    res = decode(data, fmt)
    assert res == obj


def test_array_of_float32_roundtrip():
    arr = types.array(types.f32, dims=3)
    obj = [1.0, 2.0, 3.0]
    data = encode(obj, arr)
    assert len(data) == len(obj) * 4
    res = decode(data, arr)
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(res, obj))


def test_array_of_float64_roundtrip():
    arr = types.array(types.f64, dims=3)
    obj = [1.0, 2.0, 3.0]
    data = encode(obj, arr)
    assert len(data) == len(obj) * 8
    res = decode(data, arr)
    assert all(math.isclose(a, b, rel_tol=1e-12) for a, b in zip(res, obj))


def test_array_of_float32le_roundtrip():
    arr = types.array(types.f32le, dims=3)
    obj = [1.0, 2.0, 3.0]
    data = encode(obj, arr)
    assert len(data) == len(obj) * 4
    res = decode(data, arr)
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(res, obj))


def test_array_of_float64le_roundtrip():
    arr = types.array(types.f64le, dims=3)
    obj = [1.0, 2.0, 3.0]
    data = encode(obj, arr)
    assert len(data) == len(obj) * 8
    res = decode(data, arr)
    assert all(math.isclose(a, b, rel_tol=1e-12) for a, b in zip(res, obj))
