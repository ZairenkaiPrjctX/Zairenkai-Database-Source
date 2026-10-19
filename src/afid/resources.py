"""Runtime resource inspection and budget enforcement.

Limits come from config/settings.yml `resources.defaults`, may be overridden by AFID_<NAME>
environment variables, and are clamped to `hard_caps` and `minimums`. Container limits
restrict a job; they never add resources the runner does not have, so every heavy step
checks the real free disk before it starts.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from afid.config import Config
from afid.errors import ConfigError, ResourceError

NAMES = (
    "MAX_DISCOVERY_PARALLEL",
    "MAX_DOWNLOAD_PARALLEL",
    "MAX_EXTRACT_PARALLEL",
    "MAX_ANALYSIS_PARALLEL",
    "MAX_ITEMS_PER_RUN",
    "MAX_DOWNLOAD_BYTES",
    "MAX_EXTRACTED_BYTES",
    "MAX_FETCH_FILES",
    "MAX_FETCH_BYTES",
    "DISK_RESERVE_BYTES",
    "JOB_TIMEOUT_MINUTES",
    "RETRY_LIMIT",
    "HTTP_TIMEOUT",
    "RATE_LIMIT_DELAY",
)


@dataclass(frozen=True)
class Machine:
    nproc: int
    mem_total_bytes: int | None
    mem_available_bytes: int | None
    disk_path: str
    disk_free_bytes: int
    disk_total_bytes: int
    inodes_free: int | None

    def as_dict(self) -> dict[str, Any]:
        return dict(vars(self))


def _meminfo() -> tuple[int | None, int | None]:
    try:
        text = Path("/proc/meminfo").read_text()
    except OSError:
        return None, None
    vals = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            vals[key] = int(parts[0]) * 1024
    return vals.get("MemTotal"), vals.get("MemAvailable")


def probe(path: Path) -> Machine:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    try:
        st = os.statvfs(path)
        inodes: int | None = st.f_favail
    except (OSError, AttributeError):
        inodes = None
    total, avail = _meminfo()
    return Machine(os.cpu_count() or 1, total, avail, str(path), usage.free, usage.total, inodes)


def limits(cfg: Config, env: dict[str, str] | None = None) -> dict[str, float]:
    env = dict(os.environ) if env is None else env
    res = cfg.settings.get("resources") or {}
    defaults, caps, mins = (
        res.get("defaults", {}),
        res.get("hard_caps", {}),
        res.get("minimums", {}),
    )
    out: dict[str, float] = {}
    for name in NAMES:
        if name not in defaults:
            raise ConfigError(f"resources.defaults.{name} missing in config/settings.yml")
        raw = env.get(f"AFID_{name}")
        try:
            value = float(raw) if raw not in (None, "") else float(defaults[name])
        except ValueError as exc:
            raise ConfigError(f"AFID_{name}={raw!r} is not a number") from exc
        if value < 0:
            raise ConfigError(f"AFID_{name} must not be negative")
        if name in caps:
            value = min(value, float(caps[name]))
        if name in mins:
            value = max(value, float(mins[name]))
        out[name] = value
    return out


def ensure_disk(path: Path, needed_bytes: int, reserve_bytes: int, what: str) -> None:
    """Refuse to start work that would leave less than `reserve_bytes` free."""
    free = shutil.disk_usage(path).free
    if needed_bytes + reserve_bytes > free:
        raise ResourceError(
            f"{what}: needs {needed_bytes} bytes plus {reserve_bytes} reserve, only {free} free "
            f"at {path}; use a larger runner or lower the item size"
        )


def profile(machine: Machine, lim: dict[str, float]) -> dict[str, Any]:
    """Effective concurrency for this machine: never more workers than CPUs, and heavy work
    sequential when memory is below 8 GiB."""
    cpus = max(1, machine.nproc)
    mem = machine.mem_available_bytes or 0
    heavy = 1 if mem < 8 * 1024**3 else int(lim["MAX_EXTRACT_PARALLEL"])
    return {
        "discovery_parallel": int(min(lim["MAX_DISCOVERY_PARALLEL"], cpus)),
        "download_parallel": int(min(lim["MAX_DOWNLOAD_PARALLEL"], cpus)),
        "extract_parallel": int(max(1, min(heavy, cpus))),
        "analysis_parallel": int(min(lim["MAX_ANALYSIS_PARALLEL"], cpus)),
        "items_per_run": int(lim["MAX_ITEMS_PER_RUN"]),
    }
