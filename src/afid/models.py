"""Domain constants and record builders. Records are plain dicts validated by JSON Schema;
these helpers create them with every required field, so builders and schemas stay in sync."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from afid import __version__
from afid.hashing import stable_id
from afid.utils.paths import sanitize_id

SCHEMA_VERSION = "1.0"

CATEGORIES = (
    "thermal_hal",
    "thermal_service",
    "thermal_config",
    "thermal_engine",
    "power_hal",
    "power_config",
    "power_json",
    "power_profile",
    "performance_config",
    "vendor_library",
    "init_service",
    "init_script",
    "vintf_manifest",
    "supporting_metadata",
    "unknown",
)

# Category -> file name (without .json) under database/components/<brand>/<codename>/<build>/
CATEGORY_GROUP = {
    "thermal_hal": "thermal_hal",
    "thermal_service": "thermal_hal",
    "thermal_config": "thermal_config",
    "thermal_engine": "thermal_config",
    "power_hal": "power_hal",
    "power_config": "power_config",
    "power_json": "power_config",
    "power_profile": "power_config",
    "performance_config": "power_config",
    "vendor_library": "vendor_libraries",
    "init_service": "init",
    "init_script": "init",
    "vintf_manifest": "vintf",
    "supporting_metadata": "metadata",
    "unknown": "unknown",
}
GROUPS = tuple(sorted(set(CATEGORY_GROUP.values())))

_CODENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class Evidence(TypedDict, total=False):
    evidence_type: str
    source: str
    url: str | None
    retrieved_at: str
    detail: str | None
    confidence: float


def valid_codename(codename: str) -> bool:
    return bool(_CODENAME_RE.match(codename))


def codename_key(codename: str) -> str:
    """Directory key for a codename: the codename lowercased (codenames such as 'Mi439' keep
    their original case in the record; directories use the key to avoid case collisions)."""
    if not valid_codename(codename):
        raise ValueError(f"invalid codename {codename!r}")
    return codename.lower()


def device_id(brand_id: str, codename: str) -> str:
    return f"{brand_id}_{codename_key(codename)}"


def firmware_key(build_id: str, region: str | None = None, channel: str | None = None) -> str:
    parts = [sanitize_id(build_id)] + [sanitize_id(p) for p in (region, channel) if p]
    return "_".join(parts)


def firmware_id(
    dev_id: str, build_id: str, region: str | None = None, channel: str | None = None
) -> str:
    return f"{dev_id}__{firmware_key(build_id, region, channel)}"


def component_id(fw_id: str, partition: str, path: str) -> str:
    return stable_id("c", fw_id, partition, path)


def edge_id(fw_id: str, etype: str, src: str, to_name: str) -> str:
    return stable_id("d", fw_id, etype, src, to_name)


def new_device(brand_id: str, codename: str, sources: list[Evidence]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "device_id": device_id(brand_id, codename),
        "brand_id": brand_id,
        "codename": codename,
        "codename_key": codename_key(codename),
        "codename_status": "verified",
        "product_names": [],
        "model_numbers": [],
        "regional_variants": [],
        "soc": {"vendor": None, "platform": None, "architecture": None},
        "aliases": [],
        "canonical_device_id": None,
        "shared_identity": None,
        "android_versions": [],
        "sources": list(sources),
        "discovered_at": None,
        "last_verified_at": None,
    }


def new_firmware(
    dev_id: str,
    build_id: str,
    provider_id: str,
    source_type: str,
    region: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "firmware_id": firmware_id(dev_id, build_id, region, channel),
        "device_id": dev_id,
        "build_id": build_id,
        "variant": {"region": region, "channel": channel},
        "firmware_version": None,
        "android_release": None,
        "api_level": None,
        "security_patch": None,
        "vendor_security_patch": None,
        "build_fingerprint": None,
        "kernel_version": None,
        "release_date": None,
        "source": {
            "provider_id": provider_id,
            "source_type": source_type,
            "url": None,
            "archive_name": None,
            "archive_sha256": None,
            "archive_size": None,
            "official_checksum": None,
        },
        "partitions": [],
        "ingestion": {
            "status": "discovered",
            "afid_version": __version__,
            "tools": [],
            "ingested_at": None,
        },
        "validation_status": "pending",
        "distribution_status": "unknown",
        "component_groups": [],
        "component_count": 0,
        "last_checked_at": None,
        "last_updated_at": None,
        "warnings": [],
        "errors": [],
    }
