"""Deterministic index, statistics and library map, computed only from database records.

No timestamps are written, so rebuilding unchanged data yields byte-identical files.
`database_digest` is a SHA-256 over every source record, letting CI prove that the committed
statistics correspond to the committed data.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from afid.catalog import Store
from afid.utils import jsonio

PENDING_REVIEW = {"unknown", "user_supplied"}


def _digest(store: Store) -> str:
    h = hashlib.sha256()
    for group in (
        store.device_files(),
        store.firmware_files(),
        store.component_files(),
        store.dependency_files(),
        store.staging_files(),
    ):
        for p in group:
            h.update(p.relative_to(store.root).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def build(
    store: Store, brand_ids: list[str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    devices = store.devices()
    fw_by_device: dict[str, list[dict[str, Any]]] = {}
    for fw in store.firmware():
        fw_by_device.setdefault(fw["device_id"], []).append(fw)
    comps: list[dict[str, Any]] = []
    for p in store.component_files():
        comps.extend(jsonio.load(p)["components"])
    edges: list[dict[str, Any]] = []
    for p in store.dependency_files():
        edges.extend(jsonio.load(p)["edges"])
    staged = [jsonio.load(p) for p in store.staging_files()]

    by_sha: dict[str, set[str]] = {}
    for c in comps:
        if c["sha256"]:
            by_sha.setdefault(c["sha256"], set()).add(c["firmware_id"])

    index: dict[str, Any] = {
        "schema_version": "1.0",
        "devices": [
            {
                "device_id": d["device_id"],
                "brand_id": d["brand_id"],
                "codename": d["codename"],
                "product_names": d["product_names"],
                "canonical_device_id": d["canonical_device_id"],
                "firmware_ids": sorted(
                    f["firmware_id"] for f in fw_by_device.get(d["device_id"], [])
                ),
            }
            for d in sorted(devices, key=lambda d: d["device_id"])
        ],
        "firmware": [
            {
                "firmware_id": f["firmware_id"],
                "device_id": f["device_id"],
                "build_id": f["build_id"],
                "android_release": f["android_release"],
                "security_patch": f["security_patch"],
                "component_count": f["component_count"],
            }
            for fws in fw_by_device.values()
            for f in fws
        ],
        # Content shared by several builds: the same SHA-256 recorded in more than one firmware.
        "shared_content": {sha: sorted(ids) for sha, ids in sorted(by_sha.items()) if len(ids) > 1},
    }
    index["firmware"].sort(key=lambda f: f["firmware_id"])

    cat = Counter(c["category"] for c in comps)
    edge_status = Counter(e["status"] for e in edges)
    per_brand: dict[str, dict[str, int]] = {}
    for b in brand_ids:
        b_devices = [d for d in devices if d["brand_id"] == b]
        b_fw = [f for d in b_devices for f in fw_by_device.get(d["device_id"], [])]
        b_fw_ids = {f["firmware_id"] for f in b_fw}
        per_brand[b] = {
            "devices": len(b_devices),
            "firmware_builds": len(b_fw),
            "devices_with_firmware": sum(1 for d in b_devices if fw_by_device.get(d["device_id"])),
            "components": sum(1 for c in comps if c["firmware_id"] in b_fw_ids),
        }
    stats = {
        "schema_version": "1.0",
        "database_digest": _digest(store),
        "brands": len(brand_ids),
        "devices": len(devices),
        "firmware_builds": sum(len(v) for v in fw_by_device.values()),
        "components": len(comps),
        "thermal_hal": cat["thermal_hal"] + cat["thermal_service"],
        "thermal_config": cat["thermal_config"] + cat["thermal_engine"],
        "power_hal": cat["power_hal"],
        "power_config": cat["power_config"]
        + cat["power_json"]
        + cat["power_profile"]
        + cat["performance_config"],
        "vendor_libraries": cat["vendor_library"],
        "init_related": cat["init_service"] + cat["init_script"],
        "vintf": cat["vintf_manifest"],
        "unknown": cat["unknown"],
        "by_category": dict(sorted(cat.items())),
        "dependencies_resolved": edge_status["resolved"],
        "dependencies_inferred": edge_status["inferred"],
        "dependencies_unresolved": edge_status["unresolved"],
        "pending_license_review": sum(
            1 for c in comps if c["distribution_status"] in PENDING_REVIEW
        ),
        # Staging candidates are unverified and never counted as devices above.
        "staging_candidates": len(staged),
        "staging_unverified": sum(1 for s in staged if s["verification"]["status"] == "unverified"),
        "staging_by_brand": dict(
            sorted(Counter(s["brand_id"] or "unbranded" for s in staged).items())
        ),
        "coverage_by_brand": per_brand,
    }

    # Library map: which libraries accompany which HAL/engine components, across builds.
    by_id = {c["component_id"]: c for c in comps}
    libmap: dict[str, dict[str, Any]] = {}
    for e in edges:
        if e["type"] != "dt_needed":
            continue
        src = by_id.get(e["from"])
        if src is None:
            continue
        entry = libmap.setdefault(
            e["to_name"], {"needed_by": set(), "firmware": set(), "statuses": set()}
        )
        entry["needed_by"].add(f"{src['partition']}/{src['path']}")
        entry["firmware"].add(src["firmware_id"])
        entry["statuses"].add(e["status"])
    library_map = {
        "schema_version": "1.0",
        "libraries": {
            name: {k: sorted(v) for k, v in val.items()} for name, val in sorted(libmap.items())
        },
    }
    return index, stats, library_map


def write(store: Store, brand_ids: list[str]) -> list[Path]:
    index, stats, library_map = build(store, brand_ids)
    out = []
    for name, doc in (("index.json", index), ("statistics.json", stats)):
        if jsonio.write_if_changed(store.root / name, doc):
            out.append(store.root / name)
    lib_path = store.root / "dependencies" / "library_map.json"
    if jsonio.write_if_changed(lib_path, library_map):
        out.append(lib_path)
    return out


def check(store: Store, brand_ids: list[str]) -> list[str]:
    """Return generated files that are missing or stale (for CI)."""
    index, stats, library_map = build(store, brand_ids)
    stale = []
    for path, doc in (
        (store.root / "index.json", index),
        (store.root / "statistics.json", stats),
        (store.root / "dependencies" / "library_map.json", library_map),
    ):
        if not path.exists() or jsonio.load(path) != doc:
            stale.append(path.relative_to(store.root.parent).as_posix())
    return stale
