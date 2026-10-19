"""Configuration loading. The repository root is found from --root, $AFID_ROOT, or the
nearest parent directory of the working directory that contains config/settings.yml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from afid.errors import ConfigError

MARKER = Path("config") / "settings.yml"


def find_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not (root / MARKER).is_file():
            raise ConfigError(f"{root} is not an AFID repository (missing {MARKER})")
        return root
    env = os.environ.get("AFID_ROOT")
    if env:
        return find_root(env)
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / MARKER).is_file():
            return candidate
    raise ConfigError(f"no {MARKER} found in {here} or its parents; pass --root or set AFID_ROOT")


def load_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc


@dataclass
class Config:
    root: Path
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def _load(self, name: str) -> Any:
        if name not in self._cache:
            data = load_yaml(self.root / "config" / name)
            if not isinstance(data, dict):
                raise ConfigError(f"config/{name} must be a mapping")
            self._cache[name] = data
        return self._cache[name]

    @cached_property
    def settings(self) -> dict[str, Any]:
        return dict(self._load("settings.yml"))

    @cached_property
    def brands(self) -> list[dict[str, Any]]:
        return list(self._load("brands.yml")["brands"])

    @cached_property
    def brand_ids(self) -> list[str]:
        return [b["brand_id"] for b in self.brands]

    @cached_property
    def core_brand_ids(self) -> list[str]:
        return [b["brand_id"] for b in self.brands if b.get("scope", "core") == "core"]

    @cached_property
    def rules(self) -> dict[str, Any]:
        return dict(self._load("component_rules.yml"))

    @cached_property
    def policy(self) -> dict[str, Any]:
        return dict(self._load("source_policy.yml"))

    @cached_property
    def allowlist(self) -> list[dict[str, Any]]:
        return list(self._load("redistributable_allowlist.yml").get("entries") or [])

    @cached_property
    def providers(self) -> list[dict[str, Any]]:
        return list(self._load("provider_registry.yml")["providers"])

    def path(self, key: str) -> Path:
        return self.root / str(self.settings["paths"][key])

    @property
    def database(self) -> Path:
        return self.path("database")

    @property
    def schemas_dir(self) -> Path:
        return self.path("schemas")

    @property
    def cache(self) -> Path:
        return self.path("cache")

    def limit(self, key: str) -> int:
        return int(self.settings["limits"][key])

    def network(self, key: str) -> Any:
        return self.settings["network"][key]


def load(root: str | os.PathLike[str] | None = None) -> Config:
    return Config(find_root(root))
