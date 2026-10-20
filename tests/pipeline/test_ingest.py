"""tools/ingest.py behaviour: offline dry-run, explicit and enabled sources only, bounded
discovery against an in-process fake GitLab, error handling and safe output paths."""

from __future__ import annotations

import json
import os
from typing import Any

from afid.errors import ConfigError, PolicyViolationError
from afid.pipeline import EXIT_BUDGET, EXIT_OK, EXIT_PARTIAL, EXIT_PROVIDER, EXIT_VALIDATION
from afid.pipeline.run import RunOptions, run, run_timestamp, safe_output_path
from afid.pipeline.urlpolicy import GuardedHttpClient
from afid.pipeline.validation import manifest_problems
from tests.dumps.fake_gitlab import Resp, http_error
from tests.pipeline.support import Clock, PipelineCase, add_project, fake_gitlab, http_factory

TS = "2026-10-20T00:00:00Z"
C1, C2, C3 = "a" * 40, "b" * 40, "c" * 40


class DryRunTest(PipelineCase):
    def test_dry_run_is_offline_and_deterministic(self) -> None:
        m1, path, code = run(self.root, RunOptions("dry-run", generated_at=TS))
        first = path.read_bytes()
        m2, _, _ = run(self.root, RunOptions("dry-run", generated_at=TS))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(first, path.read_bytes())
        self.assertEqual(m1, m2)
        self.assertEqual(
            m1["summary"],
            {"discovered": 4, "validated": 3, "skipped": 0, "duplicate": 1, "failed": 0},
        )
        self.assertEqual(m1["binary_downloads"], 0)
        self.assertEqual(manifest_problems(self.root, path), [])
        self.assertTrue(path.is_relative_to(self.root / "build"))
        # Sorted keys and records: the file is byte-identical for identical input.
        self.assertEqual(
            [r["record_id"] for r in m1["records"]], sorted(r["record_id"] for r in m1["records"])
        )

    def test_dry_run_reports_planned_sources_without_requests(self) -> None:
        m, _, code = run(
            self.root,
            RunOptions("dry-run", sources=["tadiphone_dumps"], max_records=5, generated_at=TS),
        )
        self.assertEqual(code, EXIT_OK)
        planned = next(s for s in m["sources"] if s["source_id"] == "tadiphone_dumps")
        self.assertEqual(
            (planned["status"], planned["requests"], planned["enabled"]), ("planned", 0, False)
        )
        self.assertEqual(planned["limits"]["max_records"], 5)

    def test_run_timestamp_sources(self) -> None:
        self.assertEqual(run_timestamp(None, {"SOURCE_DATE_EPOCH": "0"}), "1970-01-01T00:00:00Z")
        self.assertEqual(run_timestamp(TS, {}), TS)
        with self.assertRaises(ConfigError):
            run_timestamp("yesterday", {})
        with self.assertRaises(ConfigError):
            run_timestamp(None, {"SOURCE_DATE_EPOCH": "soon"})

    def test_safe_output_paths(self) -> None:
        build = self.root / "build"
        self.assertEqual(
            safe_output_path(self.root, "build/x/m.json"), (build / "x/m.json").resolve()
        )
        for bad in (
            "../m.json",
            "build/../registry/sources.json",
            "database/m.json",
            "registry/sources.json",
            "/tmp/m.json",
            "build/m.txt",
            "build",
        ):
            with self.subTest(path=bad), self.assertRaises(PolicyViolationError):
                safe_output_path(self.root, bad)
        build.mkdir()
        (build / "link").symlink_to(self.root / "registry")
        with self.assertRaises(PolicyViolationError):
            safe_output_path(self.root, "build/link/sources.json")
        with self.assertRaises(PolicyViolationError):  # checked before anything is written
            run(self.root, RunOptions("dry-run", output="registry/sources.json", generated_at=TS))
        self.assertEqual(
            json.loads((self.root / "registry/sources.json").read_text())["registry_version"], 1
        )


