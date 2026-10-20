"""S3 publishing is off unless explicitly enabled, uploads exactly one object under the
staging prefix, and the tools run end to end without AWS credentials or network."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from afid.errors import ConfigError, ProviderError, ValidationError
from afid.pipeline import publish as pub
from afid.pipeline.run import RunOptions, run
from afid.pipeline.validation import manifest_problems
from tests.pipeline.support import REPO, PipelineCase

ENV = {
    "ENABLE_S3_PUBLISH": "true",
    "STAGING_BUCKET": "zairenkai-firmware-staging-20261020-x7k9",
    "STAGING_PREFIX": "staging/",
    "EXPECTED_BUCKET_OWNER": "123456789012",
    "CODEBUILD_BUILD_ID": "zairenkai-database-source-dryrun:0a1b2c3d-4e5f-6789-abcd-ef0123456789",
}


class PublishTest(PipelineCase):
    def manifest(self) -> Path:
        _, path, _ = run(self.root, RunOptions("dry-run", generated_at="2026-10-20T00:00:00Z"))
        return path

    def test_publish_is_disabled_by_default(self) -> None:
        self.assertIsNone(pub.plan({}))
        self.assertIsNone(
            pub.plan(
                {
                    "ENABLE_S3_PUBLISH": "false",
                    **{k: v for k, v in ENV.items() if k != "ENABLE_S3_PUBLISH"},
                }
            )
        )
        sys.path.insert(0, str(REPO / "tools"))
        self.addCleanup(sys.path.remove, str(REPO / "tools"))
        import publish_manifest

        calls: list[list[str]] = []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = publish_manifest.main(
                [str(self.manifest()), "--root", str(self.root)],
                runner=lambda c: calls.append(c) or 0,
            )
        self.assertEqual((code, calls), (0, []))
        self.assertIn("S3 publish disabled", out.getvalue())

    def test_publish_rejects_unexpected_flag_values(self) -> None:
        for value in ("TRUE", "yes", "1", "true "):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                pub.plan({**ENV, "ENABLE_S3_PUBLISH": value})

    def test_publish_plan_uses_exact_prefix_key(self) -> None:
        p = pub.plan(ENV)
        assert p is not None
        self.assertEqual(p.bucket, "zairenkai-firmware-staging-20261020-x7k9")
        self.assertEqual(
            p.key,
            "staging/runs/zairenkai-database-source-dryrun-0a1b2c3d-4e5f-6789-abcd-ef0123456789/manifest.json",
        )
        self.assertTrue(p.key.startswith("staging/runs/"))

    def test_publish_requires_bucket_owner_and_valid_prefix(self) -> None:
        for key, value in (
            ("STAGING_PREFIX", ""),
            ("STAGING_PREFIX", "staging"),
            ("STAGING_PREFIX", "/staging/"),
            ("STAGING_PREFIX", "staging/../"),
            ("STAGING_PREFIX", "Staging/"),
            ("STAGING_BUCKET", ""),
            ("STAGING_BUCKET", "Bad_Bucket"),
            ("STAGING_BUCKET", "a..b"),
            ("EXPECTED_BUCKET_OWNER", ""),
            ("EXPECTED_BUCKET_OWNER", "12345"),
            ("CODEBUILD_BUILD_ID", ""),
            ("CODEBUILD_BUILD_ID", ":::"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                pub.plan({**ENV, key: value})

    def test_publish_command_is_a_single_put_object(self) -> None:
        p = pub.plan(ENV)
        assert p is not None
        calls: list[list[str]] = []
        pub.publish(p, self.manifest(), runner=lambda c: calls.append(c) or 0)
        self.assertEqual(len(calls), 1)
        cmd = calls[0]
        self.assertEqual(cmd[:3], ["aws", "s3api", "put-object"])
        self.assertEqual(cmd[cmd.index("--expected-bucket-owner") + 1], "123456789012")
        self.assertEqual(cmd[cmd.index("--key") + 1], p.key)
        self.assertNotIn("--acl", cmd)
        with self.assertRaises(ProviderError):
            pub.publish(p, self.manifest(), runner=lambda c: 255)

    def test_publish_refuses_invalid_or_oversized_manifests(self) -> None:
        p = pub.plan(ENV)
        assert p is not None
        big = self.root / "build" / "big.json"
        big.parent.mkdir(parents=True, exist_ok=True)
        big.write_bytes(b" " * (pub.MAX_MANIFEST_BYTES + 1))
        with self.assertRaises(ValidationError):
            pub.publish(p, big, runner=lambda c: 0)
        sys.path.insert(0, str(REPO / "tools"))
        self.addCleanup(sys.path.remove, str(REPO / "tools"))
        import publish_manifest

        bad = big.with_name("bad.json")
        bad.write_text(json.dumps({"schema_version": "1.0"}))
        os.environ.update(ENV)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ENV])
        calls: list[Any] = []
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = publish_manifest.main(
                [str(bad), "--root", str(self.root)], runner=lambda c: calls.append(c) or 0
            )
        self.assertEqual((code, calls), (3, []))
        self.assertIn("refusing to upload an invalid manifest", err.getvalue())


class ToolsEndToEndTest(PipelineCase):
    allow_subprocess = True

    def run_tool(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(REPO / "tools" / args[0]),
                *args[1:],
                "--root",
                str(self.root),
            ]
            if args[0] != "validate.py"
            else [
                sys.executable,
                "-I",
                str(REPO / "tools" / "validate.py"),
                "--root",
                str(self.root),
                *args[1:],
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )

    def test_dry_run_without_aws_credentials(self) -> None:
        home = self.root / "home"
        home.mkdir()
        # No AWS credentials or config, no ENABLE_S3_PUBLISH, and a dead proxy: any network
        # access would fail. The dry-run, validation and publish step must still succeed.
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "AWS_CONFIG_FILE": str(home / "none"),
            "AWS_SHARED_CREDENTIALS_FILE": str(home / "none"),
            "AWS_EC2_METADATA_DISABLED": "true",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "SOURCE_DATE_EPOCH": "1792454400",
        }
        out = "build/pipeline/manifest.json"
        r = self.run_tool("ingest.py", "--mode", "dry-run", "--output", out, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        summary = json.loads(r.stdout)
        self.assertEqual((summary["status"], summary["binary_downloads"]), ("ok", 0))
        self.assertEqual(manifest_problems(self.root, self.root / out), [])
        r = self.run_tool("validate.py", "all", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_tool("validate.py", "manifest", str(self.root / out), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_tool("publish_manifest.py", str(self.root / out), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("S3 publish disabled", r.stdout)
        r = self.run_tool("ingest.py", "--mode", "discover", "--source", "tadiphone_dumps", env=env)
        self.assertEqual(r.returncode, 9)
        self.assertIn("disabled", r.stderr)
