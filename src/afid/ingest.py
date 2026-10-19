"""Local firmware ingestion: the end-to-end vertical slice.

prepare (verify, detect, extract) -> identify device from firmware evidence -> scan ->
classify -> dependencies -> policy -> schema validation -> write catalog (or staging).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid import dependencies, models
from afid.catalog import Store
from afid.catalog.validate import load_validators
from afid.classification import Classifier
from afid.config import Config
from afid.errors import CapabilityError, ValidationError
from afid.extraction.pipeline import Pipeline, Prepared
from afid.licensing import Policy
from afid.parsers import buildprop
from afid.providers import registry
from afid.scanning import FileEntry, Scanner
from afid.utils import jsonio, log
from afid.utils.paths import sanitize_id
from afid.utils.timeutil import utc_now

LOG = log.get("ingest")
DEVICE_PROPS = (
    "ro.product.vendor.device",
    "ro.product.odm.device",
    "ro.product.device",
    "ro.product.product.device",
    "ro.product.system.device",
    "ro.build.product",
)
PROP_FILES = (
    "vendor/build.prop",
    "odm/build.prop",
    "odm/etc/build.prop",
    "product/build.prop",
    "system/build.prop",
    "system/system/build.prop",
    "build.prop",
)


@dataclass
class IngestResult:
    status: str  # cataloged | staged | dry_run
    device_id: str | None = None
    firmware_id: str | None = None
    written: list[str] = field(default_factory=list)
    component_count: int = 0
    edge_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(vars(self))


def _props(tree: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Merged props (earlier files win) and the file each key came from."""
    merged: dict[str, str] = {}
    origin: dict[str, str] = {}
    for rel in PROP_FILES:
        p = tree / rel
        if p.is_file() and not p.is_symlink():
            for k, v in buildprop.parse(p.read_text("utf-8", "replace")).items():
                if k not in merged:
                    merged[k], origin[k] = v, rel
    return merged, origin


def _fingerprint_build_id(fp: str | None) -> str | None:
    # brand/product/device:release/BUILD_ID/incremental:type/tags
    try:
        return fp.split(":", 1)[1].split("/")[1] if fp else None
    except IndexError:
        return None


def resolve_brand(
    cfg: Config, props: dict[str, str], explicit: str | None
) -> tuple[str | None, str]:
    if explicit:
        if explicit not in cfg.brand_ids:
            raise ValidationError(f"unknown brand '{explicit}' (known: {', '.join(cfg.brand_ids)})")
        return explicit, "given with --brand"
    raw = (
        buildprop.first(
            props,
            "ro.product.vendor.brand",
            "ro.product.brand",
            "ro.product.vendor.manufacturer",
            "ro.product.manufacturer",
        )
        or ""
    )
    model = buildprop.first(props, "ro.product.vendor.model", "ro.product.model") or ""
    low = raw.strip().lower()
    matches = [b for b in cfg.brands if low in {a.lower() for a in b["aliases"]}]
    for b in matches:  # prefer brands whose product-name prefix matches the model
        if any(model.lower().startswith(p.lower()) for p in b.get("product_name_prefixes") or []):
            return b["brand_id"], f"build.prop brand '{raw}' + model prefix of '{model}'"
    plain = [b for b in matches if not b.get("product_name_prefixes")]
    if len(plain) == 1:
        return plain[0]["brand_id"], f"build.prop brand '{raw}'"
    return None, f"build.prop brand '{raw}' / model '{model}' does not map to one AFID brand"


def ingest_local(
    cfg: Config,
    source: Path,
    provider_id: str = "local_firmware",
    brand: str | None = None,
    codename: str | None = None,
    expected_sha256: str | None = None,
    region: str | None = None,
    channel: str | None = None,
    dry_run: bool = False,
    keep_work: bool = False,
) -> IngestResult:
    provider = registry.get(cfg, provider_id)
    if not provider.capabilities().local_import:
        raise CapabilityError(f"provider '{provider_id}' does not support local import")
    if brand and provider.brand_ids and brand not in provider.brand_ids:
        raise ValidationError(f"provider '{provider_id}' does not cover brand '{brand}'")
    if brand is None and len(provider.brand_ids) == 1:
        brand = provider.brand_ids[0]

    pipe = Pipeline(
        cfg.cache,
        cfg.settings["scan"]["partitions"],
        cfg.limit("max_archive_bytes"),
        cfg.limit("max_extracted_bytes"),
        cfg.limit("max_member_count"),
    )
    prepared = pipe.prepare(source, expected_sha256)
    try:
        return _catalog(
            cfg,
            provider_id,
            prepared,
            brand,
            codename,
            expected_sha256,
            region,
            channel,
            dry_run,
            provider.filename_hints(source.name),
        )
    finally:
        if prepared.workdir and not keep_work:
            shutil.rmtree(prepared.workdir, ignore_errors=True)


