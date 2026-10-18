"""Format detection by magic bytes (never by file extension alone)."""

from __future__ import annotations

import struct
from pathlib import Path

SPARSE_MAGIC = 0xED26FF3A


def detect(path: Path) -> str:
    """Return one of: zip, tar, gzip, xz, bzip2, zstd, lz4, android_sparse, android_payload,
    super_lp, ext4, erofs, android_boot, unknown."""
    with path.open("rb") as fh:
        head = fh.read(8192)
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if head[:2] == b"\x1f\x8b":
        return "gzip"
    if head[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if head[:3] == b"BZh":
        return "bzip2"
    if head[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    if head[:4] == b"\x04\x22\x4d\x18":
        return "lz4"
    if head[:4] == b"CrAU":
        return "android_payload"
    if head[:8] == b"ANDROID!":
        return "android_boot"
    if len(head) >= 4 and struct.unpack("<I", head[:4])[0] == SPARSE_MAGIC:
        return "android_sparse"
    if len(head) >= 263 and head[257:262] == b"ustar":
        return "tar"
    if len(head) >= 1082 and head[1080:1082] == b"\x53\xef":
        return "ext4"
    if len(head) >= 1028 and head[1024:1028] == b"\xe2\xe1\xf5\xe0":
        return "erofs"
    if len(head) >= 4100 and head[4096:4100] == b"gDla":
        return "super_lp"
    return "unknown"
