#!/usr/bin/env python3
"""Validate the metadata pipeline's configuration and outputs. Offline; no network.

  tools/validate.py all                     # schemas + registry/sources.json + fixture
  tools/validate.py manifest <path>         # a run manifest: schema, records, counts
  tools/validate.py summary <path>          # short JSON summary of a manifest (for logs)
  tools/validate.py checksum --manifest <path> --record-id <id> --file <local file>

Exit codes: 0 valid, 2 configuration problem, 3 validation failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afid.errors import AfidError  # noqa: E402
from afid.pipeline import EXIT_OK, EXIT_VALIDATION  # noqa: E402
from afid.pipeline.records import verify_file  # noqa: E402
from afid.pipeline.registry import read_json  # noqa: E402
from afid.pipeline.validation import config_problems, manifest_problems, summarize  # noqa: E402
from afid.utils import log  # noqa: E402


def report(what: str, problems: list[str]) -> int:
    if problems:
        print(f"{what}: {len(problems)} problem(s)", file=sys.stderr)
        for p in problems[:50]:
            print(f"  - {p}", file=sys.stderr)
        return EXIT_VALIDATION
    print(f"{what}: OK")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("all")
    for name in ("manifest", "summary"):
        sub.add_parser(name).add_argument("path", type=Path)
    c = sub.add_parser("checksum")
    c.add_argument("--manifest", type=Path, required=True)
    c.add_argument("--record-id", required=True)
    c.add_argument("--file", type=Path, required=True)
    args = p.parse_args(argv)
    log.setup()
    root = args.root.resolve()
    try:
        if args.cmd == "all":
            return report("pipeline schemas, registry and fixture", config_problems(root))
        if args.cmd == "manifest":
            return report(f"manifest {args.path}", manifest_problems(root, args.path))
        if args.cmd == "summary":
            doc, _ = read_json(args.path)
            print(json.dumps(summarize(doc), sort_keys=True))
            return EXIT_OK
        problems = manifest_problems(root, args.manifest)
        if problems:
            return report(f"manifest {args.manifest}", problems)
        doc, _ = read_json(args.manifest)
        rec = next((r for r in doc["records"] if r["record_id"] == args.record_id), None)
        if rec is None:
            return report("checksum", [f"record {args.record_id} is not in the manifest"])
        verified = verify_file(rec, args.file)
        print(f"checksum: OK ({verified['record_id']} matches {args.file.name})")
        return EXIT_OK
    except AfidError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