@dataclass
class SourceContext:
    """Where a firmware tree came from. Defaults describe a user-supplied local import;
    remote dump analysis passes its own (see afid.remote)."""

    source_type: str = "user_supplied_local_firmware"
    evidence_type: str = "firmware_build_prop"
    distribution_status: str = "user_supplied"
    user_supplied: bool = True
    source_url: str | None = None
    source_ref: dict[str, Any] | None = None
    extra_inventory: list[FileEntry] = field(default_factory=list)
    store: Store | None = None
    evidence_url: str | None = None


def _catalog(
    cfg: Config,
    provider_id: str,
    prepared: Prepared,
    brand: str | None,
    codename: str | None,
    expected_sha: str | None,
    region: str | None,
    channel: str | None,
    dry_run: bool,
    hints: dict[str, str],
    ctx: SourceContext | None = None,
) -> IngestResult:
    ctx = ctx or SourceContext()
    now = utc_now()
    store = ctx.store or Store(cfg.database)
    result = IngestResult(
        status="dry_run" if dry_run else "cataloged", warnings=list(prepared.warnings)
    )
    if hints:
        result.warnings.append(f"file-name hints (not used as evidence): {hints}")
    props, origin = _props(prepared.tree)
    official = bool(expected_sha and prepared.archive_sha256)

    # ---- identity from firmware evidence --------------------------------------------------
    evidence: list[models.Evidence] = []
    fw_codename = None
    for key in DEVICE_PROPS:
        if props.get(key) and props[key] not in ("generic", "mainline"):
            fw_codename = props[key]
            evidence.append(
                {
                    "evidence_type": ctx.evidence_type,
                    "source": provider_id,
                    "url": ctx.evidence_url,
                    "retrieved_at": now,
                    "detail": f"{key}={fw_codename} in {origin[key]}"
                    + (
                        f" (archive sha256 {prepared.archive_sha256})"
                        if prepared.archive_sha256
                        else ""
                    ),
                    "confidence": 0.95,
                }
            )
            break
    ota_dev = prepared.ota_metadata.get("pre-device")
    if ota_dev:
        evidence.append(
            {
                "evidence_type": "official_ota_metadata" if official else "firmware_build_prop",
                "source": provider_id,
                "url": None,
                "retrieved_at": now,
                "detail": f"META-INF/com/android/metadata pre-device={ota_dev}"
                + (" (archive matched supplied official SHA-256)" if official else ""),
                "confidence": 0.9,
            }
        )
        if fw_codename and ota_dev != fw_codename:
            result.warnings.append(f"OTA pre-device '{ota_dev}' != build.prop '{fw_codename}'")
        fw_codename = fw_codename or ota_dev
    if codename and fw_codename and codename != fw_codename:
        raise ValidationError(
            f"--codename '{codename}' contradicts firmware evidence "
            f"'{fw_codename}'; refusing to catalog"
        )

    brand_id, brand_basis = resolve_brand(cfg, props, brand)
    build_id = buildprop.first(props, "ro.build.id", "ro.vendor.build.id") or _fingerprint_build_id(
        prepared.ota_metadata.get("post-build")
    )
    unresolved = []
    if not fw_codename:
        unresolved.append("no device codename in build.prop or OTA metadata")
    elif not models.valid_codename(fw_codename):
        unresolved.append(f"firmware codename {fw_codename!r} is not a usable identifier")
    if brand_id is None:
        unresolved.append(brand_basis)
    if not build_id:
        unresolved.append("no build id (ro.build.id / OTA post-build)")
    if unresolved:
        return _stage(
            cfg,
            store,
            provider_id,
            prepared,
            brand_id,
            brand_basis,
            fw_codename or codename,
            props,
            now,
            unresolved,
            result,
            dry_run,
            ctx,
        )
    assert fw_codename and brand_id and build_id

    # ---- device ----------------------------------------------------------------------------
    device = models.new_device(brand_id, fw_codename, evidence)
    model = buildprop.first(props, "ro.product.vendor.model", "ro.product.model")
    if model:
        device["model_numbers"] = [model]
    release = buildprop.first(
        props, "ro.build.version.release_or_codename", "ro.build.version.release"
    )
    if release:
        device["android_versions"] = [release]
    device["soc"] = {
        "vendor": buildprop.first(props, "ro.soc.manufacturer"),
        "platform": buildprop.first(props, "ro.soc.model", "ro.board.platform"),
        "architecture": buildprop.first(props, "ro.product.cpu.abi"),
    }
    device["discovered_at"] = device["last_verified_at"] = now
    promoted = _absorb_staging(store, device)
    dev_id = device["device_id"]

    # ---- firmware --------------------------------------------------------------------------
    incremental = buildprop.first(
        props, "ro.build.version.incremental", "ro.vendor.build.version.incremental"
    )
    fw = models.new_firmware(
        dev_id, build_id, provider_id, ctx.source_type, region, channel, incremental
    )
    fw_id = fw["firmware_id"]
    sdk = buildprop.first(props, "ro.build.version.sdk")
    fw.update(
        {
            "firmware_version": buildprop.first(
                props, "ro.build.version.incremental", "ro.build.display.id"
            ),
            "android_release": release,
            "api_level": int(sdk) if sdk and sdk.isdigit() else None,
            "security_patch": buildprop.first(props, "ro.build.version.security_patch"),
            "vendor_security_patch": buildprop.first(props, "ro.vendor.build.security_patch"),
            # Android 10+ may omit ro.build.fingerprint (derived at runtime); fall back to the
            # per-partition fingerprints, vendor first.
            "build_fingerprint": buildprop.first(
                props,
                "ro.vendor.build.fingerprint",
                "ro.build.fingerprint",
                "ro.odm.build.fingerprint",
                "ro.system.build.fingerprint",
                "ro.product.build.fingerprint",
            )
            or prepared.ota_metadata.get("post-build"),
            "partitions": [p.as_dict() for p in prepared.partitions],
            "distribution_status": ctx.distribution_status,
            "last_checked_at": now,
            "last_updated_at": now,
        }
    )
    fw["source_refs"] = [
        ctx.source_ref
        or {
            "provider_id": provider_id,
            "item_id": f"local:{prepared.archive_sha256 or prepared.tree.name}",
            "url": None,
            "revision": prepared.archive_sha256,
            "content_marker": prepared.archive_sha256,
            "retrieved_at": now,
        }
    ]
    fw["source"].update(
        {
            "url": ctx.source_url,
            "archive_name": prepared.archive_name,
            "archive_sha256": prepared.archive_sha256,
            "archive_size": prepared.archive_size,
            "official_checksum": (
                {"algorithm": "sha256", "value": expected_sha.lower(), "matched": True}
                if official and expected_sha
                else None
            ),
        }
    )
    fw["ingestion"].update({"status": "validated", "tools": prepared.tools, "ingested_at": now})
    if fw["kernel_version"] is None:
        fw["warnings"].append("kernel version not identified (boot image parsing not implemented)")
    if not fw["partitions"]:
        fw["warnings"].append("no partition layout recorded")

    # ---- scan, classify, dependencies --------------------------------------------------------
    policy = Policy.from_config(cfg.policy, cfg.allowlist)
    scanner = Scanner(
        Classifier(cfg.rules),
        policy,
        cfg.settings["scan"]["partitions"],
        cfg.limit("max_file_hash_bytes"),
    )
    scan = scanner.scan(prepared.tree, fw_id, provider_id, user_supplied=ctx.user_supplied)
    # Files known to exist but not present locally (remote trees) still resolve dependencies.
    known = {e.full for e in scan.inventory}
    scan.inventory.extend(e for e in ctx.extra_inventory if e.full not in known)
    edges = dependencies.build(prepared.tree, scan, scanner, fw_id, provider_id, ctx.user_supplied)
    container = prepared.archive_name
    for c in scan.components:
        c["provenance"]["container"] = container
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in scan.components:
        groups.setdefault(models.CATEGORY_GROUP[c["category"]], []).append(c)
    fw["component_groups"] = sorted(groups)
    fw["component_count"] = len(scan.components)
    fw["warnings"].extend(scan.warnings[:200])
    fw["validation_status"] = "valid"
    result.warnings.extend(scan.warnings[:50])

    # ---- schema validation before writing ----------------------------------------------------
    v = load_validators(cfg.schemas_dir)
    problems = [f"device: {e.message}" for e in v["device"].iter_errors(device)]
    problems += [f"firmware: {e.message}" for e in v["firmware"].iter_errors(fw)]
    for g, comps in groups.items():
        doc = {"schema_version": "1.0", "firmware_id": fw_id, "group": g, "components": comps}
        problems += [f"{g}: {e.message}" for e in v["component"].iter_errors(doc)]
    dep_doc = {"schema_version": "1.0", "firmware_id": fw_id, "edges": edges}
    problems += [f"dependencies: {e.message}" for e in v["dependency"].iter_errors(dep_doc)]
    if problems:
        raise ValidationError(
            "generated records failed schema validation: " + "; ".join(problems[:10])
        )

    result.device_id, result.firmware_id = dev_id, fw_id
    result.component_count = len(scan.components)
    for e in edges:
        result.edge_counts[e["status"]] = result.edge_counts.get(e["status"], 0) + 1
    if dry_run:
        return result
    key = device["codename_key"]
    fw_key = models.firmware_key(build_id, region, channel, incremental)
    if store.save_device(device):
        result.written.append(str(store.device_path(brand_id, key)))
    result.written += [
        str(p) for p in store.save_firmware(brand_id, key, fw_key, fw, groups, edges)
    ]
    for p in promoted:
        p.unlink()
        result.written.append(f"{p} (promoted to {dev_id}; removed from staging)")
    return result


