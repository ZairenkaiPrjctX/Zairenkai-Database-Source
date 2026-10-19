"""Run a pinned DumprX checkout on one local firmware file, safely.

DumprX (https://github.com/DumprX/DumprX, GPL-3.0-only) is used unmodified as an external
program; AFID never imports or links it. Guards, all enforced before DumprX starts:

- the checkout carries the marker `.afid-dumprx-commit` equal to settings `dumprx.commit`,
  and `dumper.sh` hashes to settings `dumprx.dumper_sha256`;
- no DumprX credential file exists (DumprX pushes to GitHub/GitLab and posts to Telegram
  when it finds one; AFID must never publish dumps);
- the input is an existing local regular file, never a URL (DumprX would download it with
  `wget --no-check-certificate`);
- with `require_offline` (default) the process must not be able to reach the network, i.e.
  it runs in a container started with `--network none`;
- DumprX runs in a private copy of the checkout (it writes input/ and out/ next to
  dumper.sh), with an emptied environment (no tokens), a timeout and an output size limit.

Output (`out/` of the copy) is the extracted tree; afid.ingest catalogs it like any other
extracted directory. Nothing in the output is executed by AFID.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid.errors import PolicyViolationError, ResourceError, ValidationError
from afid.hashing import sha256_file
from afid.utils import log

LOG = log.get("dumprx")
MARKER = ".afid-dumprx-commit"
CREDENTIAL_FILES = (
    ".github_token",
    ".github_orgname",
    ".gitlab_token",
    ".gitlab_group",
    ".gitlab_instance",
    ".tg_token",
    ".tg_chat",
)
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# DumprX output directories that are not firmware partitions (generated helpers).
NON_PARTITION_OUTPUT = ("tmp", "aosp-device-tree", "twrp-device-tree")


def network_reachable(timeout: float = 2.0) -> bool:
    """True if a TCP connection to a public resolver succeeds. In a `--network none`
    container this fails immediately."""
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((host, 53), timeout=timeout):
                return True
        except OSError:
            continue
    return False


@dataclass
class DumpResult:
    status: str  # ok | failed
    output_dir: Path | None
    returncode: int | None
    partitions: list[str] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    commit: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = dict(vars(self))
        d["output_dir"] = str(self.output_dir) if self.output_dir else None
        return d


@dataclass
class DumprX:
    install_dir: Path
    commit: str
    dumper_sha256: str
    require_offline: bool = True
    timeout_s: int = 7200
    max_output_bytes: int = 20 * 1024**3
    probe_network: Callable[[], bool] = network_reachable

    @classmethod
    def from_settings(cls, settings: dict[str, Any], max_output_bytes: int) -> DumprX:
        d = settings["dumprx"]
        return cls(
            install_dir=Path(os.environ.get("AFID_DUMPRX_DIR") or d["install_dir"]),
            commit=str(d["commit"]),
            dumper_sha256=str(d["dumper_sha256"]),
            require_offline=bool(d.get("require_offline", True)),
            timeout_s=int(d.get("timeout_minutes", 120)) * 60,
            max_output_bytes=max_output_bytes,
        )

    # ---- checks ------------------------------------------------------------------------------
    def problems(self) -> list[str]:
        """Everything that prevents a safe run; empty when DumprX may start."""
        out: list[str] = []
        dumper = self.install_dir / "dumper.sh"
        if not dumper.is_file():
            return [f"DumprX not installed: {dumper} missing (use the afid-firmware-worker image)"]
        marker = self.install_dir / MARKER
        got = marker.read_text().strip() if marker.is_file() else None
        if got != self.commit:
            out.append(
                f"DumprX checkout is at {got or 'an unknown commit'}, expected {self.commit}"
            )
        digest = sha256_file(dumper)
        if digest != self.dumper_sha256:
            out.append(f"dumper.sh SHA-256 {digest} != pinned {self.dumper_sha256}")
        out += [
            f"credential file {self.install_dir / name} exists; refusing (DumprX would publish)"
            for name in CREDENTIAL_FILES
            if (self.install_dir / name).exists()
        ]
        if not shutil.which("bash"):
            out.append("bash not found")
        if self.require_offline and self.probe_network():
            out.append(
                "network is reachable; DumprX must run without network "
                "(docker run --network none ...)"
            )
        return out

    # ---- run ---------------------------------------------------------------------------------
    def run(self, firmware: Path, workdir: Path | None = None) -> DumpResult:
        if "://" in str(firmware):
            raise ValidationError("DumprX input must be a local file, not a URL")
        firmware = firmware.resolve()
        if not firmware.is_file() or firmware.is_symlink():
            raise ValidationError(f"{firmware}: not a regular local file")
        problems = self.problems()
        if problems:
            raise PolicyViolationError("DumprX run refused: " + "; ".join(problems))
        need = firmware.stat().st_size * 3
        base = workdir or Path(tempfile.mkdtemp(prefix="afid-dumprx-"))
        base.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(base).free
        if need > free:
            raise ResourceError(f"DumprX needs about {need} bytes free in {base}, {free} available")
        job = base / "dumprx"
        # Private copy: DumprX writes input/, out/ and helper clones next to dumper.sh.
        shutil.copytree(self.install_dir, job, symlinks=True)
        for path in (job, *job.rglob("*")):  # the installed checkout is read-only
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | 0o200)
        for name in CREDENTIAL_FILES:  # belt and braces: the copy can never carry one
            if (job / name).exists():
                raise PolicyViolationError(f"credential file {name} in job copy; refusing")
        env = {"PATH": SAFE_PATH, "HOME": str(base / "home"), "LANG": "C.UTF-8", "TERM": "dumb"}
        (base / "home").mkdir(exist_ok=True)
        LOG.info("running DumprX %s on %s", self.commit[:12], firmware.name)
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, pinned script
                ["bash", str(job / "dumper.sh"), str(firmware)],
                cwd=job,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return DumpResult("failed", None, None, log_tail=["timeout"], commit=self.commit)
        tail = (proc.stdout + proc.stderr).decode("utf-8", "replace").splitlines()[-40:]
        out = job / "out"
        parts = (
            sorted(
                p.name
                for p in out.iterdir()
                if out.is_dir()
                and p.is_dir()
                and not p.is_symlink()
                and p.name not in NON_PARTITION_OUTPUT
            )
            if out.is_dir()
            else []
        )
        size = _tree_size(out) if out.is_dir() else 0
        if size > self.max_output_bytes:
            shutil.rmtree(out, ignore_errors=True)
            raise ResourceError(f"DumprX output {size} bytes exceeds {self.max_output_bytes}")
        shutil.rmtree(out / "tmp", ignore_errors=True)
        ok = proc.returncode == 0 and bool(parts)
        return DumpResult(
            "ok" if ok else "failed",
            out if out.is_dir() else None,
            proc.returncode,
            parts,
            tail,
            self.commit,
        )


def _tree_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for f in files:
            p = Path(dirpath) / f
            if not p.is_symlink():
                total += p.stat().st_size
    return total
