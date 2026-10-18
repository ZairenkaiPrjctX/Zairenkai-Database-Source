"""Path safety helpers. Firmware content is untrusted: never let a name escape a root."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath

from afid.errors import UnsafeArchiveError

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def normalize_member(name: str) -> str:
    """Normalize an archive member name to a relative POSIX path, or raise if unsafe."""
    if "\x00" in name:
        raise UnsafeArchiveError(f"NUL byte in member name {name!r}")
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchiveError(f"absolute member path {name!r}")
    norm = posixpath.normpath(name) if name else ""
    if norm == "" or norm == ".." or norm.startswith("../"):
        raise UnsafeArchiveError(f"member path escapes extraction root: {name!r}")
    return norm


def safe_join(root: Path, member: str) -> Path:
    """Join a member name under root, guaranteeing the result stays inside root."""
    rel = normalize_member(member)
    dest = (root / rel).resolve()
    root_r = root.resolve()
    if dest != root_r and root_r not in dest.parents:
        raise UnsafeArchiveError(f"member resolves outside extraction root: {member!r}")
    return dest


def symlink_stays_inside(root: Path, link_path: Path, target: str) -> bool:
    """True if a symlink at link_path pointing to target would resolve inside root.

    Absolute targets are interpreted relative to root (as on a mounted partition).
    """
    if target.startswith("/"):
        candidate = PurePosixPath(posixpath.normpath(target.lstrip("/")))
        return not str(candidate).startswith("..")
    base = PurePosixPath(link_path.relative_to(root).parent.as_posix())
    joined = posixpath.normpath(str(base / target))
    return not (joined == ".." or joined.startswith("../"))


def safe_dirname(value: str) -> str:
    """Return value if it is safe as a single directory name, else raise."""
    if not value or value in (".", "..") or not _SAFE_COMPONENT.match(value):
        raise UnsafeArchiveError(f"unsafe directory name {value!r}")
    return value


def sanitize_id(value: str) -> str:
    """Map an arbitrary build/version string to a safe identifier (deterministic)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned or "unknown"
