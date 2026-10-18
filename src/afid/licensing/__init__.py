"""Distribution policy. Unknown is the default and is never publishable."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from afid.errors import ConfigError
from afid.hashing import is_sha256, sha256_file

STATUSES = ("allowed", "restricted", "unknown", "user_supplied", "metadata_only")


@dataclass
class Policy:
    default_status: str
    publishable: frozenset[str]
    allow_by_sha: dict[str, dict[str, Any]]

    @classmethod
    def from_config(cls, policy: dict[str, Any], allowlist: list[dict[str, Any]]) -> Policy:
        default = policy.get("default_distribution_status")
        if default != "unknown":
            raise ConfigError("default_distribution_status must be 'unknown'")
        publishable = frozenset(policy.get("publishable_statuses") or [])
        if publishable - {"allowed"}:
            raise ConfigError("only 'allowed' may be publishable")
        by_sha: dict[str, dict[str, Any]] = {}
        for entry in allowlist:
            sha = str(entry.get("sha256") or "")
            missing = [
                k
                for k in ("license", "evidence_url", "reviewed_by", "reviewed_at")
                if not entry.get(k)
            ]
            if not is_sha256(sha) or missing:
                raise ConfigError(f"allowlist entry {entry!r} invalid (sha256/{missing})")
            by_sha[sha] = entry
        return cls(default, publishable, by_sha)

    def status_for(self, sha256: str | None, user_supplied: bool) -> str:
        if sha256 and sha256 in self.allow_by_sha:
            return "allowed"
        return "user_supplied" if user_supplied else self.default_status

    def license_for(self, sha256: str | None) -> str:
        return "reviewed" if sha256 and sha256 in self.allow_by_sha else "unknown"

    def can_publish(self, status: str) -> bool:
        return status in self.publishable

    def check_publish_dir(self, directory: Path) -> list[str]:
        """Every file under `directory` must be allowlisted by SHA-256. Returns violations."""
        problems: list[str] = []
        if not directory.exists():
            return problems
        for f in sorted(directory.rglob("*")):
            if f.is_symlink():
                problems.append(f"{f}: symlinks are not publishable")
            elif f.is_file() and f.name != "README.md" and sha256_file(f) not in self.allow_by_sha:
                problems.append(f"{f}: not in redistributable_allowlist.yml")
        return problems
