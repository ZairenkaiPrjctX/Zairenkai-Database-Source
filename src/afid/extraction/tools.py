"""External tool registry. Tools are looked up on PATH; nothing is downloaded automatically.
Arguments are passed as lists (never through a shell)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from afid.errors import ToolMissingError


@dataclass(frozen=True)
class Tool:
    name: str
    purpose: str
    install_hint: str
    version_args: tuple[str, ...] = ("--version",)
    required: bool = False


TOOLS = {
    "debugfs": Tool("debugfs", "read files from ext4 images", "apt install e2fsprogs", ("-V",)),
    "fsck.erofs": Tool(
        "fsck.erofs",
        "extract EROFS images",
        "apt install erofs-utils (>= 1.6 for --extract)",
        ("-V",),
    ),
    "lpunpack": Tool(
        "lpunpack",
        "split super.img into partition images",
        "build from AOSP system/extras/partition_tools or a distro package",
    ),
    "payload-dumper-go": Tool(
        "payload-dumper-go",
        "extract payload.bin from full OTAs",
        "https://github.com/ssut/payload-dumper-go releases",
        ("-h",),
    ),
    "lz4": Tool("lz4", "decompress .lz4 images (Samsung packages)", "apt install lz4", ("-V",)),
    "readelf": Tool(
        "readelf", "optional cross-check of the built-in ELF parser", "apt install binutils"
    ),
}


def which(name: str) -> str | None:
    return shutil.which(name)


def require(name: str) -> str:
    path = which(name)
    if path is None:
        t = TOOLS[name]
        raise ToolMissingError(name, t.purpose, t.install_hint)
    return path


def version(name: str) -> str | None:
    path = which(name)
    if path is None:
        return None
    try:
        proc = subprocess.run(
            [path, *TOOLS[name].version_args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or proc.stderr).strip().splitlines()
    return text[0][:120] if text else None


def run(name: str, args: list[str], timeout: int, cwd: Path | None = None) -> str:
    path = require(name)
    proc = subprocess.run(
        [path, *args], capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{name} failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
    return proc.stdout
