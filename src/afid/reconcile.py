"""Merge per-item delta stores into the catalog, and track per-item ingestion state.

Matrix jobs never write the repository's database. Each job writes its records into its own
delta store (a directory with the database/ layout) plus `item-report.json`; the reconcile
job merges every delta here. Rules:

- every delta record is schema-validated and re-placed by its *content* (brand, codename,
  build), never by the delta's file paths;
- devices merge through Store.save_device (union of evidence, never loses history);
- a firmware build already cataloged from another source keeps its components; the new
  source is added to `source_refs` when the build fingerprint and every common file hash
  agree, otherwise the item is a *conflict* (reported, staged as `conflict`, nothing
  overwritten);
- community candidates for a codename that is now verified are absorbed (afid.ingest);
- nothing is ever deleted; merging the same deltas twice changes nothing.

Ingestion state (database/state/<provider>.json) records each item's last processed
revision, status and attempt count, so the planner skips finished and exhausted items.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid import models
from afid.catalog import Store, merge_source_refs
from afid.catalog.validate import load_validators
from afid.config import Config
from afid.ingest import _absorb_staging
from afid.providers import registry
from afid.utils import jsonio, log
from afid.utils.paths import safe_dirname, sanitize_id
from afid.utils.timeutil import utc_now

LOG = log.get("reconcile")
REPORT = "item-report.json"
FINAL = {
    "analyzed",
    "validated",
    "unchanged",
    "unresolved",
    "restricted",
    "license_review_required",
}


def state_path(store: Store, provider_id: str) -> Path:
    return store.root / "state" / f"{safe_dirname(provider_id)}.json"


def load_state(store: Store, provider_id: str) -> dict[str, Any]:
    p = state_path(store, provider_id)
    if p.exists():
        return dict(jsonio.load(p))
    return {"schema_version": "1.0", "provider_id": provider_id, "items": {}}


@dataclass
class Outcome:
    merged: list[str] = field(default_factory=list)
    refs_added: list[str] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    items: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "merged_firmware": self.merged,
            "source_refs_added": self.refs_added,
            "conflicts": self.conflicts,
            "rejected": self.rejected,
            "written": len(self.written),
            "item_statuses": dict(sorted(self.items.items())),
        }


def _schema_errors(v: Any, doc: Any) -> list[str]:
    return [e.message[:200] for e in v.iter_errors(doc)]


def _component_hashes(comps: list[dict[str, Any]]) -> dict[str, str | None]:
    return {f"{c['partition']}/{c['path']}": c["sha256"] for c in comps}


def merge_delta(cfg: Config, main: Store, delta: Store, out: Outcome) -> None:
    v = load_validators(cfg.schemas_dir)
    devices: dict[str, dict[str, Any]] = {}
    for p in delta.device_files():
        dev = jsonio.load(p)
        errs = _schema_errors(v["device"], dev)
        if errs or dev["brand_id"] not in cfg.brand_ids:
            out.rejected.append({"record": str(p), "reason": "; ".join(errs) or "unknown brand"})
            continue
        if dev["device_id"] != f"{dev['brand_id']}_{models.codename_key(dev['codename'])}":
            out.rejected.append({"record": str(p), "reason": "device_id does not match content"})
            continue
        devices[dev["device_id"]] = dev

    for p in delta.firmware_files():
        fw = jsonio.load(p)
        dev = devices.get(fw["device_id"])
        errs = _schema_errors(v["firmware"], fw)
        if dev is None or errs:
            out.rejected.append(
                {"record": str(p), "reason": "; ".join(errs) or "device record missing in delta"}
            )
            continue
        brand, key = dev["brand_id"], dev["codename_key"]
        fw_key = models.firmware_key(
            fw["build_id"],
            fw["variant"]["region"],
            fw["variant"]["channel"],
            fw.get("build_incremental"),
        )
        if fw["firmware_id"] != f"{dev['device_id']}__{fw_key}":
            out.rejected.append({"record": str(p), "reason": "firmware_id does not match content"})
            continue
        comps = delta.components_of(p)
        groups: dict[str, list[dict[str, Any]]] = {}
        for c in comps:
            groups.setdefault(models.CATEGORY_GROUP[c["category"]], []).append(c)
        bad = [
            e
            for g, cs in groups.items()
            for e in _schema_errors(
                v["component"],
                {
                    "schema_version": "1.0",
                    "firmware_id": fw["firmware_id"],
                    "group": g,
                    "components": cs,
                },
            )
        ]
        dep_path = delta.dependency_path(brand, key, fw_key)
        dep = (
            jsonio.load(dep_path)
            if dep_path.exists()
            else {"schema_version": "1.0", "firmware_id": fw["firmware_id"], "edges": []}
        )
        bad += _schema_errors(v["dependency"], dep)
        if bad:
            out.rejected.append({"record": str(p), "reason": "; ".join(bad[:3])})
            continue

        target = main.firmware_dir(brand, key, fw_key) / "firmware.json"
        if target.exists():
            old = jsonio.load(target)
            reason = _conflict(old, fw, main.components_of(target), comps)
            if reason:
                out.conflicts.append({"firmware_id": fw["firmware_id"], "reason": reason})
                out.written += _stage_conflict(cfg, main, fw, dev, reason)
                continue
            merged = dict(old)
            merged["source_refs"] = merge_source_refs(
                old.get("source_refs", []), fw.get("source_refs", [])
            )
            if merged["source_refs"] != old.get("source_refs", []):
                out.refs_added.append(fw["firmware_id"])
            if jsonio.write_if_changed(
                target,
                merged,
                ("last_checked_at", "ingested_at", "last_updated_at", "retrieved_at"),
            ):
                out.written.append(str(target))
            if main.save_device(dev):
                out.written.append(str(main.device_path(brand, key)))
            continue
        absorbed = _absorb_staging(main, dev)
        if main.save_device(dev):
            out.written.append(str(main.device_path(brand, key)))
        out.written += [
            str(x) for x in main.save_firmware(brand, key, fw_key, fw, groups, dep["edges"])
        ]
        for s in absorbed:
            s.unlink()
            out.written.append(f"{s} (absorbed)")
        out.merged.append(fw["firmware_id"])

    for p in delta.staging_files():
        cand = jsonio.load(p)
        if _schema_errors(v["candidate"], cand):
            out.rejected.append({"record": str(p), "reason": "invalid staging candidate"})
            continue
        if cand["brand_id"] and main.device_path(cand["brand_id"], cand["codename_key"]).exists():
            continue  # already verified; the verified record is authoritative
        dest = main.staging_path(cand["source"]["provider_id"], cand["candidate_id"])
        if jsonio.write_if_changed(dest, cand, ("discovered_at", "retrieved_at")):
            out.written.append(str(dest))


def _conflict(
    old: dict[str, Any],
    new: dict[str, Any],
    old_comps: list[dict[str, Any]],
    new_comps: list[dict[str, Any]],
) -> str | None:
    a, b = old.get("build_fingerprint"), new.get("build_fingerprint")
    if a and b and a != b:
        return f"build fingerprint differs: {a} vs {b}"
    ha, hb = _component_hashes(old_comps), _component_hashes(new_comps)
    diff = sorted(k for k in ha.keys() & hb.keys() if ha[k] and hb[k] and ha[k] != hb[k])
    if diff:
        return f"{len(diff)} file(s) differ for the same build, e.g. {diff[0]}"
    return None


def _stage_conflict(
    cfg: Config, main: Store, fw: dict[str, Any], dev: dict[str, Any], reason: str
) -> list[str]:
    ref = (fw.get("source_refs") or [{}])[0]
    provider = ref.get("provider_id") or fw["source"]["provider_id"]
    entry = next((e for e in registry.entries(cfg) if e["id"] == provider), None)
    if entry is None:
        return []
    cand_id = (
        f"{dev['brand_id']}__{dev['codename_key']}__conflict-"
        + sanitize_id(str(ref.get("revision") or fw["build_id"]))[:12]
    )
    cand = {
        "schema_version": "1.0",
        "candidate_id": cand_id,
        "brand_id": dev["brand_id"],
        "brand_inference": "from the conflicting source's build.prop",
        "codename": dev["codename"],
        "codename_key": dev["codename_key"],
        "codename_status": "conflict",
        "product_names": [],
        "model_numbers": dev["model_numbers"],
        "soc": dev["soc"],
        "release_date": None,
        "evidence": dev["sources"][:5],
        "unresolved_reason": f"conflicts with cataloged {fw['firmware_id']}: {reason}",
        "discovered_at": utc_now(),
        "source": {
            "provider_id": provider,
            "source_type": fw["source"]["source_type"],
            "url": ref.get("url"),
            "revision": ref.get("revision"),
            "snapshot": None,
        },
        "license": dict(entry["data_license"]),
        "verification": {
            "status": "unverified",
            "outstanding_requirements": ["human review of the conflicting dumps"],
        },
        "distribution_status": "unknown",
        "firmware_payload_ingested": False,
    }
    dest = main.staging_path(provider, cand_id)
    return [str(dest)] if jsonio.write_if_changed(dest, cand, ("discovered_at",)) else []


def record_item(main: Store, report: dict[str, Any], retry_limit: int) -> Path | None:
    """Update database/state/<provider>.json from one job's item report."""
    provider = report["provider_id"]
    state = load_state(main, provider)
    prev = state["items"].get(report["item_id"], {})
    same_rev = prev.get("revision") == report.get("revision")
    attempts = (prev.get("attempts", 0) if same_rev else 0) + 1
    status = report.get("status", "failed")
    # A failed item is retried by the planner until `attempts` reaches RETRY_LIMIT at the same
    # revision; a new revision starts again from zero.
    state["items"][report["item_id"]] = {
        "revision": report.get("revision"),
        "status": status,
        "attempts": attempts if status == "failed" else 0,
        "exhausted": status == "failed" and attempts >= retry_limit,
        "firmware_id": report.get("firmware_id"),
        "error": (report.get("error") or report.get("detail") or None),
        "updated_at": utc_now(),
    }
    state["items"] = dict(sorted(state["items"].items()))
    p = state_path(main, provider)
    return p if jsonio.write_if_changed(p, state, ("updated_at",)) else None


def reconcile(cfg: Config, deltas: list[Path], main: Store | None = None) -> Outcome:
    main = main or Store(cfg.database)
    out = Outcome()
    retry_limit = int(cfg.settings["resources"]["defaults"]["RETRY_LIMIT"])
    for root in sorted(deltas):
        db = root / "database" if (root / "database").is_dir() else root
        merge_delta(cfg, main, Store(db), out)
        rep_path = root / REPORT
        if rep_path.is_file():
            try:
                report = json.loads(rep_path.read_text())
            except ValueError:
                out.rejected.append({"record": str(rep_path), "reason": "invalid JSON"})
                continue
            known = {e["id"] for e in registry.entries(cfg)}
            if {"provider_id", "item_id"} <= report.keys() and report["provider_id"] in known:
                written = record_item(main, report, retry_limit)
                if written:
                    out.written.append(str(written))
                out.items[report.get("status", "failed")] = (
                    out.items.get(report.get("status", "failed"), 0) + 1
                )
    return out