class DiscoverTest(PipelineCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = Clock()
        self.fake = fake_gitlab()
        add_project(
            self.fake,
            1,
            "xiaomi/achilles",
            {
                "achilles-user-7.1.1-NMF26X-7.6.14-release-keys": C1,
                "achilles-user-8.0.0-OPR1.170623.032-8.1.1-release-keys": C2,
            },
        )
        add_project(self.fake, 2, "google/empty", {})  # no default branch: skipped
        add_project(self.fake, 3, "nokia/gone", {"x-user-9-PPR1.180610.011-1-release-keys": C3})

    def discover(self, transport: Any = None, **opts: Any) -> tuple[dict[str, Any], int]:
        opts.setdefault("generated_at", TS)
        m, path, code = run(
            self.root,
            RunOptions("discover", sources=["android_dumps_gitlab"], **opts),
            http_factory=http_factory(transport or self.fake.open, self.clock),
            clock=self.clock,
        )
        self.assertEqual(manifest_problems(self.root, path), [])
        return m, code

    def test_discover_refuses_disabled_sources(self) -> None:
        with self.assertRaisesRegex(PolicyViolationError, "disabled"):
            run(
                self.root,
                RunOptions("discover", sources=["android_dumps_gitlab"]),
                http_factory=http_factory(self.fake.open, self.clock),
            )
        self.assertEqual(self.fake.requests, [])
        self.enable("tadiphone_dumps")
        with self.assertRaisesRegex(PolicyViolationError, "android_dumps_gitlab"):
            run(
                self.root,
                RunOptions("discover", sources=["tadiphone_dumps", "android_dumps_gitlab"]),
            )

    def test_discover_requires_explicit_known_source(self) -> None:
        with self.assertRaisesRegex(ConfigError, "explicit --source"):
            run(self.root, RunOptions("discover"))
        with self.assertRaisesRegex(ConfigError, "unknown source"):
            run(self.root, RunOptions("discover", sources=["https://evil.example"]))
        self.enable("dumprx")  # a tool: the registry itself becomes invalid
        with self.assertRaises(ConfigError):
            run(self.root, RunOptions("discover", sources=["dumprx"]))

    def test_discover_with_fake_gitlab(self) -> None:
        self.enable("android_dumps_gitlab")
        self.fake.fail_once["projects/3/repository/branches"] = 404  # repository not readable
        m, code = self.discover()
        self.assertEqual(code, EXIT_OK, m)
        self.assertEqual(
            m["summary"],
            {"discovered": 2, "validated": 2, "skipped": 2, "duplicate": 0, "failed": 0},
        )
        src = m["sources"][0]
        self.assertEqual((src["status"], src["truncated"], src["requests"]), ("ok", False, 3))
        builds = sorted(r["build_id"] for r in m["records"])
        self.assertEqual(builds, ["NMF26X", "OPR1.170623.032"])
        self.assertTrue(
            all(
                r["source_url"].startswith(
                    "https://gitlab.com/Android-Dumps/xiaomi/achilles/-/tree/"
                )
                for r in m["records"]
            )
        )

    def test_no_binary_downloads_in_initial_mode(self) -> None:
        self.enable("android_dumps_gitlab")
        calls: list[str] = []
        original = GuardedHttpClient.download

        def spy(self_: Any, *a: Any, **k: Any) -> Any:
            calls.append("download")
            return original(self_, *a, **k)

        GuardedHttpClient.download = spy  # type: ignore[method-assign]
        self.addCleanup(setattr, GuardedHttpClient, "download", original)
        m, _ = self.discover()
        self.assertEqual(calls, [])
        self.assertEqual(m["binary_downloads"], 0)
        for url in self.fake.requests:  # listings only: no file, raw, archive or tree endpoints
            self.assertRegex(
                url, r"/api/v4/(groups/13303221/projects|projects/\d+/repository/branches)\?"
            )
        self.assertTrue(
            all(r["download_url"] is None and r["sha256"] is None for r in m["records"])
        )

    def test_record_and_page_limits_truncate(self) -> None:
        self.enable("android_dumps_gitlab")
        m, code = self.discover(max_records=1)
        self.assertEqual(
            (code, m["summary"]["validated"], m["sources"][0]["truncated"]), (EXIT_OK, 1, True)
        )
        for i in range(10, 160):  # more than one page of projects
            add_project(
                self.fake,
                i,
                f"vendor/dev{i}",
                {f"dev{i}-user-14-AP1A.240505.005-{i}-release-keys": f"{i:040x}"},
            )
        m, _ = self.discover(max_pages=1, max_records=500)
        self.assertTrue(m["sources"][0]["truncated"])
        self.assertEqual(sum(1 for u in self.fake.requests if "/groups/" in u and "page=2" in u), 0)

    def test_request_budget_truncates_without_failing(self) -> None:
        self.enable("android_dumps_gitlab", max_requests=2)
        m, code = self.discover()
        src = m["sources"][0]
        self.assertEqual(
            (code, src["status"], src["truncated"], src["requests"]), (EXIT_OK, "ok", True, 2)
        )
        self.assertEqual(m["summary"]["validated"], 2)

    def test_cli_limits_only_lower_registry_limits(self) -> None:
        self.enable("android_dumps_gitlab", max_requests=2)
        m, _ = self.discover(max_requests=500, max_records=10_000, max_pages=50)
        limits = m["sources"][0]["limits"]
        self.assertEqual(
            (limits["max_requests"], limits["max_records"], limits["max_pages"]), (2, 50, 1)
        )
        with self.assertRaises(ConfigError):
            self.discover(max_records=0)

    def test_rate_limit_is_retried_with_retry_after(self) -> None:
        self.enable("android_dumps_gitlab")
        self.fake.fail_once["groups/13303221/projects"] = 429  # fake sends Retry-After: 7
        m, code = self.discover()
        self.assertEqual(code, EXIT_OK)
        self.assertIn(7.0, self.clock.sleeps)
        self.assertEqual(m["sources"][0]["requests"], 4)  # the throttled attempt counts too

    def test_persistent_server_errors_are_bounded(self) -> None:
        self.enable("android_dumps_gitlab", max_retries=2)
        attempts: list[str] = []

        def down(req: Any) -> Any:
            attempts.append(req.full_url)
            raise http_error(req.full_url, 503)

        m, code = self.discover(down)
        self.assertEqual(len(attempts), 3)  # one try + two retries, then give up
        self.assertEqual(
            (code, m["status"], m["sources"][0]["status"]), (EXIT_PROVIDER, "failed", "failed")
        )
        self.assertIn("HTTP 503", m["sources"][0]["errors"][0])
        self.assertEqual([s for s in self.clock.sleeps if s > 0], [2.0, 4.0])  # exponential backoff

    def test_client_errors_are_not_retried(self) -> None:
        self.enable("android_dumps_gitlab")
        attempts: list[str] = []

        def forbidden(req: Any) -> Any:
            attempts.append(req.full_url)
            raise http_error(req.full_url, 403)

        _, code = self.discover(forbidden)
        self.assertEqual((len(attempts), code), (1, EXIT_PROVIDER))

    def test_malformed_source_responses(self) -> None:
        self.enable("android_dumps_gitlab")

        def html(req: Any) -> Any:
            return Resp(b"<html>login</html>", {"Content-Type": "text/html"}, req.full_url)

        m, code = self.discover(html)
        self.assertEqual(code, EXIT_PROVIDER)
        self.assertIn("not valid JSON", m["sources"][0]["errors"][0])

        def not_a_list(req: Any) -> Any:
            return Resp(json.dumps({"message": "x"}).encode(), {}, req.full_url)

        m, code = self.discover(not_a_list)
        self.assertIn("expected a JSON list", m["sources"][0]["errors"][0])

        def broken_branches(req: Any) -> Any:
            if "/repository/branches" in req.full_url:
                rows = [
                    {"name": "ok-user-14-AP1A.1-1-release-keys", "commit": {"id": C1}},
                    {"name": "no-commit"},
                    {"name": "bad", "commit": {"id": "zz"}},
                    "junk",
                ]
                return Resp(json.dumps(rows).encode(), {}, req.full_url)
            return self.fake.open(req)

        m, code = self.discover(broken_branches)
        self.assertEqual(code, EXIT_VALIDATION)
        self.assertEqual(m["status"], "partial")
        self.assertGreaterEqual(m["summary"]["failed"], 3)
        self.assertGreaterEqual(m["summary"]["validated"], 1)
        self.assertTrue(all(r["problems"] for r in m["rejected"]))

    def test_oversized_responses_are_refused(self) -> None:
        self.enable("android_dumps_gitlab", max_response_bytes=1024)

        def huge(req: Any) -> Any:
            return Resp(b"[" + b" " * 4096 + b"]", {}, req.full_url)

        m, code = self.discover(huge)
        self.assertEqual(code, EXIT_PROVIDER)
        self.assertIn("larger than 1024 bytes", m["sources"][0]["errors"][0])

    def test_timeout_budget_stops_the_run(self) -> None:
        self.enable("android_dumps_gitlab", max_run_seconds=10)

        def slow(req: Any) -> Any:
            self.clock.now += 6  # each request takes 6 s of the 10 s budget
            return self.fake.open(req)

        m, code = self.discover(slow)
        src = m["sources"][0]
        self.assertEqual((code, src["status"]), (EXIT_BUDGET, "partial"))
        self.assertIn("run time budget", src["errors"][-1])
        self.assertEqual(src["requests"], 2)

    def test_network_errors_and_partial_sources(self) -> None:
        self.enable("android_dumps_gitlab", max_retries=0)

        def flaky(req: Any) -> Any:
            if "projects/1/repository" in req.full_url:
                raise TimeoutError("timed out")
            return self.fake.open(req)

        m, code = self.discover(flaky)
        self.assertEqual(
            (code, m["status"], m["sources"][0]["status"]), (EXIT_PARTIAL, "partial", "partial")
        )
        self.assertTrue(any("timed out" in e for e in m["sources"][0]["errors"]))

    def test_logs_do_not_contain_records_or_credentials(self) -> None:
        self.enable("android_dumps_gitlab")
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret-value"
        self.addCleanup(os.environ.pop, "AWS_SECRET_ACCESS_KEY", None)
        with self.assertLogs("afid", level="INFO") as logs:
            self.discover()
        text = "\n".join(logs.output)
        self.assertNotIn("test-secret-value", text)
        self.assertNotIn("NMF26X", text)  # record contents stay in the manifest
