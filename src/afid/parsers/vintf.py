"""VINTF manifest / compatibility matrix parser. Rejects DTDs and entities (XXE, entity
expansion) before handing the document to ElementTree."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 - guarded by reject_dtd()
from typing import Any

MAX_XML_BYTES = 8 * 1024 * 1024


class XmlRejected(ValueError):
    pass


def reject_dtd(data: bytes) -> None:
    if len(data) > MAX_XML_BYTES:
        raise XmlRejected("XML larger than limit")
    head = data.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise XmlRejected("XML with DOCTYPE/ENTITY declarations is not parsed")


def safe_fromstring(data: bytes) -> ET.Element:
    reject_dtd(data)
    try:
        return ET.fromstring(data)  # noqa: S314 - DTD/entities rejected above
    except ET.ParseError as exc:
        raise XmlRejected(f"malformed XML: {exc}") from exc


def parse(data: bytes) -> dict[str, Any]:
    root = safe_fromstring(data)
    hals: list[dict[str, Any]] = []
    for hal in root.iter("hal"):
        name = (hal.findtext("name") or "").strip()
        interfaces = [
            {
                "name": (i.findtext("name") or "").strip(),
                "instances": [x.text.strip() for x in i.findall("instance") if x.text],
            }
            for i in hal.findall("interface")
        ]
        hals.append(
            {
                "format": hal.get("format", "hidl"),
                "name": name,
                "versions": [v.text.strip() for v in hal.findall("version") if v.text],
                "transport": (hal.findtext("transport") or "").strip() or None,
                "fqnames": [f.text.strip() for f in hal.findall("fqname") if f.text],
                "interfaces": interfaces,
            }
        )
    return {
        "root": root.tag,
        "type": root.get("type"),
        "version": root.get("version"),
        "hals": hals,
    }
