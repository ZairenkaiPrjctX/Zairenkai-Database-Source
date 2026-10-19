"""Safe summarizers for thermal and power configuration files.

Original files are never modified. Summaries capture structure (names, counts, referenced
paths) so configurations can be compared across builds without storing the payload.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from afid.parsers.vintf import XmlRejected, safe_fromstring

MAX_CONFIG_BYTES = 16 * 1024 * 1024
PARTITION_PATH_RE = re.compile(
    r"(?<![\w/])/(?:vendor|odm|system|system_ext|product|vendor_dlkm|odm_dlkm)/[\w@.+/-]+"
)
SYSFS_RE = re.compile(r"(?<![\w/])/(?:sys|proc|dev)/[\w@.+:/-]+")


def _names(items: Any, key: str = "Name") -> list[str]:
    if not isinstance(items, list):
        return []
    return sorted({str(i[key]) for i in items if isinstance(i, dict) and key in i})


def references(text: str) -> dict[str, list[str]]:
    """Absolute paths mentioned in a config: partition files and runtime kernel nodes."""
    return {
        "partition_paths": sorted(set(PARTITION_PATH_RE.findall(text))),
        "runtime_nodes": sorted(set(SYSFS_RE.findall(text)))[:500],
    }


def summarize_json(data: bytes, kind: str) -> dict[str, Any]:
    doc = json.loads(data.decode("utf-8"))
    out: dict[str, Any] = {"format": "json"}
    if isinstance(doc, dict):
        out["top_level_keys"] = sorted(doc)
        if kind == "thermal_hal_config_json":
            out["sensors"] = _names(doc.get("Sensors"))
            out["cooling_devices"] = _names(doc.get("CoolingDevices"))
        elif kind == "powerhint_json":
            out["nodes"] = _names(doc.get("Nodes"))
            hints = doc.get("Actions")
            out["power_hints"] = _names(hints, "PowerHint")
            out["node_paths"] = sorted(
                {
                    str(n["Path"])
                    for n in doc.get("Nodes") or []
                    if isinstance(n, dict) and "Path" in n
                }
            )
    else:
        out["top_level_type"] = type(doc).__name__
    out.update(references(data.decode("utf-8", "replace")))
    return out


def summarize_xml(data: bytes) -> dict[str, Any]:
    root = safe_fromstring(data)
    counts: dict[str, int] = {}
    for child in root:
        counts[child.tag] = counts.get(child.tag, 0) + 1
    out: dict[str, Any] = {"format": "xml", "root": root.tag, "child_tag_counts": counts}
    out.update(references(data.decode("utf-8", "replace")))
    return out


def summarize_yaml(data: bytes) -> dict[str, Any]:
    """YAML config: top-level structure only. safe_load builds plain data, never Python
    objects; only top-level keys are read, so aliased (shared) nodes are never walked."""
    text = data.decode("utf-8", "replace")
    doc = yaml.safe_load(text)
    out: dict[str, Any] = {"format": "yaml"}
    if isinstance(doc, dict):
        out["top_level_keys"] = sorted(str(k) for k in doc)[:500]
    else:
        out["top_level_type"] = type(doc).__name__
    out.update(references(text))
    return out


def summarize_thermal_engine_conf(text: str) -> dict[str, Any]:
    """thermal-engine.conf: INI-like '[SECTION]' blocks with 'key value' lines."""
    sections: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            cur = {"name": m.group(1).strip(), "algo_type": None, "sensor": None}
            sections.append(cur)
            continue
        if cur is None:
            continue
        parts = line.split(None, 1)
        key, val = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        if key in ("algo_type", "sensor"):
            cur[key] = val
    out: dict[str, Any] = {
        "format": "thermal_engine_conf",
        "sections": [s["name"] for s in sections],
        "algo_types": sorted({s["algo_type"] for s in sections if s["algo_type"]}),
        "sensors": sorted({s["sensor"] for s in sections if s["sensor"]}),
    }
    out.update(references(text))
    return out


def summarize(data: bytes, subcategory: str, filename: str) -> tuple[str, dict[str, Any]]:
    """Return (parser_name, summary). Raises ValueError/XmlRejected on malformed input."""
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError("config larger than limit")
    lower = filename.lower()
    if lower.endswith(".json"):
        return "json", summarize_json(data, subcategory)
    if lower.endswith(".xml"):
        return "xml", summarize_xml(data)
    if lower.endswith((".yaml", ".yml")):
        try:
            return "yaml", summarize_yaml(data)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {str(exc)[:200]}") from None
    text = data.decode("utf-8", "replace")
    if "thermal-engine" in lower or subcategory == "thermal_engine_conf":
        return "thermal_engine_conf", summarize_thermal_engine_conf(text)
    return "text", {"format": "text", "lines": text.count("\n") + 1, **references(text)}


__all__ = ["XmlRejected", "references", "summarize"]
