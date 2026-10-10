"""Small file-inspection helpers for solver scripts.

These helpers are convenience APIs only. They do not sandbox a solver or
restrict its access to files, the network, or other resources.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def read_bytes(path: str | Path) -> bytes:
    """Read and return a file's bytes."""
    return Path(path).read_bytes()


def read_text(path: str | Path, encoding: str = "utf-8") -> str:
    """Read a text file using the supplied encoding."""
    return Path(path).read_text(encoding=encoding)


def sha256_file(path: str | Path) -> str:
    """Return the hexadecimal SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
