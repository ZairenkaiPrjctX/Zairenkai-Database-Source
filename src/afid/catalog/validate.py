"""Database validation: schemas, references, codename layout, provenance, payload policy."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from afid.hashing import is_sha256
from afid.models import CATEGORY_GROUP, codename_key, firmware_key
from afid.utils import jsonio

KNOWN_SCHEMA_VERSIONS = {"1.0"}
GENERATED = {"index.json", "statistics.json"}
# Must equal codename_verification.verifying_evidence in config/source_policy.yml (tested).
VERIFYING_EVIDENCE = frozenset(
    {"firmware_build_prop", "dump_build_prop", "official_ota_metadata", "official_source"}
)


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
            "ok": not self.errors,
        }


def load_validators(schemas_dir: Path) -> dict[str, Draft202012Validator]:
    out = {}
    for name in (
        "device",
        "firmware",
        "component",
        "dependency",
        "source",
        "candidate",
        "report",
        "state",
    ):
        schema = json.loads((schemas_dir / f"{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        out[name] = Draft202012Validator(schema)
    return out


def _schema(v: Draft202012Validator, doc: Any, rel: str, res: Result) -> bool:
    errs = sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))
    for e in errs[:20]:
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        res.errors.append(f"{rel}: schema: {loc}: {e.message[:200]}")
    return not errs


def validate(db: Path, schemas_dir: Path, brand_ids: list[str]) -> Result:
    res = Result()
    v = load_validators(schemas_dir)

    def rel(p: Path) -> str:
        return p.relative_to(db.parent).as_posix()

    def load(p: Path) -> Any | None:
        try:
            doc = jsonio.load(p)
        except (OSError, ValueError) as exc:
            res.errors.append(f"{rel(p)}: unreadable JSON ({exc})")
            return None
        if (
            isinstance(doc, dict)
            and "schema_version" in doc
            and doc["schema_version"] not in KNOWN_SCHEMA_VERSIONS
        ):
            res.errors.append(f"{rel(p)}: unknown schema_version {doc['schema_version']!r}")
            return None
        return doc

    # Payload guard: database/ holds JSON metadata only.
    for p in sorted(db.rglob("*")):
        if p.is_symlink():
            res.errors.append(f"{rel(p)}: symlinks are not allowed in database/")
        elif p.is_file() and p.suffix != ".json" and p.name not in (".gitkeep", "README.md"):
            res.errors.append(f"{rel(p)}: only JSON metadata may live in database/")
        elif p.is_file() and p.suffix == ".json" and p.read_bytes()[:4] == b"\x7fELF":
            res.errors.append(f"{rel(p)}: binary payload in database/")

    # ---- devices ---------------------------------------------------------------------------
    devices: dict[str, dict[str, Any]] = {}
    by_codename: dict[str, list[str]] = {}
    for p in sorted((db / "devices").glob("**/*.json")):
        parts = p.relative_to(db / "devices").parts
        if len(parts) != 3 or parts[2] != "device.json":
            res.errors.append(
                f"{rel(p)}: device records must be devices/<brand>/<codename>/device.json"
            )
            continue
        d = load(p)
        if d is None or not _schema(v["device"], d, rel(p), res):
            continue
        brand, key = parts[0], parts[1]
        if brand not in brand_ids or d["brand_id"] != brand:
            res.errors.append(f"{rel(p)}: brand directory '{brand}' != brand_id '{d['brand_id']}'")
        try:
            expected_key = codename_key(d["codename"])
        except ValueError as exc:
            res.errors.append(f"{rel(p)}: {exc}")
            continue
        if d["codename_key"] != expected_key or key != expected_key:
            res.errors.append(
                f"{rel(p)}: directory '{key}' must equal codename key "
                f"'{expected_key}' of codename '{d['codename']}'"
            )
        if d["device_id"] != f"{d['brand_id']}_{expected_key}":
            res.errors.append(f"{rel(p)}: device_id must be '<brand_id>_<codename_key>'")
        if not any(e["evidence_type"] in VERIFYING_EVIDENCE for e in d["sources"]):
            res.errors.append(
                f"{rel(p)}: verified codename without verifying evidence "
                "(firmware or dump build.prop, official OTA metadata or official source)"
            )
        if d["device_id"] in devices:
            res.errors.append(f"{rel(p)}: duplicate device_id {d['device_id']}")
        devices[d["device_id"]] = d
        by_codename.setdefault(expected_key, []).append(d["device_id"])
    for d in devices.values():
        for ref in [d["canonical_device_id"]] + (d["shared_identity"] or {}).get("device_ids", []):
            if ref and ref not in devices:
                res.errors.append(f"device {d['device_id']}: references unknown device {ref}")
    alias_owner = {a.lower(): d["device_id"] for d in devices.values() for a in d["aliases"]}
    for d in devices.values():
        owner = alias_owner.get(d["codename_key"])
        if (
            owner
            and owner != d["device_id"]
            and owner
            not in ([d["canonical_device_id"]] + (d["shared_identity"] or {}).get("device_ids", []))
        ):
            res.errors.append(
                f"device {d['device_id']}: codename is an alias of {owner} "
                "with no recorded identity relation"
            )
    for key, ids in sorted(by_codename.items()):
        if len(ids) > 1:
            linked = all(
                devices[i]["shared_identity"] or devices[i]["canonical_device_id"] for i in ids
            )
            msg = f"codename '{key}' used by {', '.join(sorted(ids))}"
            if not linked:
                res.warnings.append(
                    msg + " without shared_identity/canonical_device_id; "
                    "review whether these are rebrands or distinct devices"
                )

    # ---- firmware ----------------------------------------------------------------------------
    firmware: dict[str, dict[str, Any]] = {}
    fw_dirs: dict[str, Path] = {}
    for p in sorted((db / "firmware").glob("**/*.json")):
        parts = p.relative_to(db / "firmware").parts
        if len(parts) != 4 or parts[3] != "firmware.json":
            res.errors.append(
                f"{rel(p)}: firmware records must be "
                "firmware/<brand>/<codename>/<build>/firmware.json"
            )
            continue
        fw = load(p)
        if fw is None or not _schema(v["firmware"], fw, rel(p), res):
            continue
        dev = devices.get(fw["device_id"])
        if dev is None:
            res.errors.append(f"{rel(p)}: device {fw['device_id']} does not exist")
        elif (parts[0], parts[1]) != (dev["brand_id"], dev["codename_key"]):
            res.errors.append(f"{rel(p)}: path does not match device {fw['device_id']}")
        fkey = firmware_key(
            fw["build_id"],
            fw["variant"]["region"],
            fw["variant"]["channel"],
            fw.get("build_incremental"),
        )
        if parts[2] != fkey or fw["firmware_id"] != f"{fw['device_id']}__{fkey}":
            res.errors.append(f"{rel(p)}: directory/firmware_id must use firmware key '{fkey}'")
        if fw["firmware_id"] in firmware:
            res.errors.append(f"{rel(p)}: firmware_id collision {fw['firmware_id']}")
        sha = fw["source"]["archive_sha256"]
        if sha is not None and not is_sha256(sha):
            res.errors.append(f"{rel(p)}: archive_sha256 is not a SHA-256 hex digest")
        if not fw["source"]["provider_id"]:
            res.errors.append(f"{rel(p)}: missing provenance (source.provider_id)")
        firmware[fw["firmware_id"]] = fw
        fw_dirs[fw["firmware_id"]] = p.parent

    # ---- components --------------------------------------------------------------------------
    components: dict[str, dict[str, Any]] = {}
    per_fw: dict[str, int] = {}
    groups_seen: dict[str, set[str]] = {}
    for p in sorted((db / "components").glob("**/*.json")):
        parts = p.relative_to(db / "components").parts
        if len(parts) != 4:
            res.errors.append(
                f"{rel(p)}: components must be components/<brand>/<codename>/<build>/<group>.json"
            )
            continue
        doc = load(p)
        if doc is None or not _schema(v["component"], doc, rel(p), res):
            continue
        fw_id = doc["firmware_id"]
        fw_dir = fw_dirs.get(fw_id)
        if fw_dir is None:
            res.errors.append(f"{rel(p)}: firmware {fw_id} does not exist")
        elif fw_dir.relative_to(db / "firmware").parts != parts[:3]:
            res.errors.append(f"{rel(p)}: path does not match firmware {fw_id}")
        if doc["group"] != p.stem:
            res.errors.append(f"{rel(p)}: group '{doc['group']}' != file name")
        groups_seen.setdefault(fw_id, set()).add(doc["group"])
        for c in doc["components"]:
            cid = c["component_id"]
            if cid in components:
                res.errors.append(f"{rel(p)}: duplicate component_id {cid}")
            if c["firmware_id"] != fw_id or c["provenance"]["firmware_id"] != fw_id:
                res.errors.append(f"{rel(p)}: component {cid} belongs to another firmware")
            if CATEGORY_GROUP[c["category"]] != doc["group"]:
                res.errors.append(
                    f"{rel(p)}: component {cid} category {c['category']} "
                    f"belongs in group {CATEGORY_GROUP[c['category']]}"
                )
            if c["file_type"] != "symlink" and c["sha256"] is None:
                res.warnings.append(f"{rel(p)}: component {cid} has no SHA-256 (too large?)")
            components[cid] = c
            per_fw[fw_id] = per_fw.get(fw_id, 0) + 1
    for c in components.values():
        if c["duplicate_of"] and (
            c["duplicate_of"] not in components
            or components[c["duplicate_of"]]["sha256"] != c["sha256"]
        ):
            res.errors.append(
                f"component {c['component_id']}: duplicate_of must reference a "
                "component with the same SHA-256"
            )
    for fw_id, fw in firmware.items():
        if fw["component_count"] != per_fw.get(fw_id, 0):
            res.errors.append(
                f"firmware {fw_id}: component_count {fw['component_count']} != "
                f"{per_fw.get(fw_id, 0)} records"
            )
        if set(fw["component_groups"]) != groups_seen.get(fw_id, set()):
            res.errors.append(f"firmware {fw_id}: component_groups does not match group files")

    # ---- dependencies ------------------------------------------------------------------------
    for p in sorted((db / "dependencies").glob("**/*.json")):
        if p.relative_to(db / "dependencies").as_posix() == "library_map.json":
            continue  # generated by `afid dependencies build`
        if len(p.relative_to(db / "dependencies").parts) != 3:
            res.errors.append(f"{rel(p)}: must be dependencies/<brand>/<codename>/<build>.json")
            continue
        doc = load(p)
        if doc is None or not _schema(v["dependency"], doc, rel(p), res):
            continue
        if doc["firmware_id"] not in firmware:
            res.errors.append(f"{rel(p)}: firmware {doc['firmware_id']} does not exist")
        for e in doc["edges"]:
            for end in (e["from"], e["to"]):
                if end is not None and end not in components:
                    res.errors.append(
                        f"{rel(p)}: edge {e['edge_id']} references unknown component {end}"
                    )
            if (
                e["status"] == "resolved"
                and e["type"] == "dt_needed"
                and e["to"] is None
                and "platform library" not in e["evidence"]
                and "content not fetched" not in e["evidence"]
            ):
                res.errors.append(f"{rel(p)}: edge {e['edge_id']} resolved without target")

    # ---- staging and sources -----------------------------------------------------------------
    staged = 0
    for p in sorted((db / "staging").glob("**/*.json")):
        doc = load(p)
        if doc is None or not _schema(v["candidate"], doc, rel(p), res):
            continue
        staged += 1
    for p in sorted((db / "sources").glob("*.json")):
        doc = load(p)
        if (
            doc is not None
            and _schema(v["source"], doc, rel(p), res)
            and doc["provider_id"] != p.stem
        ):
            res.errors.append(f"{rel(p)}: provider_id must equal file name")
    for p in sorted((db / "sources").glob("*/*.json")):  # sharded firmware-item snapshots
        doc = load(p)
        if (
            doc is not None
            and _schema(v["source"], doc, rel(p), res)
            and doc["provider_id"] != p.parent.name
        ):
            res.errors.append(f"{rel(p)}: provider_id must equal the directory name")
    for p in sorted((db / "state").glob("*.json")):
        doc = load(p)
        if (
            doc is not None
            and _schema(v["state"], doc, rel(p), res)
            and doc["provider_id"] != p.stem
        ):
            res.errors.append(f"{rel(p)}: provider_id must equal file name")
    for p in sorted((db / "updates").glob("*.json")):
        doc = load(p)
        if doc is not None:
            _schema(v["report"], doc, rel(p), res)

    res.counts = {
        "devices": len(devices),
        "firmware": len(firmware),
        "components": len(components),
        "staging_candidates": staged,
    }
    return res
