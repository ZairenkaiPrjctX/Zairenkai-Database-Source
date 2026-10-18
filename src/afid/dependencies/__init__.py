"""Dependency graph construction for one scanned firmware tree.

Edge status semantics:
  resolved   - the target was found where the evidence points (same partition's library
               directory for DT_NEEDED, exact path for init/config references)
  inferred   - a plausible target was found by a weaker method (other partition, name match,
               string present in a binary); the runtime may resolve differently
  unresolved - the referenced name was not found in the scanned tree

Libraries reached through DT_NEEDED from cataloged components are added to the catalog as
vendor_library components when they live on vendor-side partitions (transitively, bounded).
"""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any

from afid.classification import Classification
from afid.models import edge_id
from afid.scanning import FileEntry, Scanner, ScanResult

VENDOR_SIDE = ("vendor", "odm", "vendor_dlkm", "odm_dlkm")
LIB_DIRS = {
    "ELF64": ("lib64", "lib64/hw", "lib64/vndk-sp"),
    "ELF32": ("lib", "lib/hw", "lib/vndk-sp"),
}
SEARCH_PARTITIONS = ("vendor", "odm", "system", "system_ext", "product", "apex")
MAX_DEPTH = 8
MAX_STRINGS_BYTES = 64 * 1024 * 1024
HAL_CATEGORIES = {"thermal_hal", "thermal_engine", "power_hal"}
CONFIG_CATEGORIES = {"thermal_config", "power_json", "power_config", "performance_config"}


def _lib_index(inventory: list[FileEntry]) -> dict[str, list[FileEntry]]:
    index: dict[str, list[FileEntry]] = {}
    for e in inventory:
        if e.path.endswith(".so") or ".so." in e.path:
            index.setdefault(e.path.rsplit("/", 1)[-1], []).append(e)
    return index


def _locate(
    name: str, origin: dict[str, Any], index: dict[str, list[FileEntry]]
) -> tuple[FileEntry | None, str]:
    cands = index.get(name, [])
    elf_class = origin["details"].get("elf", {}).get("elf_class", "ELF64")
    dirs = LIB_DIRS.get(elf_class, LIB_DIRS["ELF64"])

    def in_dirs(e: FileEntry, partition: str) -> bool:
        return e.partition == partition and e.path.rsplit("/", 1)[0] in dirs

    for e in cands:
        if in_dirs(e, origin["partition"]):
            return e, "resolved"
    for part in SEARCH_PARTITIONS:
        for e in cands:
            if in_dirs(e, part):
                return e, "inferred"
    return None, "unresolved"


