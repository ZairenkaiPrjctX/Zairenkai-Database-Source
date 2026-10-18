"""Provider registry loaded from config/provider_registry.yml."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from afid.config import Config
from afid.download import HttpClient
from afid.errors import ConfigError, NotFoundError
from afid.providers.base import FirmwareProvider

STATUSES = {"active", "metadata_only", "manual_import_required", "unsupported"}
REQUIRED = (
    "id",
    "class",
    "brand_ids",
    "status",
    "source_type",
    "source_urls",
    "allowed_hosts",
    "capabilities",
    "auth",
    "distribution_default",
    "last_verified",
    "limitations",
)


def _load_class(path: str) -> type[FirmwareProvider]:
    module, _, name = path.rpartition(".")
    if not module.startswith("afid.providers."):
        raise ConfigError(f"provider class {path} must live in afid.providers")
    cls = getattr(importlib.import_module(module), name, None)
    if not (isinstance(cls, type) and issubclass(cls, FirmwareProvider)):
        raise ConfigError(f"{path} is not a FirmwareProvider")
    return cls


def entries(cfg: Config) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for e in cfg.providers:
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            raise ConfigError(f"provider {e.get('id')}: missing {missing}")
        if e["status"] not in STATUSES:
            raise ConfigError(f"provider {e['id']}: unknown status {e['status']}")
        unknown = set(e["brand_ids"]) - set(cfg.brand_ids)
        if unknown:
            raise ConfigError(f"provider {e['id']}: unknown brand ids {sorted(unknown)}")
        if e["id"] in seen:
            raise ConfigError(f"duplicate provider id {e['id']}")
        seen.add(e["id"])
    return list(cfg.providers)


def build(cfg: Config, entry: dict[str, Any]) -> FirmwareProvider:
    token_env = (entry.get("auth") or {}).get("token_env")
    http = HttpClient(
        allowed_hosts=frozenset(entry["allowed_hosts"]),
        timeout=float(cfg.network("timeout_seconds")),
        max_retries=int(cfg.network("max_retries")),
        backoff=float(cfg.network("backoff_initial_seconds")),
        min_interval=float(cfg.network("min_interval_seconds")),
        user_agent=str(cfg.network("user_agent")),
        token=os.environ.get(token_env) if token_env else None,
    )
    return _load_class(entry["class"])(entry, http, Path(cfg.cache))


def get(cfg: Config, provider_id: str) -> FirmwareProvider:
    for e in entries(cfg):
        if e["id"] == provider_id:
            return build(cfg, e)
    raise NotFoundError(f"unknown provider '{provider_id}'")


def self_test(cfg: Config, entry: dict[str, Any]) -> list[str]:
    """Offline consistency checks: class loads, declared capabilities equal real ones."""
    problems: list[str] = []
    try:
        prov = build(cfg, entry)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return [f"cannot instantiate: {exc}"]
    real = prov.capabilities().as_dict()
    declared = dict(entry["capabilities"])
    if real != declared:
        problems.append(f"declared capabilities {declared} != implementation {real}")
    if entry["status"] == "active" and not any(real.values()):
        problems.append("status 'active' but no capability implemented")
    if real["download"] and entry["distribution_default"] not in ("unknown", "restricted"):
        problems.append("downloadable sources must default to unknown/restricted distribution")
    for url in entry["source_urls"]:
        if not url.startswith("https://"):
            problems.append(f"non-HTTPS source URL {url}")
    return problems
