"""Optional upload of one run manifest to the existing S3 staging bucket.

Disabled unless ENABLE_S3_PUBLISH is exactly "true". When enabled it uploads only
<prefix>runs/<build id>/manifest.json with one `aws s3api put-object` call (argument list,
no shell), using whatever credentials the environment provides: in CodeBuild, the service
role's temporary credentials. It never configures credentials, never lists the bucket and
pins the bucket owner with --expected-bucket-owner.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from afid.errors import ConfigError, ProviderError, ValidationError
from afid.pipeline.validation import MAX_MANIFEST_BYTES

FLAG = "ENABLE_S3_PUBLISH"
# S3 general purpose bucket naming rules (lowercase, digits, dots, hyphens; 3-63 characters).
BUCKET = re.compile(r"^(?!xn--)(?!.*-s3alias$)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
PREFIX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}/$")
ACCOUNT = re.compile(r"^[0-9]{12}$")

Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class PublishPlan:
    bucket: str
    key: str
    expected_owner: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


def build_run_id(build_id: str) -> str:
    """CodeBuild ids look like '<project>:<uuid>'; keep a safe, unique path segment."""
    run_id = re.sub(r"[^A-Za-z0-9._-]", "-", build_id).strip("-.")
    if not run_id or len(run_id) > 200:
        raise ConfigError("CODEBUILD_BUILD_ID is empty or too long for an S3 key segment")
    return run_id


def plan(env: Mapping[str, str]) -> PublishPlan | None:
    """None when publishing is disabled (the default). Raises ConfigError for an enabled but
    incomplete or unsafe configuration, so a typo can never upload somewhere unexpected."""
    flag = env.get(FLAG, "")
    if flag in ("", "false"):
        return None
    if flag != "true":
        raise ConfigError(f"{FLAG} must be 'true' or 'false', not {flag!r}")
    bucket = env.get("STAGING_BUCKET", "")
    prefix = env.get("STAGING_PREFIX", "")
    owner = env.get("EXPECTED_BUCKET_OWNER", "")
    build_id = env.get("CODEBUILD_BUILD_ID", "")
    if not BUCKET.match(bucket) or ".." in bucket:
        raise ConfigError("STAGING_BUCKET is missing or not a valid S3 bucket name")
    if not PREFIX.match(prefix):
        raise ConfigError(
            "STAGING_PREFIX must look like 'staging/' (one lowercase segment and '/')"
        )
    if not ACCOUNT.match(owner):
        raise ConfigError("EXPECTED_BUCKET_OWNER must be the 12-digit account id owning the bucket")
    if not build_id:
        raise ConfigError("CODEBUILD_BUILD_ID is not set: publishing runs only inside CodeBuild")
    return PublishPlan(bucket, f"{prefix}runs/{build_run_id(build_id)}/manifest.json", owner)


def command(p: PublishPlan, manifest: Path) -> list[str]:
    return [
        "aws",
        "s3api",
        "put-object",
        "--bucket",
        p.bucket,
        "--key",
        p.key,
        "--body",
        str(manifest),
        "--content-type",
        "application/json",
        "--checksum-algorithm",
        "SHA256",
        "--expected-bucket-owner",
        p.expected_owner,
    ]


def _run(cmd: list[str]) -> int:
    # stdout carries the ETag/checksum JSON only; credentials never appear on the command line.
    return subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL).returncode


def publish(p: PublishPlan, manifest: Path, runner: Runner = _run) -> None:
    size = manifest.stat().st_size
    if size > MAX_MANIFEST_BYTES:
        raise ValidationError(f"manifest is {size} bytes; refusing to upload more than 1 MiB")
    code = runner(command(p, manifest))
    if code != 0:
        raise ProviderError(f"aws s3api put-object failed with exit code {code}")
