from collections.abc import Sequence
from typing import cast

from fmtspec import encode_inspect, format_tree, sizeof, types

type ListOfList[T] = Sequence[T | ListOfList[T]]


def make_array[T](element: T, dims: Sequence[int]) -> ListOfList[T]:
    if not dims:
        raise ValueError("dims must be non-empty")

    # cast since the loop guaranteed to run at least once
    result = cast("list[T]", element)
    for dim in reversed(dims):
        result = [result] * dim
    return result


arr_data = make_array(0, (3, 3, 3, 2))
arr_fmt = make_array(types.u8, (3, 3, 3, 2))

fmt = {
    "header": {
        "version": types.u8,
        "flags": types.u8,
    },
    "data": types.u16,
    "list": arr_fmt,
}

obj = {"header": {"version": 1, "flags": 2}, "data": 0x0304, "list": arr_data}
data, view = encode_inspect(obj, fmt)
print("Tree with max_depth=2:")
print(format_tree(view, max_depth=2, only_leaf=False))

print("Version:", view["header"]["version"].data)
print("Flags:", view["header"]["flags"].data)
print("Data:", view["data"].data)

# Modify values via different part of the view
view["data"].data = view["header"].data

# print("Modified Data:", view["data"].data)
assert view["list"].size == sizeof(fmt["list"])

# list access
view["list"][0][0][0][0].data = b"\x10"
view["list"][0][0][0][1].data = b"\x14"
view["list"][0][0][1][0].data = b"\x1e"

print(view["list"].value)


view["list"][0][0][0].value = [0xFF, 67]

# print(format_tree(view, max_depth=1))
print(format_tree(view, max_depth=2))
