#!/usr/bin/env python3
"""Upload a validated run manifest to the existing S3 staging prefix, only when
ENABLE_S3_PUBLISH=true. Otherwise it prints that publishing is disabled and exits 0.

  ENABLE_S3_PUBLISH=true STAGING_BUCKET=... STAGING_PREFIX=staging/ \\
  EXPECTED_BUCKET_OWNER=<account id> CODEBUILD_BUILD_ID=... tools/publish_manifest.py <path>

Credentials come from the environment (in CodeBuild: the service role); this tool never
reads, prints or configures them.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afid.errors import AfidError  # noqa: E402
from afid.pipeline import EXIT_OK, EXIT_VALIDATION  # noqa: E402
from afid.pipeline import publish as pub  # noqa: E402
from afid.pipeline.validation import manifest_problems  # noqa: E402
from afid.utils import log  # noqa: E402


def main(argv: list[str] | None = None, runner: pub.Runner | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("path", type=Path)
    p.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    log.setup()
    try:
        target = pub.plan(os.environ)
        if target is None:
            print(f"S3 publish disabled ({pub.FLAG} is not 'true'); nothing uploaded")
            return EXIT_OK
        problems = manifest_problems(args.root.resolve(), args.path)
        if problems:
            print(f"refusing to upload an invalid manifest: {problems[0]}", file=sys.stderr)
            return EXIT_VALIDATION
        pub.publish(target, args.path, runner or pub._run)
    except AfidError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    print(f"uploaded manifest to {target.uri}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
