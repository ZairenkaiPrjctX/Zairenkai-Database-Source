"""Discovery snapshots, update detection, and firmware history comparison.

Rules:
- A change is reported only when a revision marker (content hash, git blob SHA, ETag, version)
  changes; check timestamps never count as change.
- A provider failure never deletes or tombstones data: items are reported "unavailable".
- An item missing from a *complete* listing is "removed_from_source"; its staging candidate is
  kept (history) and flagged in the report.
- Identity questions (codename already used by another brand, codename conflicts) are reported
  for review; nothing is renamed, moved or merged automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from afid.catalog import Store
from afid.config import Config
from afid.errors import AfidError, CapabilityError
from afid.models import codename_key
from afid.providers import registry
from afid.providers.base import DeviceCandidate, DiscoveryResult
from afid.utils import jsonio, log
from afid.utils.paths import sanitize_id
from afid.utils.timeutil import utc_now

LOG = log.get("updates")


@dataclass
class Change:
    change: str
    record_type: str
    record_id: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(vars(self))


@dataclass
class CheckOutcome:
    results: list[DiscoveryResult] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    provider_status: list[dict[str, Any]] = field(default_factory=list)
    written: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(p["status"] == "failed" for p in self.provider_status)

    def report(self) -> dict[str, Any]:
        summary: dict[str, int] = {}
        for c in self.changes:
            summary[c.change] = summary.get(c.change, 0) + 1
        return {
            "schema_version": "1.0",
            "kind": "update_check",
            "generated_at": utc_now(),
            "summary": dict(sorted(summary.items())),
            "changes": [c.as_dict() for c in self.changes],
            "provider_status": self.provider_status,
        }


def candidate_id(c: DeviceCandidate) -> str:
    return f"{c.brand_id}__{sanitize_id(c.item_id).lower()}"


COMMUNITY_REQUIREMENTS = [
    "codename confirmed by firmware evidence (ro.product.vendor.device / ro.product.device in "
    "build.prop, or OTA metadata pre-device) via `afid ingest --local`, or by an official source",
    "brand assignment confirmed (community brand inference is unverified)",
]


def candidate_record(
    c: DeviceCandidate, now: str, entry: dict[str, Any], snapshot: str | None
) -> dict[str, Any]:
    """Staging record for a community candidate: unverified, metadata only, licensed per source."""
    return {
        "schema_version": "1.0",
        "candidate_id": candidate_id(c),
        "brand_id": c.brand_id,
        "brand_inference": c.brand_inference,
        "codename": c.codename,
        "codename_key": codename_key(c.codename),
        "codename_status": "community_reported",
        "product_names": c.product_names,
        "model_numbers": c.model_numbers,
        "soc": c.soc,
        "release_date": c.release_date,
        "evidence": [c.evidence],
        "unresolved_reason": "community source only; needs firmware build.prop or official "
        "source to verify the codename",
        "discovered_at": now,
        "source": {
            "provider_id": entry["id"],
            "source_type": entry["source_type"],
            "url": c.url,
            "revision": c.revision,
            "snapshot": snapshot,
        },
        "license": dict(entry["data_license"]),
        "verification": {
            "status": "unverified",
            "outstanding_requirements": COMMUNITY_REQUIREMENTS,
        },
        "distribution_status": entry["distribution_default"],
        "firmware_payload_ingested": False,
    }


def select_providers(cfg: Config, provider: str | None, brand: str | None) -> list[dict[str, Any]]:
    out = []
    for e in registry.entries(cfg):
        if provider and e["id"] != provider:
            continue
        if brand and brand not in e["brand_ids"]:
            continue
        out.append(e)
    if provider and not out:
        raise AfidError(
            f"no provider '{provider}'" + (f" covering brand '{brand}'" if brand else "")
        )
    return out


def check(
    cfg: Config,
    provider: str | None = None,
    brand: str | None = None,
    write: bool = False,
    include_dumps: bool = True,
) -> CheckOutcome:
    """include_dumps=False skips firmware-item (dump) providers, whose listing is long-running
    and has its own workflow (discover-dumps.yml)."""
    store = Store(cfg.database)
    outcome = CheckOutcome()
    now = utc_now()
    devices = {(d["brand_id"], d["codename_key"]): d for d in store.devices()}
    codename_brands: dict[str, set[str]] = {}
    for b, k in devices:
        codename_brands.setdefault(k, set()).add(b)

    for entry in select_providers(cfg, provider, brand):
        prov = registry.build(cfg, entry)
        caps = prov.capabilities()
        if caps.discover_firmware and not caps.discover_devices:
            if not include_dumps:
                continue
            if brand:
                outcome.provider_status.append(
                    {
                        "provider_id": entry["id"],
                        "status": "unsupported",
                        "detail": "brand filter not applicable: a dump's brand is known only "
                        "after analysis",
                    }
                )
                continue
            _check_items(store, entry, prov, outcome, write, now)
            continue
        if not caps.discover_devices:
            outcome.provider_status.append(
                {
                    "provider_id": entry["id"],
                    "status": "unsupported",
                    "detail": entry["limitations"][:300],
                }
            )
            continue
        try:
            res = prov.discover_devices()
        except (CapabilityError, AfidError, OSError) as exc:
            outcome.provider_status.append(
                {"provider_id": entry["id"], "status": "failed", "detail": str(exc)[:300]}
            )
            outcome.changes.append(
                Change(
                    "unavailable",
                    "source",
                    entry["id"],
                    "provider check failed; existing data kept",
                )
            )
            continue
        if brand:
            res.candidates = [c for c in res.candidates if c.brand_id == brand]
        outcome.results.append(res)
        outcome.provider_status.append(
            {
                "provider_id": entry["id"],
                "status": res.status,
                "detail": f"{len(res.candidates)} candidates, {res.skipped} out of scope, "
                f"{len(res.errors)} errors; index revision {res.index_revision}",
            }
        )
        snap_path = store.source_path(entry["id"])
        old = jsonio.load(snap_path) if snap_path.exists() else {"items": []}
        old_items = {i["item_id"]: i for i in old["items"]}
        new_items = {c.item_id: c for c in res.candidates}

        for item_id, c in sorted(new_items.items()):
            prev = old_items.get(item_id)
            if prev is None:
                outcome.changes.append(
                    Change("added", "device_candidate", item_id, f"{c.brand_id}/{c.codename}")
                )
            elif prev["revision"] != c.revision:
                outcome.changes.append(
                    Change(
                        "changed",
                        "device_candidate",
                        item_id,
                        f"revision {prev['revision']} -> {c.revision}",
                    )
                )
            key = codename_key(c.codename)
            others = codename_brands.get(key, set()) - {c.brand_id}
            if others:
                outcome.changes.append(
                    Change(
                        "unverified",
                        "identity",
                        item_id,
                        f"codename '{c.codename}' already cataloged under {sorted(others)}; "
                        "possible rebrand or shared codename - review before linking",
                    )
                )
            dev = devices.get((c.brand_id, key))
            if dev and c.model_numbers and not set(c.model_numbers) <= set(dev["model_numbers"]):
                outcome.changes.append(
                    Change(
                        "unverified",
                        "identity",
                        dev["device_id"],
                        f"source lists model numbers not in the verified record: "
                        f"{sorted(set(c.model_numbers) - set(dev['model_numbers']))}",
                    )
                )
        # Only an unfiltered, successful listing can prove that an item disappeared.
        complete = res.status == "ok" and brand is None
        for item_id in sorted(set(old_items) - set(new_items) - {"_index"}):
            if brand and old_items[item_id].get("metadata", {}).get("brand_id") != brand:
                continue
            outcome.changes.append(
                Change(
                    "removed_from_source" if complete else "unavailable",
                    "device_candidate",
                    item_id,
                    "no longer listed by the source"
                    if complete
                    else "not seen in a partial/filtered run; existing data kept",
                )
            )

        if write:
            outcome.written += _write(store, entry, res, old_items, brand, now)
    return outcome


def _write(
    store: Store,
    entry: dict[str, Any],
    res: DiscoveryResult,
    old_items: dict[str, dict[str, Any]],
    brand: str | None,
    now: str,
) -> list[str]:
    provider_id = entry["id"]
    written = []
    for c in res.candidates:
        path = store.staging_path(provider_id, candidate_id(c))
        if store.device_path(c.brand_id or "", codename_key(c.codename)).exists():
            continue  # already verified; the verified record is authoritative
        if jsonio.write_if_changed(
            path,
            candidate_record(c, now, entry, res.index_revision),
            ("discovered_at", "retrieved_at"),
        ):
            written.append(str(path))
    # Keep items a filtered/partial run did not see, but never the old "_index" marker: it is
    # re-added once below, otherwise it would be duplicated and the file would flap between runs.
    items = {k: v for k, v in old_items.items() if k != "_index"}
    for c in res.candidates:
        items[c.item_id] = {
            "item_id": c.item_id,
            "kind": "device",
            "url": c.url,
            "revision": c.revision,
            "metadata": {"brand_id": c.brand_id, "codename": c.codename},
        }
    if res.status == "ok" and not brand:
        items = {k: v for k, v in items.items() if k in {c.item_id for c in res.candidates}}
    snapshot: dict[str, Any] = {
        "schema_version": "1.0",
        "provider_id": provider_id,
        "status": res.status,
        "checked_at": now,
        "items": [items[k] for k in sorted(items)],
        "errors": sorted(res.errors),
    }
    if index := res.index_revision:
        snapshot["items"].insert(
            0, {"item_id": "_index", "kind": "index", "url": None, "revision": index}
        )
    path = store.source_path(provider_id)
    if jsonio.write_if_changed(path, snapshot, ("checked_at",)):
        written.append(str(path))
    return written


def _check_items(
    store: Store,
    entry: dict[str, Any],
    prov: Any,
    outcome: CheckOutcome,
    write: bool,
    now: str,
) -> None:
    """Firmware-item sources (dump repositories): diff items by revision (commit SHA)."""
    snap_path = store.source_path(entry["id"])
    old = jsonio.load(snap_path) if snap_path.exists() else {"items": []}
    old_all = {i["item_id"]: i for i in old["items"] if i.get("kind") in ("firmware", "index")}
    old_items = {k: v for k, v in old_all.items() if v["kind"] == "firmware"}
    try:
        res = prov.discover_firmware(previous=old_all)
    except (CapabilityError, AfidError, OSError) as exc:
        outcome.provider_status.append(
            {"provider_id": entry["id"], "status": "failed", "detail": str(exc)[:300]}
        )
        outcome.changes.append(
            Change(
                "unavailable", "source", entry["id"], "provider check failed; existing data kept"
            )
        )
        return
    outcome.results.append(res)
    outcome.provider_status.append(
        {
            "provider_id": entry["id"],
            "status": res.status,
            "detail": f"{sum(i.kind == 'firmware' for i in res.items)} firmware items, "
            f"{res.skipped} skipped, "
            f"{len(res.errors)} errors; {res.stats}",
        }
    )
    new_all = {i.item_id: i for i in res.items}
    new_items = {k: v for k, v in new_all.items() if v.kind == "firmware"}
    for item_id, it in sorted(new_items.items()):
        prev = old_items.get(item_id)
        if prev is None:
            outcome.changes.append(Change("added", "firmware_item", item_id, it.revision))
        elif prev["revision"] != it.revision:
            outcome.changes.append(
                Change(
                    "changed",
                    "firmware_item",
                    item_id,
                    f"revision {prev['revision']} -> {it.revision}",
                )
            )
    complete = res.status == "ok"
    for item_id in sorted(set(old_items) - set(new_items)):
        outcome.changes.append(
            Change(
                "removed_from_source" if complete else "unavailable",
                "firmware_item",
                item_id,
                "no longer listed by the source; cataloged records are kept"
                if complete
                else "not seen in a partial run; existing data kept",
            )
        )
    if not write:
        return
    items = {} if complete else dict(old_all)
    items.update({k: v.as_snapshot() for k, v in new_all.items()})
    snapshot: dict[str, Any] = {
        "schema_version": "1.0",
        "provider_id": entry["id"],
        "status": res.status,
        "checked_at": now,
        "items": [items[k] for k in sorted(items)],
        "errors": sorted(res.errors),
    }
    if jsonio.write_if_changed(snap_path, snapshot, ("checked_at",)):
        outcome.written.append(str(snap_path))


def history(store: Store, device_id: str | None = None) -> list[dict[str, Any]]:
    """Compare consecutive firmware builds of each device (ordered by security patch, then
    build id): files added/removed, content changed, dependency edges added/removed."""
    by_dev: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
    for p in store.firmware_files():
        fw = jsonio.load(p)
        if device_id and fw["device_id"] != device_id:
            continue
        by_dev.setdefault(fw["device_id"], []).append((p, fw))
    reports = []
    for dev, builds in sorted(by_dev.items()):
        builds.sort(key=lambda x: (x[1]["security_patch"] or "", x[1]["build_id"]))
        for (pa, a), (pb, b) in zip(builds, builds[1:], strict=False):
            ca = {(c["partition"], c["path"]): c for c in store.components_of(pa)}
            cb = {(c["partition"], c["path"]): c for c in store.components_of(pb)}
            changes = []
            for k in sorted(cb.keys() - ca.keys()):
                changes.append(Change("added", "component", "/".join(k)))
            for k in sorted(ca.keys() - cb.keys()):
                changes.append(Change("removed_from_source", "component", "/".join(k)))
            for k in sorted(ca.keys() & cb.keys()):
                if ca[k]["sha256"] != cb[k]["sha256"]:
                    changes.append(
                        Change(
                            "checksum_changed",
                            "component",
                            "/".join(k),
                            f"{ca[k]['sha256']} -> {cb[k]['sha256']}",
                        )
                    )
                if ca[k]["distribution_status"] != cb[k]["distribution_status"]:
                    changes.append(Change("license_changed", "component", "/".join(k)))
            ea, eb = _edge_keys(store, a, ca), _edge_keys(store, b, cb)
            changes += [
                Change("dependency_added", "dependency", " -> ".join(e)) for e in sorted(eb - ea)
            ]
            changes += [
                Change("dependency_removed", "dependency", " -> ".join(e)) for e in sorted(ea - eb)
            ]
            reports.append(
                {
                    "device_id": dev,
                    "from": a["firmware_id"],
                    "to": b["firmware_id"],
                    "changes": [c.as_dict() for c in changes],
                }
            )
    return reports


def _edge_keys(
    store: Store, fw: dict[str, Any], comps: dict[tuple[str, str], dict[str, Any]]
) -> set[tuple[str, str, str]]:
    id_to_path = {c["component_id"]: f"{c['partition']}/{c['path']}" for c in comps.values()}
    keys: set[tuple[str, str, str]] = set()
    for p in store.dependency_files():
        doc = jsonio.load(p)
        if doc["firmware_id"] != fw["firmware_id"]:
            continue
        for e in doc["edges"]:
            keys.add((id_to_path.get(e["from"], e["from"]), e["type"], e["to_name"]))
    return keys