def build(
    root: Path,
    result: ScanResult,
    scanner: Scanner,
    firmware_id: str,
    provider_id: str,
    user_supplied: bool,
) -> list[dict[str, Any]]:
    edges: dict[str, dict[str, Any]] = {}
    by_path = result.by_full_path()
    index = _lib_index(result.inventory)
    inv_paths = {e.full: e for e in result.inventory}

    def add(
        etype: str,
        src: dict[str, Any],
        to: dict[str, Any] | None,
        to_name: str,
        status: str,
        evidence: str,
    ) -> None:
        eid = edge_id(firmware_id, etype, src["component_id"], to_name)
        edges[eid] = {
            "edge_id": eid,
            "type": etype,
            "from": src["component_id"],
            "to": to["component_id"] if to else None,
            "to_name": to_name,
            "status": status,
            "evidence": evidence,
        }
        src["dependency_refs"] = sorted(set(src["dependency_refs"]) | {eid})

    # DT_NEEDED, transitively through vendor-side libraries.
    queue = deque((c, 0) for c in list(result.components) if c["details"].get("elf"))
    while queue:
        comp, depth = queue.popleft()
        for needed in comp["details"]["elf"].get("needed", []):
            entry, status = _locate(needed, comp, index)
            target = by_path.get(entry.full) if entry else None
            if entry and target is None and entry.partition in VENDOR_SIDE and depth < MAX_DEPTH:
                cls = Classification(
                    "vendor_library",
                    "resolved_dependency",
                    0.6,
                    "content",
                    reasons=[f"DT_NEEDED '{needed}' of {comp['partition']}/{comp['path']}"],
                )
                target = scanner._component(
                    root.resolve(), entry, cls, firmware_id, provider_id, user_supplied
                )
                if target is not None:
                    result.components.append(target)
                    by_path[entry.full] = target
                    if target["details"].get("elf"):
                        queue.append((target, depth + 1))
            where = entry.full if entry else "not found in scanned tree"
            note = "" if target or not entry else " (platform library, not cataloged)"
            add(
                "dt_needed",
                comp,
                target,
                needed,
                status,
                f"DT_NEEDED entry; located: {where}{note}",
            )

    # init service -> binary
    for comp in list(result.components):
        for svc in comp["details"].get("init", {}).get("services", []):
            if svc["name"] not in comp["details"].get("relevant_services", []):
                continue
            full = svc["binary"].lstrip("/")
            target = by_path.get(full)
            exists = full in inv_paths
            status = "resolved" if exists else "unresolved"
            add(
                "init_service_binary",
                comp,
                target,
                svc["binary"],
                status,
                f"service '{svc['name']}' in {comp['path']}"
                + ("" if exists else "; binary not present in scanned tree"),
            )

    # VINTF HAL declarations -> HAL services
    services = [
        c
        for c in result.components
        if c["category"] in HAL_CATEGORIES and c["subcategory"] == "service_binary"
    ]
    # init "interface" lines: AIDL is `interface aidl <hal>.IFoo/<instance>`, HIDL is
    # `interface <hal>@<ver>::IFoo <instance>`; match the HAL name anywhere in the declaration.
    init_ifaces = [
        f"{i['name']} {i['instance']}"
        for c in result.components
        for s in c["details"].get("init", {}).get("services", [])
        for i in s.get("interfaces", [])
    ]
    for comp in result.components:
        for hal in comp["details"].get("vintf", {}).get("hals", []):
            name = hal["name"]
            if not scanner.classifier.relevant(name):
                continue
            # Boundary required: android.hardware.power must not match ...power.stats-service.
            matches = [s for s in services if re.match(re.escape(name) + r"[-@]", s["filename"])]
            if matches:
                declared = any(re.search(re.escape(name) + r"[.@]", k) for k in init_ifaces)
                status = "resolved" if declared else "inferred"
                for s in matches:
                    add(
                        "vintf_declares_hal",
                        comp,
                        s,
                        name,
                        status,
                        "HAL name matches service binary name"
                        + ("; init interface declaration agrees" if status == "resolved" else ""),
                    )
            else:
                add(
                    "vintf_declares_hal",
                    comp,
                    None,
                    name,
                    "unresolved",
                    "declared HAL with no matching service binary in scan",
                )

    # config -> referenced partition paths
    for comp in list(result.components):
        refs = comp["details"].get("config", {}).get("partition_paths", [])
        for ref in refs:
            full = ref.lstrip("/")
            target = by_path.get(full)
            status = "resolved" if full in inv_paths else "unresolved"
            add("config_reference", comp, target, ref, status, "absolute path in config text")

    # HAL/engine binary -> config file whose name appears as a string inside the binary
    configs = [c for c in result.components if c["category"] in CONFIG_CATEGORIES]
    for comp in [
        c for c in result.components if c["category"] in HAL_CATEGORIES and c["file_type"] == "elf"
    ]:
        path = root / comp["partition"] / comp["path"]
        try:
            if path.stat().st_size > MAX_STRINGS_BYTES:
                continue
            blob = path.read_bytes()
        except OSError:
            continue
        for cfg in configs:
            if cfg["filename"].encode() in blob:
                add(
                    "hal_config",
                    comp,
                    cfg,
                    f"/{cfg['partition']}/{cfg['path']}",
                    "inferred",
                    f"file name '{cfg['filename']}' appears as a string in the binary",
                )

    result.components.sort(key=lambda c: (c["partition"], c["path"]))
    return sorted(edges.values(), key=lambda e: e["edge_id"])
