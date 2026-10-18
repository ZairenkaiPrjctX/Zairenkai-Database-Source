"""Read-only firmware extraction pipeline.

source (archive | image | directory)
  -> integrity (size limit, SHA-256, optional official checksum)
  -> type detection (magic bytes)
  -> safe unpack of ZIP/TAR (nested up to MAX_NESTING)
  -> partition image discovery
  -> sparse -> raw, super -> partition images, payload.bin -> partition images
  -> filesystem extraction (ext4 via debugfs, EROFS via fsck.erofs) into tree/<partition>/

Nothing found inside firmware is executed. External tools receive argument lists, never shell
strings. Work directories are keyed by the archive SHA-256 so repeated runs reuse results.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid.errors import (
    CorruptArchiveError,
    ToolMissingError,
    UnsafeArchiveError,
    UnsupportedFormatError,
)
from afid.extraction import archives, sparse, tools
from afid.extraction.detect import detect
from afid.hashing import sha256_file
from afid.utils import log

LOG = log.get("extract")
MAX_NESTING = 2
ARCHIVE_TYPES = {"zip", "tar", "gzip", "xz", "bzip2"}
IMAGE_TYPES = {"ext4", "erofs", "android_sparse", "super_lp", "android_payload", "lz4"}
TOOL_TIMEOUT = 3600
_SLOT = re.compile(r"_(a|b)$")


@dataclass
class Partition:
    name: str
    container: str | None
    filesystem: str | None
    extracted: bool
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "container": self.container,
            "filesystem": self.filesystem,
            "extracted": self.extracted,
            "note": self.note,
        }


@dataclass
class Prepared:
    tree: Path
    workdir: Path | None
    archive_name: str | None
    archive_sha256: str | None
    archive_size: int | None
    partitions: list[Partition] = field(default_factory=list)
    ota_metadata: dict[str, str] = field(default_factory=dict)
    android_info: dict[str, str] = field(default_factory=dict)
    tools: list[dict[str, str | None]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def partition_name(filename: str) -> str:
    stem, prev = filename, None
    while stem != prev:  # strip stacked suffixes such as .raw.img or .img.lz4
        prev = stem
        for ext in (".lz4", ".raw", ".img", ".ext4", ".erofs", ".bin"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
    return _SLOT.sub("", stem.lower())


def _key_value(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class Pipeline:
    def __init__(
        self,
        cache: Path,
        partitions: list[str],
        max_archive: int,
        max_extracted: int,
        max_members: int,
    ) -> None:
        self.cache = cache
        self.wanted = set(partitions)
        self.max_archive = max_archive
        self.limits = archives.Limits(max_members=max_members, max_bytes=max_extracted)
        self._tools_used: dict[str, str | None] = {}

    # ---- entry point -------------------------------------------------------------------------
    def prepare(self, source: Path, expected_sha256: str | None = None) -> Prepared:
        source = source.resolve()
        if source.is_dir():
            return self._prepare_dir(source)
        if not source.is_file():
            raise FileNotFoundError(f"{source} does not exist")
        size = source.stat().st_size
        if size > self.max_archive:
            raise UnsafeArchiveError(f"{source.name}: {size} bytes exceeds max_archive_bytes")
        digest = sha256_file(source)
        if expected_sha256 and expected_sha256.lower() != digest:
            raise CorruptArchiveError(
                f"{source.name}: SHA-256 mismatch (expected {expected_sha256}, got {digest})"
            )
        work = self.cache / "work" / digest[:16]
        prepared = Prepared(
            tree=work / "tree",
            workdir=work,
            archive_name=source.name,
            archive_sha256=digest,
            archive_size=size,
        )
        kind = detect(source)
        unpacked = work / "unpacked"
        if kind in ARCHIVE_TYPES:
            self._unpack_once(source, kind, unpacked)
        elif kind in IMAGE_TYPES:
            unpacked.mkdir(parents=True, exist_ok=True)
            link = unpacked / source.name
            if not link.exists():
                link.symlink_to(source)
        else:
            raise UnsupportedFormatError(
                f"{source.name}: unrecognized format '{kind}'. Supported containers: ZIP, TAR "
                "(plain/gz/bz2/xz); images: ext4, EROFS, Android sparse, super, payload.bin, lz4"
            )
        self._read_metadata(unpacked, prepared)
        if _has_partition_dirs(unpacked, self.wanted):
            prepared.tree = unpacked
            prepared.partitions = [
                Partition(p.name, "directory", None, True)
                for p in sorted(unpacked.iterdir())
                if p.is_dir() and p.name in self.wanted
            ]
        else:
            self._extract_images(unpacked, prepared, nesting=0)
        prepared.tools = [{"name": k, "version": v} for k, v in sorted(self._tools_used.items())]
        return prepared

    def _prepare_dir(self, source: Path) -> Prepared:
        prepared = Prepared(
            tree=source, workdir=None, archive_name=None, archive_sha256=None, archive_size=None
        )
        self._read_metadata(source, prepared)
        if _has_partition_dirs(source, self.wanted):
            prepared.partitions = [
                Partition(p.name, "directory", None, True)
                for p in sorted(source.iterdir())
                if p.is_dir() and p.name in self.wanted
            ]
            return prepared
        # A directory of images (e.g. an unpacked factory package): extract into a work dir.
        work = self.cache / "work" / ("dir-" + re.sub(r"[^A-Za-z0-9]", "_", source.name)[:40])
        prepared.workdir, prepared.tree = work, work / "tree"
        self._extract_images(source, prepared, nesting=0)
        prepared.tools = [{"name": k, "version": v} for k, v in sorted(self._tools_used.items())]
        return prepared

    # ---- stages ------------------------------------------------------------------------------
    def _unpack_once(self, archive: Path, kind: str, dest: Path) -> None:
        marker = dest.with_name(dest.name + ".complete")
        if marker.exists():
            LOG.info("reusing unpacked %s", archive.name)
            return
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        try:
            if kind == "zip":
                rep = archives.extract_zip(archive, dest, self.limits)
            else:
                rep = archives.extract_tar(archive, dest, self.limits)
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        LOG.info("unpacked %s: %d members, %d bytes", archive.name, rep.members, rep.bytes_written)
        marker.write_text("ok\n")

    def _read_metadata(self, base: Path, prepared: Prepared) -> None:
        meta = base / "META-INF" / "com" / "android" / "metadata"
        if meta.is_file():
            prepared.ota_metadata = _key_value(meta.read_text("utf-8", "replace"))
        for info in sorted(base.rglob("android-info.txt"))[:1]:
            prepared.android_info = _key_value(info.read_text("utf-8", "replace"))

    def _extract_images(self, base: Path, prepared: Prepared, nesting: int) -> None:
        candidates = sorted(p for p in base.rglob("*") if p.is_file() or p.is_symlink())
        for path in candidates:
            if not path.exists():
                continue
            kind = detect(path)
            if kind in ARCHIVE_TYPES and nesting < MAX_NESTING:
                inner = prepared.workdir / "nested" / f"{nesting}-{path.name}"  # type: ignore[operator]
                try:
                    self._unpack_once(path, kind, inner)
                except (CorruptArchiveError, UnsafeArchiveError) as exc:
                    prepared.warnings.append(f"nested archive {path.name}: {exc}")
                    continue
                self._read_metadata(inner, prepared)
                self._extract_images(inner, prepared, nesting + 1)
            elif kind in IMAGE_TYPES:
                self._image(path, kind, prepared)

    def _image(self, path: Path, kind: str, prepared: Prepared) -> None:
        name = "payload" if kind == "android_payload" else partition_name(path.name)
        if kind not in ("super_lp", "android_payload") and name not in self.wanted:
            prepared.partitions.append(
                Partition(name, kind, None, False, "not in scan.partitions; not extracted")
            )
            return
        try:
            self._image_inner(path, kind, name, prepared)
        except (
            ToolMissingError,
            CorruptArchiveError,
            UnsupportedFormatError,
            RuntimeError,
            OSError,
        ) as exc:
            prepared.partitions.append(Partition(name, kind, None, False, str(exc)[:300]))
            prepared.warnings.append(f"{path.name}: {exc}")

    def _image_inner(self, path: Path, kind: str, name: str, prepared: Prepared) -> None:
        work: Path = prepared.workdir  # type: ignore[assignment]
        images = work / "images"
        images.mkdir(parents=True, exist_ok=True)
        if kind == "lz4":
            raw = images / f"{name}.img"
            self._tool("lz4", ["-d", "-f", str(path), str(raw)])
            self._image(raw, detect(raw), prepared)
        elif kind == "android_sparse":
            raw = images / f"{name}.raw.img"
            if not raw.exists():
                sparse.unsparse(path, raw, self.limits.max_bytes)
            inner = detect(raw)
            if inner == "super_lp":
                self._image(raw, inner, prepared)
            else:
                self._filesystem(raw, inner, name, "android_sparse", prepared)
        elif kind == "super_lp":
            out = images / f"super-{path.stem}"
            out.mkdir(exist_ok=True)
            self._tool("lpunpack", [str(path), str(out)])
            for img in sorted(out.glob("*.img")):
                self._image(img, detect(img), prepared)
        elif kind == "android_payload":
            out = images / "payload"
            out.mkdir(exist_ok=True)
            wanted = ",".join(sorted(self.wanted))
            self._tool("payload-dumper-go", ["-p", wanted, "-o", str(out), str(path)])
            for img in sorted(out.glob("*.img")):
                self._image(img, detect(img), prepared)
        else:
            self._filesystem(path, kind, name, None, prepared)

    def _filesystem(
        self, image: Path, fs: str, name: str, container: str | None, prepared: Prepared
    ) -> None:
        dest = prepared.tree / name
        marker = dest.with_name(dest.name + ".complete")
        if not marker.exists():
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            if fs == "ext4":
                self._tool("debugfs", ["-R", f"rdump / {dest}", str(image)])
            elif fs == "erofs":
                self._tool("fsck.erofs", [f"--extract={dest}", str(image)])
            else:
                shutil.rmtree(dest)
                raise UnsupportedFormatError(f"{image.name}: filesystem '{fs}' not supported")
            marker.write_text("ok\n")
        prepared.partitions.append(Partition(name, container or "raw_image", fs, True))

    def _tool(self, name: str, args: list[str]) -> str:
        out = tools.run(name, args, TOOL_TIMEOUT)
        self._tools_used.setdefault(name, tools.version(name))
        return out


def _has_partition_dirs(base: Path, wanted: set[str]) -> bool:
    return any((base / p).is_dir() for p in wanted)
