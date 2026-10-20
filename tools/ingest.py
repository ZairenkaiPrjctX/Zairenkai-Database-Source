#!/usr/bin/env python3
"""Metadata pipeline run: discover firmware metadata within strict limits and write a
validated run manifest. Never downloads firmware.

  tools/ingest.py --mode dry-run                      # offline, synthetic fixture only
  tools/ingest.py --mode dry-run --source tadiphone_dumps   # + plan for a source, no requests
  tools/ingest.py --mode discover --source <id> [--max-records N] ...

discover accepts only sources enabled in registry/sources.json. Prints a one-line JSON
summary on stdout; logs go to stderr (JSON lines with AFID_LOG_FORMAT=json). Exit codes:
docs/AWS_PIPELINE.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afid.errors import AfidError  # noqa: E402
from afid.pipeline.run import DEFAULT_OUTPUT, RunOptions, run  # noqa: E402
from afid.utils import log  # noqa: E402


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--mode", required=True, choices=["dry-run", "discover"])
    p.add_argument("--source", action="append", default=[], help="registry source id (repeatable)")
    p.add_argument("--output", default=DEFAULT_OUTPUT, help="manifest path inside build/")
    p.add_argument("--max-pages", type=int, help="lower the registry's page limit")
    p.add_argument("--max-records", type=int, help="lower the registry's record limit")
    p.add_argument("--max-requests", type=int, help="lower the registry's request limit")
    p.add_argument("--timeout", type=float, help="lower the per-request timeout (seconds)")
    p.add_argument("--max-run-seconds", type=int, help="lower the per-source run time limit")
    p.add_argument("--generated-at", help="fixed run timestamp YYYY-MM-DDTHH:MM:SSZ")
    p.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    log.setup(args.verbose)
    opts = RunOptions(
        mode=args.mode,
        sources=args.source,
        output=args.output,
        max_pages=args.max_pages,
        max_records=args.max_records,
        max_requests=args.max_requests,
        timeout=args.timeout,
        max_run_seconds=args.max_run_seconds,
        generated_at=args.generated_at,
    )
    try:
        manifest, path, code = run(args.root.resolve(), opts)
    except AfidError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    root = args.root.resolve()
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "mode": manifest["mode"],
                "output": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "summary": manifest["summary"],
                "sources": {s["source_id"]: s["status"] for s in manifest["sources"]},
                "binary_downloads": manifest["binary_downloads"],
                "exit_code": code,
            },
            sort_keys=True,
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
