"""Provider API. Every firmware/metadata source is an independent FirmwareProvider.

Operations a provider does not support raise CapabilityError with the provider's documented
limitation, so callers (CLI, workflows) can report precisely why something is unavailable.
"""

from __future__ import annotations

import threading
from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid.download import HttpClient
from afid.errors import CapabilityError, CorruptArchiveError
from afid.hashing import sha256_file
from afid.models import Evidence


@dataclass(frozen=True)
class Capabilities:
    discover_devices: bool = False
    discover_firmware: bool = False
    fetch_metadata: bool = False
    download: bool = False
    verify: bool = False
    local_import: bool = False

    def as_dict(self) -> dict[str, bool]:
        return dict(vars(self))


@dataclass
class DeviceCandidate:
    item_id: str
    revision: str | None
    url: str | None
    brand_id: str | None
    brand_inference: str
    codename: str
    product_names: list[str]
    model_numbers: list[str]
    soc: dict[str, str | None]
    release_date: str | None
    evidence: Evidence


@dataclass
class Release:
    provider_id: str
    codename: str
    build_id: str
    url: str | None
    sha256: str | None
    size: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryResult:
    provider_id: str
    status: str  # ok | partial | failed | unsupported
    index_revision: str | None = None
    candidates: list[DeviceCandidate] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class VerifyResult:
    sha256: str
    expected: str | None
    matched: bool | None  # None when nothing to compare against


class FirmwareProvider(ABC):  # noqa: B024 - concrete defaults by design
    """Base class. Subclasses override only the operations they really support."""

    CAPABILITIES = Capabilities()

    def __init__(self, entry: dict[str, Any], http: HttpClient, cache: Path) -> None:
        self.entry = entry
        self.provider_id: str = entry["id"]
        self.brand_ids: list[str] = list(entry.get("brand_ids") or [])
        self.settings: dict[str, Any] = dict(entry.get("settings") or {})
        self.limitations: str = entry.get("limitations", "")
        self.http = http
        self.cache = cache / "providers" / self.provider_id

    def capabilities(self) -> Capabilities:
        return self.CAPABILITIES

    def _unsupported(self, op: str) -> CapabilityError:
        return CapabilityError(
            f"provider '{self.provider_id}' does not support {op}: "
            f"{self.limitations or 'not implemented'}"
        )

    def discover_devices(self, cancel: threading.Event | None = None) -> DiscoveryResult:
        raise self._unsupported("device discovery")

    def discover_firmware(self, codename: str) -> list[Release]:
        raise self._unsupported("firmware discovery")

    def fetch_metadata(self, release: Release) -> dict[str, Any]:
        raise self._unsupported("metadata fetch")

    def download(self, release: Release, destination: Path) -> Path:
        raise self._unsupported("download")

    def verify(self, local_path: Path, expected_sha256: str | None = None) -> VerifyResult:
        if not self.CAPABILITIES.verify:
            raise self._unsupported("verification")
        digest = sha256_file(local_path) if local_path.is_file() else ""
        if expected_sha256 and local_path.is_file():
            if digest != expected_sha256.lower():
                raise CorruptArchiveError(
                    f"{local_path.name}: SHA-256 {digest} does not match expected {expected_sha256}"
                )
            return VerifyResult(digest, expected_sha256.lower(), True)
        return VerifyResult(digest, None, None)

    def filename_hints(self, name: str) -> dict[str, str]:
        """Metadata guessed from a package file name. Hints only: never used as evidence."""
        return {}
