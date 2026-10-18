"""Safe ZIP/TAR extraction. Rejects traversal, absolute paths, escaping links, device files,
and enforces member-count and written-byte limits (zip bombs lie about sizes)."""

from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from afid.errors import CorruptArchiveError, UnsafeArchiveError
from afid.utils.paths import normalize_member, safe_join, symlink_stays_inside

_COPY_CHUNK = 1024 * 1024


@dataclass
class Limits:
    max_members: int
    max_bytes: int


@dataclass
class ExtractReport:
    members: int = 0
    bytes_written: int = 0
    skipped: list[str] = field(default_factory=list)


def _copy(src, dest: Path, report: ExtractReport, limits: Limits) -> None:  # type: ignore[no-untyped-def]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while chunk := src.read(_COPY_CHUNK):
            report.bytes_written += len(chunk)
            if report.bytes_written > limits.max_bytes:
                raise UnsafeArchiveError(f"extracted size exceeds limit {limits.max_bytes} bytes")
            out.write(chunk)


def extract_zip(archive: Path, dest: Path, limits: Limits) -> ExtractReport:
    report = ExtractReport()
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise CorruptArchiveError(f"{archive.name}: not a readable ZIP ({exc})") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_members:
            raise UnsafeArchiveError(f"{archive.name}: {len(infos)} members exceeds limit")
        declared = sum(i.file_size for i in infos)
        if declared > limits.max_bytes:
            raise UnsafeArchiveError(f"{archive.name}: declared size {declared} exceeds limit")
        root = dest.resolve()
        for info in infos:
            target = safe_join(dest, info.filename)
            if target == root and not info.is_dir():
                raise UnsafeArchiveError(f"non-directory member {info.filename!r} at root")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:  # symlink stored in zip
                link = zf.read(info).decode("utf-8", "replace")
                if not symlink_stays_inside(dest.resolve(), target, link):
                    raise UnsafeArchiveError(f"symlink {info.filename} -> {link} escapes root")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(link, target)
            elif info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                try:
                    with zf.open(info) as src:
                        _copy(src, target, report, limits)
                except (zipfile.BadZipFile, EOFError, zipfile.LargeZipFile) as exc:
                    raise CorruptArchiveError(f"{info.filename}: corrupt member ({exc})") from exc
            report.members += 1
    return report


def extract_tar(archive: Path, dest: Path, limits: Limits) -> ExtractReport:
    """Handles plain and gzip/bzip2/xz-compressed tar (tarfile autodetects)."""
    report = ExtractReport()
    try:
        tf = tarfile.open(archive, mode="r:*")  # noqa: SIM115 - closed below
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise CorruptArchiveError(f"{archive.name}: not a readable TAR ({exc})") from exc
    root = dest.resolve()
    with tf:
        try:
            for member in tf:
                report.members += 1
                if report.members > limits.max_members:
                    raise UnsafeArchiveError(f"{archive.name}: member count exceeds limit")
                target = safe_join(dest, member.name)
                if target == root and not member.isdir():
                    raise UnsafeArchiveError(f"non-directory member {member.name!r} at root")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.issym():
                    if not symlink_stays_inside(root, target, member.linkname):
                        raise UnsafeArchiveError(
                            f"symlink {member.name} -> {member.linkname} escapes root"
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, target)
                elif member.islnk():
                    src = safe_join(dest, member.linkname)
                    if not src.is_file():
                        raise UnsafeArchiveError(f"hardlink {member.name} has no valid source")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, target)
                elif member.isfile():
                    fobj = tf.extractfile(member)
                    if fobj is None:
                        raise CorruptArchiveError(f"{member.name}: unreadable member")
                    with fobj:
                        _copy(fobj, target, report, limits)
                else:
                    report.skipped.append(f"{normalize_member(member.name)} (special file)")
        except (tarfile.TarError, EOFError) as exc:
            raise CorruptArchiveError(f"{archive.name}: corrupt TAR ({exc})") from exc
    return report