def _absorb_staging(store: Store, device: dict[str, Any]) -> list[Path]:
    """Merge community candidates for the same brand+codename into the verified device."""
    used = []
    for p in store.staging_files():
        cand = jsonio.load(p)
        if cand["brand_id"] != device["brand_id"] or cand["codename_key"] != device["codename_key"]:
            continue
        device["product_names"] = sorted(set(device["product_names"]) | set(cand["product_names"]))
        device["model_numbers"] = sorted(set(device["model_numbers"]) | set(cand["model_numbers"]))
        for k, val in (cand.get("soc") or {}).items():
            if val and not device["soc"].get(k):
                device["soc"][k] = val
        device["sources"].extend(e for e in cand["evidence"] if e not in device["sources"])
        used.append(p)
    return used


def _stage(
    cfg: Config,
    store: Store,
    provider_id: str,
    prepared: Prepared,
    brand_id: str | None,
    brand_basis: str,
    codename: str | None,
    props: dict[str, str],
    now: str,
    reasons: list[str],
    result: IngestResult,
    dry_run: bool,
    ctx: SourceContext | None = None,
    codename_status: str = "unresolved",
) -> IngestResult:
    ctx = ctx or SourceContext()
    cfg_entry = next(e for e in registry.entries(cfg) if e["id"] == provider_id)
    result.status = "staged" if not dry_run else "dry_run"
    result.detail = "; ".join(reasons)
    claimed = codename or "unknown"
    key = sanitize_id(claimed).lower() if claimed else "unknown"
    if not models.valid_codename(key):
        key = "unknown"
    marker = (ctx.source_ref or {}).get("revision") or prepared.archive_sha256 or "dir"
    cand_id = f"{brand_id or 'unbranded'}__{key}__{sanitize_id(marker)[:12]}"
    cand = {
        "schema_version": "1.0",
        "candidate_id": cand_id,
        "brand_id": brand_id,
        "brand_inference": brand_basis,
        "codename": claimed,
        "codename_key": key,
        "codename_status": codename_status,
        "product_names": [],
        "model_numbers": [
            m for m in [buildprop.first(props, "ro.product.vendor.model", "ro.product.model")] if m
        ],
        "soc": {
            "vendor": None,
            "platform": buildprop.first(props, "ro.board.platform"),
            "architecture": None,
        },
        "release_date": None,
        "evidence": [
            {
                "evidence_type": "user_statement" if codename and not props else ctx.evidence_type,
                "source": provider_id,
                "url": None,
                "retrieved_at": now,
                "detail": f"local import of {prepared.archive_name or prepared.tree.name}; "
                + "; ".join(reasons),
                "confidence": 0.2,
            }
        ],
        "unresolved_reason": "; ".join(reasons),
        "discovered_at": now,
        "source": {
            "provider_id": provider_id,
            "source_type": ctx.source_type,
            "url": ctx.source_url,
            "revision": (ctx.source_ref or {}).get("revision") or prepared.archive_sha256,
            "snapshot": None,
        },
        "license": dict(cfg_entry["data_license"]),
        "verification": {"status": "unverified", "outstanding_requirements": list(reasons)},
        "distribution_status": ctx.distribution_status,
        "firmware_payload_ingested": False,
    }
    errs = [e.message for e in load_validators(cfg.schemas_dir)["candidate"].iter_errors(cand)]
    # (the firmware itself stays in the local cache; only this metadata record is written)
    if errs:
        raise ValidationError(f"staging candidate invalid: {errs[:3]}")
    if not dry_run:
        path = store.staging_path(provider_id, cand_id)
        if jsonio.write_if_changed(path, cand, ("discovered_at", "retrieved_at")):
            result.written.append(str(path))
    return result
