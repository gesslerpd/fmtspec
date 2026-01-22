from enum import StrEnum


class Endian(StrEnum):
    """Byte order enumeration."""

    LITTLE = "little"
    BIG = "big"
