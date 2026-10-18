"""Android sparse image -> raw image conversion (format: AOSP libsparse sparse_format.h).

Header (28 bytes, little-endian): magic u32, major u16, minor u16, file_hdr_sz u16,
chunk_hdr_sz u16, blk_sz u32, total_blks u32, total_chunks u32, image_checksum u32.
Chunk header (12 bytes): type u16, reserved u16, chunk_sz u32 (blocks), total_sz u32 (bytes).
"""

from __future__ import annotations

import struct
from pathlib import Path

from afid.errors import CorruptArchiveError

MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE, CRC32 = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4


def unsparse(src: Path, dest: Path, max_bytes: int) -> int:
    """Write the raw image to dest. Returns the raw size in bytes."""
    with src.open("rb") as fh, dest.open("wb") as out:
        hdr = fh.read(28)
        if len(hdr) < 28:
            raise CorruptArchiveError(f"{src.name}: truncated sparse header")
        magic, major, _minor, fhs, chs, blk, total_blks, chunks, _ = struct.unpack(
            "<IHHHHIIII", hdr
        )
        if magic != MAGIC or major != 1 or fhs < 28 or chs < 12 or blk == 0 or blk % 4:
            raise CorruptArchiveError(f"{src.name}: invalid sparse header")
        raw_size = total_blks * blk
        if raw_size > max_bytes:
            raise CorruptArchiveError(f"{src.name}: raw size {raw_size} exceeds limit")
        fh.seek(fhs)
        written_blocks = 0
        for _ in range(chunks):
            ch = fh.read(chs)
            if len(ch) < 12:
                raise CorruptArchiveError(f"{src.name}: truncated chunk header")
            ctype, _r, csz, tsz = struct.unpack("<HHII", ch[:12])
            fh.seek(chs - 12, 1)
            data_sz = tsz - chs
            if written_blocks + csz > total_blks:
                raise CorruptArchiveError(f"{src.name}: chunks exceed declared size")
            if ctype == RAW:
                if data_sz != csz * blk:
                    raise CorruptArchiveError(f"{src.name}: RAW chunk size mismatch")
                remaining = data_sz
                while remaining:
                    buf = fh.read(min(remaining, 1 << 20))
                    if not buf:
                        raise CorruptArchiveError(f"{src.name}: truncated RAW chunk")
                    out.write(buf)
                    remaining -= len(buf)
            elif ctype == FILL:
                if data_sz != 4:
                    raise CorruptArchiveError(f"{src.name}: FILL chunk size mismatch")
                pattern = fh.read(4) * (blk // 4)
                for _b in range(csz):
                    out.write(pattern)
            elif ctype == DONT_CARE:
                out.seek(csz * blk, 1)
            elif ctype == CRC32:
                fh.seek(data_sz, 1)
                continue
            else:
                raise CorruptArchiveError(f"{src.name}: unknown chunk type {ctype:#x}")
            written_blocks += csz
        out.truncate(raw_size)
    return int(raw_size)
