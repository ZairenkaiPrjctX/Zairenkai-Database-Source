"""build.prop parser. Only an allowlist of non-personal build properties is kept."""

from __future__ import annotations

KEEP = (
    "ro.build.fingerprint",
    "ro.system.build.fingerprint",
    "ro.vendor.build.fingerprint",
    "ro.odm.build.fingerprint",
    "ro.product.build.fingerprint",
    "ro.build.id",
    "ro.vendor.build.id",
    "ro.build.display.id",
    "ro.build.version.incremental",
    "ro.build.version.release",
    "ro.build.version.release_or_codename",
    "ro.build.version.sdk",
    "ro.vendor.build.version.sdk",
    "ro.build.version.security_patch",
    "ro.vendor.build.security_patch",
    "ro.build.date.utc",
    "ro.vendor.build.date.utc",
    "ro.build.type",
    "ro.build.tags",
    "ro.product.device",
    "ro.product.system.device",
    "ro.product.vendor.device",
    "ro.product.odm.device",
    "ro.product.product.device",
    "ro.build.product",
    "ro.product.model",
    "ro.product.vendor.model",
    "ro.product.odm.model",
    "ro.product.name",
    "ro.product.vendor.name",
    "ro.product.brand",
    "ro.product.vendor.brand",
    "ro.product.manufacturer",
    "ro.product.vendor.manufacturer",
    "ro.board.platform",
    "ro.soc.manufacturer",
    "ro.soc.model",
    "ro.hardware",
    "ro.product.cpu.abi",
    "ro.product.cpu.abilist",
    "ro.vendor.api_level",
    "ro.product.first_api_level",
    "ro.board.first_api_level",
    "ro.boot.dynamic_partitions",
    "ro.build.ab_update",
    "ro.mi.os.version.incremental",
    "ro.miui.ui.version.name",
)


def parse(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in KEEP:
            props[key] = value.strip()
    return props


def first(props: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        if props.get(k):
            return props[k]
    return None
