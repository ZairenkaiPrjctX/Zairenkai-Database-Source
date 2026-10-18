"""Codename-centric catalog storage.

database/
  devices/<brand>/<codename_key>/device.json
  firmware/<brand>/<codename_key>/<firmware_key>/firmware.json
  components/<brand>/<codename_key>/<firmware_key>/<group>.json
  dependencies/<brand>/<codename_key>/<firmware_key>.json
  sources/<provider_id>.json
  staging/unresolved/<provider_id>/<candidate_id>.json
  updates/<report>.json
  index.json, statistics.json
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from afid.errors import NotFoundError, ValidationError
from afid.utils import jsonio
from afid.utils.paths import safe_dirname

VOLATILE = ("last_checked_at",)


@dataclass
class Store:
    root: Path  # the database/ directory

    # ---- paths -------------------------------------------------------------------------------
    def device_path(self, brand: str, key: str) -> Path:
        return self.root / "devices" / safe_dirname(brand) / safe_dirname(key) / "device.json"

    def firmware_dir(self, brand: str, key: str, fw_key: str) -> Path:
        return (
            self.root / "firmware" / safe_dirname(brand) / safe_dirname(key) / safe_dirname(fw_key)
        )

    def components_dir(self, brand: str, key: str, fw_key: str) -> Path:
        return (
            self.root
            / "components"
            / safe_dirname(brand)
            / safe_dirname(key)
            / safe_dirname(fw_key)
        )

    def dependency_path(self, brand: str, key: str, fw_key: str) -> Path:
        return (
            self.root
            / "dependencies"
            / safe_dirname(brand)
            / safe_dirname(key)
            / f"{safe_dirname(fw_key)}.json"
        )

    def staging_path(self, provider: str, candidate_id: str) -> Path:
        return (
            self.root
            / "staging"
            / "unresolved"
            / safe_dirname(provider)
            / f"{safe_dirname(candidate_id)}.json"
        )

    def source_path(self, provider: str) -> Path:
        return self.root / "sources" / f"{safe_dirname(provider)}.json"

    # ---- iteration ---------------------------------------------------------------------------
    def device_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "devices").glob("*/*/device.json"))

    def firmware_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "firmware").glob("*/*/*/firmware.json"))

    def component_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "components").glob("*/*/*/*.json"))

    def dependency_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "dependencies").glob("*/*/*.json"))

    def staging_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "staging" / "unresolved").glob("*/*.json"))

    def source_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "sources").glob("*.json"))

    def devices(self) -> list[dict[str, Any]]:
        return [jsonio.load(p) for p in self.device_files()]

    def firmware(self) -> list[dict[str, Any]]:
        return [jsonio.load(p) for p in self.firmware_files()]

    # ---- lookups -----------------------------------------------------------------------------
    def find_device(self, device_id: str) -> dict[str, Any]:
        for d in self.devices():
            if d["device_id"] == device_id:
                return d
        raise NotFoundError(f"device '{device_id}' not found")

    def find_firmware(self, firmware_id: str) -> tuple[Path, dict[str, Any]]:
        for p in self.firmware_files():
            fw = jsonio.load(p)
            if fw["firmware_id"] == firmware_id:
                return p, fw
        raise NotFoundError(f"firmware '{firmware_id}' not found")

    def components_of(self, fw_path: Path) -> list[dict[str, Any]]:
        rel = fw_path.parent.relative_to(self.root / "firmware")
        comps: list[dict[str, Any]] = []
        for f in sorted((self.root / "components" / rel).glob("*.json")):
            comps.extend(jsonio.load(f)["components"])
        return comps

    # ---- writes ------------------------------------------------------------------------------
    def save_device(self, device: dict[str, Any]) -> bool:
        path = self.device_path(device["brand_id"], device["codename_key"])
        if path.exists():
            device = merge_device(jsonio.load(path), device)
        # Re-verifying an unchanged device must not create a Git diff, so last_verified_at
        # only moves when something else in the record changes.
        return jsonio.write_if_changed(path, device, (*VOLATILE, "last_verified_at"))

    def save_firmware(
        self,
        brand: str,
        key: str,
        fw_key: str,
        firmware: dict[str, Any],
        groups: dict[str, list[dict[str, Any]]],
        edges: list[dict[str, Any]],
    ) -> list[Path]:
        written: list[Path] = []
        fw_path = self.firmware_dir(brand, key, fw_key) / "firmware.json"
        if fw_path.exists():
            old = jsonio.load(fw_path)
            if old["firmware_id"] != firmware["firmware_id"]:
                raise ValidationError(
                    f"{fw_path} holds {old['firmware_id']}, refusing to "
                    f"overwrite with {firmware['firmware_id']}"
                )
        cdir = self.components_dir(brand, key, fw_key)
        for group, comps in sorted(groups.items()):
            doc = {
                "schema_version": "1.0",
                "firmware_id": firmware["firmware_id"],
                "group": group,
                "components": comps,
            }
            if jsonio.write_if_changed(cdir / f"{group}.json", doc):
                written.append(cdir / f"{group}.json")
        for stale in sorted(cdir.glob("*.json")) if cdir.exists() else []:
            if stale.stem not in groups:
                stale.unlink()
                written.append(stale)
        dep = {"schema_version": "1.0", "firmware_id": firmware["firmware_id"], "edges": edges}
        dpath = self.dependency_path(brand, key, fw_key)
        if jsonio.write_if_changed(dpath, dep):
            written.append(dpath)
        # Re-ingesting identical content only changes timestamps, which are ignored here, so
        # the file (and Git) stays untouched.
        if jsonio.write_if_changed(
            fw_path, firmware, VOLATILE + ("ingested_at", "last_updated_at")
        ):
            written.append(fw_path)
        return written


def _union(a: list[Any], b: list[Any]) -> list[Any]:
    out = list(a)
    for item in b:
        if item not in out:
            out.append(item)
    return out


def merge_device(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Merge a re-verified device into its existing record without losing history."""
    for key in ("device_id", "brand_id", "codename_key"):
        if old[key] != new[key]:
            raise ValidationError(f"identity mismatch on {key}: {old[key]} vs {new[key]}")
    merged = dict(old)
    for key in ("product_names", "model_numbers", "aliases", "android_versions"):
        merged[key] = sorted(set(old[key]) | set(new[key]))
    merged["regional_variants"] = _union(old["regional_variants"], new["regional_variants"])
    # Evidence is keyed by (type, source, url, detail); keep the earliest retrieval.
    seen = {
        (e["evidence_type"], e["source"], e.get("url"), e.get("detail")) for e in old["sources"]
    }
    merged["sources"] = list(old["sources"]) + [
        e
        for e in new["sources"]
        if (e["evidence_type"], e["source"], e.get("url"), e.get("detail")) not in seen
    ]
    for k, v in new["soc"].items():
        if v and not old["soc"].get(k):
            merged["soc"] = {**merged["soc"], k: v}
    merged["discovered_at"] = old["discovered_at"] or new["discovered_at"]
    if new["last_verified_at"]:
        merged["last_verified_at"] = new["last_verified_at"]
    return merged
