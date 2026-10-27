#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ZairenkaiPrjctX contributors
"""Generate the app's compact AFID device-candidate asset.

Input: a checkout of Zairenkai-Database-Source at the commit locked in
integration/repository-lock.json (only database/staging/unresolved/lineageos_wiki is read).
Output: one JSON file with the selected factual fields, the source revision and the
CC BY-SA 3.0 attribution that the source data requires.

Every record stays "unverified": AFID has not confirmed these codenames with firmware evidence.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CODENAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,63}$")
SOURCE_DIR = "database/staging/unresolved/lineageos_wiki"


def fail(msg: str) -> None:
    print(f"afid_asset: {msg}", file=sys.stderr)
    sys.exit(2)


def candidate(path: Path) -> dict:
    rec = json.loads(path.read_text(encoding="utf-8"))
    for key in ("codename_key", "brand_id", "product_names", "soc", "source", "license", "verification"):
        if key not in rec:
            fail(f"{path.name}: missing {key}")
    if rec["license"].get("spdx") != "CC-BY-SA-3.0":
        fail(f"{path.name}: unexpected licence {rec['license'].get('spdx')!r}")
    if rec["verification"].get("status") != "unverified":
        fail(f"{path.name}: expected verification status 'unverified'")
    if not CODENAME_RE.match(rec["codename_key"]):
        fail(f"{path.name}: unusable codename {rec['codename_key']!r}")
    soc = rec.get("soc") or {}
    return {
        "codename": rec["codename_key"],
        "brand_id": rec["brand_id"],
        "product_names": [str(p) for p in rec.get("product_names", [])],
        "model_numbers": [str(m) for m in rec.get("model_numbers", [])],
        "soc": {k: soc.get(k) for k in ("vendor", "platform", "architecture")},
        "release_date": rec.get("release_date"),
        "source_url": rec["source"]["url"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True, help="Zairenkai-Database-Source checkout")
    ap.add_argument("--commit", required=True, help="locked commit of that checkout")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    src = args.source / SOURCE_DIR
    files = sorted(p for p in src.glob("*.json"))
    if not files:
        fail(f"no records in {src}")
    devices = [candidate(p) for p in files]
    seen: dict[str, int] = {}
    for d in devices:
        seen[d["codename"]] = seen.get(d["codename"], 0) + 1
    readme = (src / "README.md").read_text(encoding="utf-8")
    attribution = ("Device metadata from the LineageOS Wiki (https://wiki.lineageos.org), "
                   "(c) The LineageOS Project, licensed under CC BY-SA 3.0 "
                   "(https://creativecommons.org/licenses/by-sa/3.0/). Adapted by AFID "
                   "(selected factual fields, reshaped) and by Zairenkai App (fields reduced further).")
    if "CC BY-SA 3.0" not in readme:
        fail("source README no longer states CC BY-SA 3.0; re-check the licence before packaging")
    asset = {
        "schema": 1,
        "generated_from": {
            "repository": "ZairenkaiPrjctX/Zairenkai-Database-Source",
            "commit": args.commit,
            "path": SOURCE_DIR,
        },
        "license": {"spdx": "CC-BY-SA-3.0", "attribution": attribution, "share_alike": True},
        "verification": "unverified",
        "note": "Community-reported codenames. AFID has not verified them with firmware or an official source.",
        "duplicate_codenames": sorted(c for c, n in seen.items() if n > 1),
        "count": len(devices),
        "devices": devices,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(asset, indent=None, separators=(",", ":"), sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"afid_asset: {len(devices)} candidates -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
