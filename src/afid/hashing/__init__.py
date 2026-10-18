"""SHA-256 helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, *parts: str, length: int = 20) -> str:
    """Deterministic ID from its defining parts (not from file paths alone)."""
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest[:length]}"


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.match(value))
