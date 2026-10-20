"""registry/sources.json: loading, schema validation and the rules a schema cannot express.

Rules (all reported by `registry_problems`, enforced by `load_registry`):
- provider ids are unique; base and API URLs pass the URL policy against the provider's own
  allowlist; allowlist entries are plain hostnames;
- a provider may be enabled only with an approved review naming a reviewer and a date, a
  recorded rate-limit and robots check, and a real discovery strategy (never a tool);
- an approved review names its reviewer and date;
- the provider agrees with its entry in config/provider_registry.yml (hosts, API base, group),
  so the two registries cannot drift apart.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry as SchemaRegistry
from referencing import Resource

from afid.config import load_yaml
from afid.errors import ConfigError
from afid.pipeline.urlpolicy import UrlPolicyError, check_url, valid_hostname

REGISTRY_PATH = "registry/sources.json"
FIXTURE_PATH = "registry/fixtures/synthetic-dry-run.json"
SCHEMAS = ("source-registry", "firmware-record", "run-manifest")
SCHEMA_BASE = "https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source/schemas/"
# Synthetic fixture hosts must be under this reserved TLD (RFC 2606): they can never resolve.
SYNTHETIC_TLD = ".invalid"


def load_schemas(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in SCHEMAS:
        path = root / "schemas" / f"{name}.schema.json"
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read schema {path.name}: {exc}") from None
        Draft202012Validator.check_schema(schema)
        out[name] = schema
    return out


def validators(root: Path) -> dict[str, Draft202012Validator]:
    """Validators for the pipeline schemas, with cross-file $refs and format checks."""
    schemas = load_schemas(root)
    store: SchemaRegistry[Any] = SchemaRegistry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas.values()
    )
    checker = FormatChecker()
    out = {
        name: Draft202012Validator(schema, registry=store, format_checker=checker)
        for name, schema in schemas.items()
    }
    out["provider"] = Draft202012Validator(
        {"$ref": f"{SCHEMA_BASE}source-registry.schema.json#/$defs/provider"},
        registry=store,
        format_checker=checker,
    )
    return out


def schema_errors(v: Draft202012Validator, doc: Any, limit: int = 10) -> list[str]:
    errors = sorted(v.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])
    out = []
    for e in errors[:limit]:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{where}: {e.message[:300]}")
    if len(errors) > limit:
        out.append(f"... and {len(errors) - limit} more schema errors")
    return out


@dataclass(frozen=True)
class Limits:
    request_timeout_seconds: float
    min_interval_seconds: float
    max_retries: int
    backoff_seconds: float
    max_pages: int
    max_records: int
    max_requests: int
    max_response_bytes: int
    max_run_seconds: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Limits:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class Provider:
    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.raw["id"])

    @property
    def enabled(self) -> bool:
        return bool(self.raw["enabled"])

    @property
    def provider_type(self) -> str:
        return str(self.raw["provider_type"])

    @property
    def strategy(self) -> str:
        return str(self.raw["discovery"]["strategy"])

    @property
    def discovery(self) -> dict[str, Any]:
        return dict(self.raw["discovery"])

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset(self.raw["allowed_hosts"])

    @property
    def limits(self) -> Limits:
        return Limits.from_dict(self.raw["limits"])

    @property
    def license_notes(self) -> str:
        return str(self.raw["license_notes"])


@dataclass(frozen=True)
class SourceRegistry:
    path: Path
    sha256: str
    version: int
    providers: dict[str, Provider]


def provider_problems(p: dict[str, Any], afid_entries: dict[str, dict[str, Any]]) -> list[str]:
    pid = p.get("id", "?")
    out: list[str] = []
    hosts = p.get("allowed_hosts", [])
    out += [
        f"{pid}: allowed host '{h}' is not a plain DNS name" for h in hosts if not valid_hostname(h)
    ]
    disc = p.get("discovery", {})
    for key, url in (("base_url", p.get("base_url")), ("api_base", disc.get("api_base"))):
        if url is None:
            continue
        try:
            check_url(url, hosts)
        except UrlPolicyError as exc:
            out.append(f"{pid}: {key} {exc}")
    review = p.get("review", {})
    if review.get("status") == "approved" and not (
        review.get("reviewed_by") and review.get("reviewed_on")
    ):
        out.append(f"{pid}: an approved review must name reviewed_by and reviewed_on")
    if p.get("provider_type") == "tool" and disc.get("strategy") != "none":
        out.append(f"{pid}: a tool is not a metadata source; its strategy must be 'none'")
    if p.get("enabled"):
        if review.get("status") != "approved":
            out.append(
                f"{pid}: enabled without an approved review (status '{review.get('status')}')"
            )
        if disc.get("strategy") in ("none", None) or p.get("provider_type") == "tool":
            out.append(f"{pid}: enabled, but it has no discovery strategy")
        if not (p.get("rate_limit_policy") or {}).get("checked_on"):
            out.append(f"{pid}: enabled without a recorded rate-limit check")
        if not (p.get("robots") or {}).get("checked_on"):
            out.append(f"{pid}: enabled without a recorded robots check")
    if p.get("provider_type") == "synthetic_fixture":
        out += [
            f"{pid}: synthetic host '{h}' must end with {SYNTHETIC_TLD}"
            for h in hosts
            if not h.endswith(SYNTHETIC_TLD)
        ]
        return out
    ref = p.get("afid_provider")
    if ref is None:
        return out
    entry = afid_entries.get(ref)
    if entry is None:
        return [*out, f"{pid}: afid_provider '{ref}' is not in config/provider_registry.yml"]
    if p.get("provider_type") != "tool":
        extra = sorted(set(hosts) - set(entry.get("allowed_hosts") or []))
        if extra:
            out.append(
                f"{pid}: hosts {extra} are not allowed for '{ref}' in config/provider_registry.yml"
            )
    if disc.get("strategy") == "gitlab_group_branches":
        settings = entry.get("settings") or {}
        for key in ("api_base", "group", "group_path"):
            if disc.get(key) != settings.get(key):
                out.append(
                    f"{pid}: discovery.{key} {disc.get(key)!r} differs from "
                    f"config/provider_registry.yml ({settings.get(key)!r})"
                )
    return out


def _afid_entries(root: Path) -> dict[str, dict[str, Any]]:
    doc = load_yaml(root / "config" / "provider_registry.yml")
    return {e["id"]: e for e in (doc or {}).get("providers") or []}


def registry_problems(root: Path, doc: Any) -> list[str]:
    v = validators(root)
    problems = schema_errors(v["source-registry"], doc)
    if problems:
        return problems
    entries = _afid_entries(root)
    seen: set[str] = set()
    for p in doc["providers"]:
        if p["id"] in seen:
            problems.append(f"duplicate provider id '{p['id']}'")
        seen.add(p["id"])
        if p["provider_type"] == "synthetic_fixture":
            problems.append(
                f"{p['id']}: synthetic fixtures belong in {FIXTURE_PATH}, not the registry"
            )
        problems += provider_problems(p, entries)
    return problems


def read_json(path: Path) -> tuple[Any, bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        return json.loads(data), data
    except ValueError as exc:
        raise ConfigError(f"{path.name}: invalid JSON ({exc})") from None


def load_registry(root: Path) -> SourceRegistry:
    path = root / REGISTRY_PATH
    doc, data = read_json(path)
    problems = registry_problems(root, doc)
    if problems:
        raise ConfigError(f"{REGISTRY_PATH} is invalid: " + "; ".join(problems[:10]))
    return SourceRegistry(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        version=int(doc["registry_version"]),
        providers={p["id"]: Provider(p) for p in doc["providers"]},
    )


def fixture_problems(root: Path, doc: Any) -> list[str]:
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        return [f"{FIXTURE_PATH}: expected an object with 'provider' and 'items'"]
    problems = schema_errors(validators(root)["provider"], doc.get("provider"))
    if problems:
        return [f"{FIXTURE_PATH} provider: {p}" for p in problems]
    p = doc["provider"]
    if (
        p["provider_type"] != "synthetic_fixture"
        or p["discovery"]["strategy"] != "synthetic_fixture"
    ):
        problems.append(f"{FIXTURE_PATH}: provider must be a synthetic_fixture")
    return problems + provider_problems(p, {})


def load_fixture(root: Path) -> tuple[Provider, list[dict[str, Any]]]:
    doc, _ = read_json(root / FIXTURE_PATH)
    problems = fixture_problems(root, doc)
    if problems:
        raise ConfigError("; ".join(problems[:10]))
    return Provider(doc["provider"]), list(doc["items"])
