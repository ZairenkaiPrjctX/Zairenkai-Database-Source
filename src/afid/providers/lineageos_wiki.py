"""Community metadata provider: LineageOS wiki device data (_data/devices/*.yml).

Source: https://github.com/LineageOS/lineage_wiki (public). Used for device candidates
(codename, product name, models, SoC, release date). Community data never verifies a
codename on its own; candidates go to database/staging/unresolved/ until firmware evidence
(build.prop) or an official source confirms them.

Discovery reads a git checkout: `settings.checkout_dir` / $AFID_LINEAGE_WIKI_DIR if given,
otherwise a shallow sparse clone in the AFID cache. Per-file revision markers are git blob
SHA-1s, so unchanged files are recognised without trusting timestamps.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import yaml

from afid.errors import ProviderError, ToolMissingError
from afid.models import Evidence, valid_codename
from afid.providers.base import Capabilities, DeviceCandidate, DiscoveryResult, FirmwareProvider
from afid.utils.timeutil import utc_now

REPO = "https://github.com/LineageOS/lineage_wiki"
RAW = "https://raw.githubusercontent.com/LineageOS/lineage_wiki/main/_data/devices/"
DATA_DIR = "_data/devices"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _norm_date(value: Any) -> str | None:
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        return value
    if isinstance(value, list) and value:  # some files list several release dates
        dates = [
            d
            for d in (
                _norm_date(v if not isinstance(v, dict) else next(iter(v.values()), None))
                for v in value
            )
            if d
        ]
        return min(dates) if dates else None
    return None


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return sorted({str(v) for v in value if isinstance(v, (str, int))})
    if isinstance(value, (str, int)):
        return [str(value)]
    return []


def _architecture(value: Any) -> str | None:
    if isinstance(value, dict):
        return str(value.get("userspace") or value.get("cpu") or "") or None
    return str(value) if value else None


def _soc_vendor(soc: str | None) -> str | None:
    if not soc:
        return None
    low = soc.lower()
    for key, vendor in (
        ("qualcomm", "qualcomm"),
        ("snapdragon", "qualcomm"),
        ("mediatek", "mediatek"),
        ("dimensity", "mediatek"),
        ("helio", "mediatek"),
        ("exynos", "samsung_lsi"),
        ("tensor", "google"),
        ("unisoc", "unisoc"),
        ("kirin", "hisilicon"),
    ):
        if key in low:
            return vendor
    return None


class LineageWikiProvider(FirmwareProvider):
    CAPABILITIES = Capabilities(discover_devices=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.brand_rules: list[dict[str, Any]] = list(self.settings.get("brand_rules") or [])

    # ---- checkout -------------------------------------------------------------------------------
    def _checkout(self) -> tuple[Path, str | None]:
        explicit = self.settings.get("checkout_dir") or os.environ.get("AFID_LINEAGE_WIKI_DIR")
        if explicit:
            path = Path(explicit)
            if not (path / DATA_DIR).is_dir():
                raise ProviderError(f"{path} has no {DATA_DIR}/ directory")
            return path, self._head(path)
        git = shutil.which("git")
        if git is None:
            raise ToolMissingError("git", "fetch LineageOS wiki data", "apt install git")
        dest = self.cache / "lineage_wiki"
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if not (dest / ".git").is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._git(
                [git, "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO, str(dest)],
                env,
            )
            self._git([git, "-C", str(dest), "sparse-checkout", "set", DATA_DIR], env)
        else:
            self._git([git, "-C", str(dest), "fetch", "--depth", "1", "origin", "main"], env)
            self._git([git, "-C", str(dest), "reset", "--hard", "FETCH_HEAD"], env)
        return dest, self._head(dest)

    @staticmethod
    def _git(args: list[str], env: dict[str, str]) -> None:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=600, env=env, check=False
        )
        if proc.returncode != 0:
            raise ProviderError(f"git failed: {proc.stderr.strip()[:300]}")

    @staticmethod
    def _head(path: Path) -> str | None:
        if not (path / ".git").exists() or shutil.which("git") is None:
            return None
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.stdout.strip() or None

    # ---- brand mapping ----------------------------------------------------------------------
    def infer_brand(self, vendor: str, name: str) -> tuple[str | None, str]:
        for rule in self.brand_rules:
            if vendor not in rule["vendors"]:
                continue
            prefixes = rule.get("name_prefixes")
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            basis = f"vendor '{vendor}'" + (
                f" + product name prefix '{next(p for p in prefixes if name.startswith(p))}'"
                if prefixes
                else ""
            )
            return rule["brand_id"], basis + " (community data; unverified)"
        return None, f"vendor '{vendor}' / name '{name}' outside AFID brand scope"

    # ---- discovery ---------------------------------------------------------------------------
    def discover_devices(self, cancel: threading.Event | None = None) -> DiscoveryResult:
        result = DiscoveryResult(self.provider_id, "ok")
        checkout, head = self._checkout()
        result.index_revision = head
        now = utc_now()
        for path in sorted((checkout / DATA_DIR).glob("*.yml")):
            if cancel is not None and cancel.is_set():
                result.status = "partial"
                result.errors.append("cancelled")
                break
            raw = path.read_bytes()
            try:
                doc = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                result.errors.append(f"{path.name}: invalid YAML ({str(exc)[:120]})")
                result.status = "partial"
                continue
            if not isinstance(doc, dict) or not doc.get("codename"):
                result.errors.append(f"{path.name}: no codename")
                result.status = "partial"
                continue
            codename = str(doc["codename"])
            name = str(doc.get("name") or "")
            brand, basis = self.infer_brand(str(doc.get("vendor") or ""), name)
            if brand is None:
                result.skipped += 1
                continue
            if not valid_codename(codename):
                result.errors.append(f"{path.name}: unusable codename {codename!r}")
                continue
            soc = str(doc["soc"]) if doc.get("soc") else None
            url = RAW + path.name
            evidence: Evidence = {
                "evidence_type": "community_repository",
                "source": self.provider_id,
                "url": url,
                "retrieved_at": now,
                "detail": f"{path.name} (blob {git_blob_sha(raw)[:12]}): codename '{codename}', "
                f"name '{name}'",
                "confidence": 0.5,
            }
            result.candidates.append(
                DeviceCandidate(
                    item_id=path.stem,
                    revision=git_blob_sha(raw),
                    url=url,
                    brand_id=brand,
                    brand_inference=basis,
                    codename=codename,
                    product_names=[name] if name else [],
                    model_numbers=_str_list(doc.get("models")),
                    soc={
                        "vendor": _soc_vendor(soc),
                        "platform": soc,
                        "architecture": _architecture(doc.get("architecture")),
                    },
                    release_date=_norm_date(doc.get("release")),
                    evidence=evidence,
                )
            )
        return result
