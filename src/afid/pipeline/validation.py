"""Checks behind tools/validate.py: pipeline schemas, registry, fixture and run manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from afid.errors import ConfigError
from afid.pipeline.records import record_problems
from afid.pipeline.registry import (
    FIXTURE_PATH,
    REGISTRY_PATH,
    SCHEMAS,
    Provider,
    fixture_problems,
    read_json,
    registry_problems,
    schema_errors,
    validators,
)

MAX_MANIFEST_BYTES = 1024 * 1024


def schema_problems(root: Path) -> list[str]:
    out = []
    for name in SCHEMAS:
        path = root / "schemas" / f"{name}.schema.json"
        try:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, SchemaError) as exc:
            out.append(f"{path.name}: {str(exc).splitlines()[0][:300]}")
    return out


def config_problems(root: Path) -> list[str]:
    """Schemas, registry and synthetic fixture (what `tools/validate.py all` checks)."""
    problems = schema_problems(root)
    if problems:
        return problems
    for rel, check in ((REGISTRY_PATH, registry_problems), (FIXTURE_PATH, fixture_problems)):
        try:
            doc, _ = read_json(root / rel)
        except ConfigError as exc:
            problems.append(str(exc))
            continue
        problems += [p if p.startswith(rel) else f"{rel}: {p}" for p in check(root, doc)]
    return problems


def providers_for_manifests(root: Path) -> dict[str, Provider]:
    doc, _ = read_json(root / REGISTRY_PATH)
    providers = {p["id"]: Provider(p) for p in doc.get("providers", [])}
    fixture, _ = read_json(root / FIXTURE_PATH)
    providers[fixture["provider"]["id"]] = Provider(fixture["provider"])
    return providers


def manifest_problems(root: Path, path: Path) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return [f"{path}: {exc.strerror or exc}"]
    if size > MAX_MANIFEST_BYTES:
        return [f"{path.name}: {size} bytes exceeds the {MAX_MANIFEST_BYTES}-byte manifest limit"]
    try:
        doc, _ = read_json(path)
    except ConfigError as exc:
        return [str(exc)]
    v = validators(root)
    problems = schema_errors(v["run-manifest"], doc)
    if problems:
        return problems
    providers = providers_for_manifests(root)
    ids: list[str] = []
    for rec in doc["records"]:
        ids.append(rec["record_id"])
        problems += [
            f"{rec['record_id']}: {p}"
            for p in record_problems(rec, providers.get(rec["source_id"]), v["firmware-record"])
        ]
    if len(ids) != len(set(ids)):
        problems.append("duplicate record_id values in records")
    if ids != sorted(ids):
        problems.append("records are not sorted by record_id (output must be deterministic)")
    s = doc["summary"]
    if s["validated"] != len(ids):
        problems.append(f"summary.validated {s['validated']} != {len(ids)} records")
    if s["discovered"] != s["validated"] + s["duplicate"] + s["failed"]:
        problems.append("summary: discovered != validated + duplicate + failed")
    if s["failed"] < len(doc["rejected"]):
        problems.append("summary.failed is smaller than the number of rejected entries")
    return problems


def summarize(doc: dict[str, Any]) -> dict[str, Any]:
    """A short, secret-free view of a manifest for build logs (no records)."""
    return {
        "status": doc.get("status"),
        "mode": doc.get("mode"),
        "generated_at": doc.get("generated_at"),
        "summary": doc.get("summary"),
        "sources": [
            {k: s.get(k) for k in ("source_id", "status", "requests", "truncated")}
            for s in doc.get("sources", [])
        ],
        "rejected": len(doc.get("rejected", [])),
        "binary_downloads": doc.get("binary_downloads"),
    }
