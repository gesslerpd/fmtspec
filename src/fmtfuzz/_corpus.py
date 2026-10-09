"""Content-addressed storage for fuzzing inputs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class Corpus:
    """A small on-disk corpus with SHA-256 deduplication."""

    def __init__(self, directory: str | Path, *, max_size: int = 4096) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self.directory = Path(directory)
        self.max_size = max_size
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.is_dir():
            raise NotADirectoryError(self.directory)

    def add(self, data: bytes | bytearray | memoryview) -> bool:
        """Store ``data`` and return whether it was a new corpus entry."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("corpus inputs must be bytes-like")
        value = bytes(data)
        if len(value) > self.max_size:
            raise ValueError(f"Input size {len(value)} exceeds max_size={self.max_size}")

        digest = hashlib.sha256(value).hexdigest()
        path = self.directory / f"{digest}.bin"
        try:
            with path.open("xb") as file:
                file.write(value)
        except FileExistsError:
            if path.read_bytes() != value:
                raise RuntimeError(f"SHA-256 collision or corrupt corpus entry: {path}")
            return False
        return True

    def extend(self, inputs: Iterable[bytes]) -> int:
        """Store inputs and return the number of newly added entries."""
        return sum(self.add(data) for data in inputs)

    def load(self) -> tuple[bytes, ...]:
        """Read all corpus inputs in deterministic filename order."""
        values = []
        for path in sorted(self.directory.glob("*.bin")):
            data = path.read_bytes()
            if len(data) > self.max_size:
                raise ValueError(
                    f"Corpus entry {path.name} has {len(data)} bytes, "
                    f"exceeding max_size={self.max_size}"
                )
            expected_name = f"{hashlib.sha256(data).hexdigest()}.bin"
            if path.name != expected_name:
                raise ValueError(f"Corrupt or non-content-addressed corpus entry: {path}")
            values.append(data)
        return tuple(values)

    def __iter__(self) -> Iterator[bytes]:
        return iter(self.load())

    def __len__(self) -> int:
        return sum(1 for _ in self.directory.glob("*.bin"))
