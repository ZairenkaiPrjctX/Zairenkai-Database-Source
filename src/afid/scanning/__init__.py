"""Recursive scanner for an extracted firmware tree.

Layout expected: <root>/<partition>/<path inside partition>, e.g. root/vendor/bin/hw/...
Files directly under <root> get partition "root". Nothing found in the tree is executed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid.classification import Classification, Classifier
from afid.hashing import sha256_file
from afid.licensing import Policy
from afid.models import component_id
from afid.parsers import buildprop, configs, elf, init_rc, vintf
from afid.utils import log
from afid.utils.paths import symlink_stays_inside

LOG = log.get("scan")
CONFIG_CATEGORIES = {
    "thermal_config",
    "power_json",
    "power_config",
    "power_profile",
    "performance_config",
}
TEXT_EXT = {".rc", ".conf", ".txt", ".prop", ".cfg", ".ini"}


@dataclass
class FileEntry:
    partition: str
    path: str
    size: int | None
    sha256: str | None
    is_symlink: bool
    symlink_target: str | None
    is_elf: bool

    @property
    def full(self) -> str:
        return f"{self.partition}/{self.path}"


@dataclass
class ScanResult:
    inventory: list[FileEntry] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    build_props: dict[str, dict[str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def by_full_path(self) -> dict[str, dict[str, Any]]:
        return {f"{c['partition']}/{c['path']}": c for c in self.components}


def _file_type(entry: FileEntry) -> str:
    if entry.is_symlink:
        return "symlink"
    if entry.is_elf:
        return "elf"
    ext = os.path.splitext(entry.path)[1].lower()
    if ext == ".json":
        return "json"
    if ext == ".xml":
        return "xml"
    if ext in TEXT_EXT:
        return "text"
    return "binary"


class Scanner:
    def __init__(
        self, classifier: Classifier, policy: Policy, partitions: list[str], max_hash_bytes: int
    ) -> None:
        self.classifier = classifier
        self.policy = policy
        self.partitions = set(partitions)
        self.max_hash_bytes = max_hash_bytes

    # ---- inventory -------------------------------------------------------------------------
    def inventory(self, root: Path, result: ScanResult) -> None:
        root = root.resolve()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            here = Path(dirpath)
            # Symlinked directories appear in dirnames; record them as symlinks, don't descend.
            for d in list(dirnames):
                if (here / d).is_symlink():
                    filenames.append(d)
                    dirnames.remove(d)
            for name in sorted(filenames):
                p = here / name
                rel = p.relative_to(root).as_posix()
                part, _, inner = rel.partition("/")
                if not inner:
                    part, inner = "root", rel
                if part not in self.partitions and part != "root":
                    result.warnings.append(f"unrecognized top-level directory '{part}' scanned")
                result.inventory.append(self._entry(root, p, part, inner, result))
        result.warnings = sorted(set(result.warnings))

    def _entry(self, root: Path, p: Path, part: str, inner: str, result: ScanResult) -> FileEntry:
        if p.is_symlink():
            target = os.readlink(p)
            if not symlink_stays_inside(root, p, target):
                result.warnings.append(f"{part}/{inner}: symlink target escapes tree ({target})")
            return FileEntry(part, inner, None, None, True, target, False)
        size = p.stat().st_size
        digest = None
        if size <= self.max_hash_bytes:
            digest = sha256_file(p)
        else:
            result.warnings.append(f"{part}/{inner}: {size} bytes exceeds hash limit; not hashed")
        return FileEntry(part, inner, size, digest, False, None, elf.is_elf(p))

    # ---- scan --------------------------------------------------------------------------------
    def scan(
        self, root: Path, firmware_id: str, provider_id: str, user_supplied: bool
    ) -> ScanResult:
        result = ScanResult()
        self.inventory(root, result)
        root = root.resolve()
        for entry in result.inventory:
            cls = self.classifier.classify(entry.full, entry.is_elf)
            if cls is None:
                if not self.classifier.catalog_unknown(entry.full):
                    continue
                cls = Classification(
                    "unknown",
                    "unmatched",
                    0.0,
                    "unmatched",
                    reasons=["no classification rule matched"],
                )
            comp = self._component(root, entry, cls, firmware_id, provider_id, user_supplied)
            if comp is not None:
                if comp["details"].get("build_props"):
                    result.build_props[entry.full] = comp["details"]["build_props"]
                result.components.append(comp)
        _mark_duplicates(result.components)
        result.components.sort(key=lambda c: (c["partition"], c["path"]))
        LOG.info(
            "scanned %d files, %d catalog components", len(result.inventory), len(result.components)
        )
        return result

    def _component(
        self,
        root: Path,
        entry: FileEntry,
        cls: Classification,
        fw_id: str,
        provider_id: str,
        user_supplied: bool,
    ) -> dict[str, Any] | None:
        details: dict[str, Any] = {}
        parser: dict[str, Any] = {"name": None, "status": "not_applicable", "error": None}
        path = (
            root / entry.partition / entry.path if entry.partition != "root" else root / entry.path
        )
        if not entry.is_symlink:
            try:
                name = self._parse(path, entry, cls, details)
                if name:
                    parser = {"name": name, "status": "ok", "error": None}
            except (
                elf.ElfError,
                vintf.XmlRejected,
                ValueError,
                UnicodeDecodeError,
                OSError,
            ) as exc:
                parser = {
                    "name": _parser_name(entry, cls),
                    "status": "failed",
                    "error": str(exc)[:300],
                }
        if cls.category == "init_script" and cls.subcategory == "init_rc":
            services = details.get("init", {}).get("services", [])
            relevant = [
                s["name"] for s in services if self.classifier.relevant(s["name"], s["binary"])
            ]
            if not relevant and not self.classifier.relevant(entry.path):
                return None  # unrelated init file: stays in the local inventory only
            if relevant:
                cls.category = "init_service"
                cls.reasons.append(f"defines relevant service(s): {', '.join(relevant)}")
            details["relevant_services"] = relevant
        status = self.policy.status_for(entry.sha256, user_supplied)
        return {
            "component_id": component_id(fw_id, entry.partition, entry.path),
            "firmware_id": fw_id,
            "category": cls.category,
            "subcategory": cls.subcategory,
            "partition": entry.partition,
            "path": entry.path,
            "filename": entry.path.rsplit("/", 1)[-1],
            "file_type": _file_type(entry),
            "size": entry.size,
            "sha256": entry.sha256,
            "symlink_target": entry.symlink_target,
            "classification": cls.as_dict(),
            "parser": parser,
            "details": details,
            "license_status": self.policy.license_for(entry.sha256),
            "distribution_status": status,
            "provenance": {"firmware_id": fw_id, "source_provider": provider_id, "container": None},
            "dependency_refs": [],
            "duplicate_of": None,
            "validation_status": "valid" if parser["status"] != "failed" else "review_required",
        }

    def _parse(
        self, path: Path, entry: FileEntry, cls: Classification, details: dict[str, Any]
    ) -> str | None:
        if entry.is_elf:
            details["elf"] = elf.parse_file(path).as_dict()
            return "elf"
        if cls.category == "vintf_manifest":
            details["vintf"] = vintf.parse(path.read_bytes())
            return "vintf"
        if cls.category == "init_script":
            details["init"] = init_rc.parse(path.read_text("utf-8", "replace"))
            return "init_rc"
        if cls.category == "supporting_metadata" and cls.subcategory == "build_prop":
            details["build_props"] = buildprop.parse(path.read_text("utf-8", "replace"))
            return "build_prop"
        if cls.category in CONFIG_CATEGORIES:
            name, summary = configs.summarize(path.read_bytes(), cls.subcategory, entry.path)
            details["config"] = summary
            return name
        return None


def _parser_name(entry: FileEntry, cls: Classification) -> str | None:
    if entry.is_elf:
        return "elf"
    return {"vintf_manifest": "vintf", "init_script": "init_rc"}.get(cls.category, "config")


def _mark_duplicates(components: list[dict[str, Any]]) -> None:
    """Identical content (same SHA-256) at a second path points to the first record.
    Same file names with different content stay independent records."""
    first: dict[str, str] = {}
    for comp in sorted(components, key=lambda c: (c["partition"], c["path"])):
        sha = comp["sha256"]
        if sha is None:
            continue
        if sha in first:
            comp["duplicate_of"] = first[sha]
        else:
            first[sha] = comp["component_id"]
