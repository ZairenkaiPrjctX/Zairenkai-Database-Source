"""Human- and machine-readable catalog reports, built from generated statistics."""

from __future__ import annotations

from typing import Any

from afid.catalog import Store
from afid.catalog import index as catalog_index
from afid.catalog.validate import validate
from afid.config import Config
from afid.providers import registry


def build(cfg: Config) -> dict[str, Any]:
    store = Store(cfg.database)
    _, stats, _ = catalog_index.build(store, cfg.brand_ids)
    val = validate(cfg.database, cfg.schemas_dir, cfg.brand_ids)
    providers = [
        {
            "provider_id": e["id"],
            "status": e["status"],
            "brands": e["brand_ids"],
            "capabilities": sorted(k for k, v in e["capabilities"].items() if v),
            "last_verified": e["last_verified"],
        }
        for e in registry.entries(cfg)
    ]
    return {
        "schema_version": "1.0",
        "statistics": stats,
        "validation": {"errors": len(val.errors), "warnings": len(val.warnings)},
        "providers": providers,
        "stale_generated_files": catalog_index.check(store, cfg.brand_ids),
    }


def to_markdown(rep: dict[str, Any]) -> str:
    s = rep["statistics"]
    lines = [
        "# AFID catalog report",
        "",
        f"Database digest: `{s['database_digest']}`",
        "",
        "| Metric | Count |",
        "|---|---|",
    ]
    for key in (
        "brands",
        "devices",
        "firmware_builds",
        "components",
        "thermal_hal",
        "thermal_config",
        "power_hal",
        "power_config",
        "vendor_libraries",
        "init_related",
        "vintf",
        "unknown",
        "dependencies_resolved",
        "dependencies_inferred",
        "dependencies_unresolved",
        "pending_license_review",
        "staging_candidates",
    ):
        lines.append(f"| {key.replace('_', ' ')} | {s[key]} |")
    lines += [
        "",
        "## Coverage by brand",
        "",
        "| Brand | Devices | With firmware | Firmware builds | Components |",
        "|---|---|---|---|---|",
    ]
    for b, c in s["coverage_by_brand"].items():
        lines.append(
            f"| {b} | {c['devices']} | {c['devices_with_firmware']} | "
            f"{c['firmware_builds']} | {c['components']} |"
        )
    lines += [
        "",
        "## Providers",
        "",
        "| Provider | Status | Capabilities | Last verified |",
        "|---|---|---|---|",
    ]
    for p in rep["providers"]:
        lines.append(
            f"| {p['provider_id']} | {p['status']} | {', '.join(p['capabilities'])} "
            f"| {p['last_verified']} |"
        )
    v = rep["validation"]
    lines += [
        "",
        f"Validation: {v['errors']} error(s), {v['warnings']} warning(s).",
        f"Stale generated files: {', '.join(rep['stale_generated_files']) or 'none'}.",
        "",
    ]
    return "\n".join(lines)
