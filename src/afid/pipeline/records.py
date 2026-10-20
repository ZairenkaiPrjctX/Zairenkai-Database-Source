"""Canonical firmware records (schemas/firmware-record.schema.json).

A record is built from a source item: the source's own stable identifier, its revision, its
URL and the field values the source gave or that a documented rule inferred. Every data
field gets a provenance entry; a field without a value is null with origin "unknown". The
record id is a hash of (source_id, source_item_id) and never depends on the run time.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from afid.errors import ValidationError
from afid.hashing import sha256_file, stable_id
from afid.pipeline.registry import Provider, schema_errors
from afid.pipeline.urlpolicy import UrlPolicyError, check_url

SCHEMA_VERSION = "1.0"
DATA_FIELDS = (
    "manufacturer",
    "device_name",
    "device_codename",
    "soc",
    "android_version",
    "build_id",
    "firmware_version",
    "region",
    "release_date",
    "file_name",
    "file_size_bytes",
    "sha256",
    "download_url",
)
ORIGINS = ("source", "inferred", "computed")
UNKNOWN = {"origin": "unknown", "method": "not provided by the source", "source_field": None}
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Android build description, as used for dump branch names (verified on 2026-10-19 snapshots):
# <product>-<build type>-<release>-<build id>-<incremental>-<signing tags>
BUILD_DESCRIPTION = re.compile(
    r"^(?P<product>[A-Za-z0-9_.]+)-(?P<type>user|userdebug|eng)-"
    r"(?P<release>[0-9]{1,2}(?:\.[0-9]{1,2}){0,2})-(?P<build_id>[A-Za-z0-9][A-Za-z0-9._]{0,63})-"
    r"(?P<incremental>[A-Za-z0-9][A-Za-z0-9._-]{0,127}?)-(?P<tags>release-keys|test-keys|dev-keys)$"
)
CODENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Value:
    value: str | int
    origin: str  # source | inferred | computed
    method: str
    source_field: str | None = None


@dataclass
class Item:
    """One firmware item from a source, before it becomes a record."""

    source_item_id: str
    revision: str | None
    source_url: str
    fields: dict[str, Value] = field(default_factory=dict)


def record_id(source_id: str, source_item_id: str) -> str:
    return stable_id("fwr", "firmware-record/1", source_id, source_item_id, length=32)


def parse_build_description(text: str) -> dict[str, str] | None:
    m = BUILD_DESCRIPTION.match(text)
    return m.groupdict() if m else None


def dump_branch_item(project_path: str, branch: str, commit: str, web_url: str) -> Item:
    """Item for one branch of a DumprX-style dump repository.

    Namespace and project names are hints (recorded as inferred), and so are the version
    fields parsed from the branch name. Nothing here comes from the dump's build.prop.
    """
    namespace, _, project = project_path.rpartition("/")
    fields: dict[str, Value] = {}
    if namespace:
        fields["manufacturer"] = Value(
            namespace.split("/")[-1],
            "inferred",
            "GitLab project namespace (a naming convention, not identity evidence)",
            "path_with_namespace",
        )
    if CODENAME.match(project):
        fields["device_codename"] = Value(
            project,
            "inferred",
            "GitLab project name (a naming convention, not identity evidence)",
            "path_with_namespace",
        )
    parsed = parse_build_description(branch)
    if parsed:
        method = "parsed from the branch name as an Android build description"
        fields["android_version"] = Value(parsed["release"], "inferred", method, "branch.name")
        fields["build_id"] = Value(parsed["build_id"], "inferred", method, "branch.name")
        fields["firmware_version"] = Value(parsed["incremental"], "inferred", method, "branch.name")
    return Item(
        source_item_id=f"{project_path}@{branch}",
        revision=commit,
        source_url=f"{web_url.rstrip('/')}/-/tree/{commit}",
        fields=fields,
    )


def build_record(provider: Provider, item: Item, discovered_at: str) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id(provider.id, item.source_item_id),
        "source_id": provider.id,
        "source_item_id": item.source_item_id,
        "source_revision": item.revision,
        "source_url": item.source_url,
        "discovered_at": discovered_at,
        "license": {"status": "unknown", "spdx": None, "notes": provider.license_notes[:2000]},
        "validation_status": "unverified",
    }
    provenance: dict[str, Any] = {}
    for name in DATA_FIELDS:
        v = item.fields.get(name)
        rec[name] = None if v is None else v.value
        provenance[name] = (
            dict(UNKNOWN)
            if v is None
            else {"origin": v.origin, "method": v.method, "source_field": v.source_field}
        )
    rec["provenance"] = provenance
    return rec


def record_problems(
    rec: Any, provider: Provider | None, validator: Draft202012Validator
) -> list[str]:
    """Everything wrong with one record: schema, URL policy, id, provenance, dates."""
    problems = schema_errors(validator, rec)
    if problems:
        return problems
    if provider is None:
        return [f"unknown source_id '{rec['source_id']}'"]
    if rec["source_id"] != provider.id:
        problems.append(f"source_id '{rec['source_id']}' does not match provider '{provider.id}'")
    for key in ("source_url", "download_url"):
        if rec[key] is not None:
            try:
                check_url(rec[key], provider.allowed_hosts)
            except UrlPolicyError as exc:
                problems.append(f"{key}: {exc}")
    expected = record_id(rec["source_id"], rec["source_item_id"])
    if rec["record_id"] != expected:
        problems.append(f"record_id {rec['record_id']} is not the deterministic id {expected}")
    for name in DATA_FIELDS:
        origin = rec["provenance"][name]["origin"]
        if (rec[name] is None) != (origin == "unknown"):
            problems.append(f"{name}: provenance origin '{origin}' does not match its value")
        if origin == "computed" and name not in ("sha256", "file_size_bytes"):
            problems.append(f"{name}: only checksums and sizes can be computed by AFID")
    verified = rec["validation_status"] == "checksum_verified"
    if verified != (rec["provenance"]["sha256"]["origin"] == "computed"):
        problems.append(
            "validation_status 'checksum_verified' requires, and is required by, a computed sha256"
        )
    try:
        datetime.strptime(rec["discovered_at"], TIMESTAMP_FORMAT)
    except ValueError:
        problems.append(f"discovered_at '{rec['discovered_at']}' is not a valid UTC timestamp")
    return problems


def verify_file(rec: dict[str, Any], path: Path) -> dict[str, Any]:
    """Compare a local file with the record's checksum (and size, if known).

    Returns a copy marked checksum_verified on a match; raises ValidationError otherwise.
    The file is only read and hashed, never executed or extracted.
    """
    if rec.get("sha256") is None:
        raise ValidationError(f"{rec['record_id']}: the source gave no SHA-256 to compare with")
    if not path.is_file():
        raise ValidationError(f"{path}: not a regular file")
    size = path.stat().st_size
    if rec.get("file_size_bytes") is not None and rec["file_size_bytes"] != size:
        raise ValidationError(
            f"{path.name}: size {size} differs from the recorded {rec['file_size_bytes']} bytes"
        )
    digest = sha256_file(path)
    if digest != rec["sha256"]:
        raise ValidationError(f"{path.name}: SHA-256 {digest} does not match {rec['sha256']}")
    out = copy.deepcopy(rec)
    out["validation_status"] = "checksum_verified"
    out["provenance"]["sha256"] = {
        "origin": "computed",
        "method": "SHA-256 of a local file matched the source's value",
        "source_field": rec["provenance"]["sha256"].get("source_field"),
    }
    return out
