"""tools/validate.py manifest: a manifest edited after generation is rejected."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from afid.pipeline.run import RunOptions, run
from afid.pipeline.validation import manifest_problems, summarize
from tests.pipeline.support import PipelineCase, deep


class ManifestValidationTest(PipelineCase):
    def setUp(self) -> None:
        super().setUp()
        self.manifest, self.path, _ = run(
            self.root, RunOptions("dry-run", generated_at="2026-10-20T00:00:00Z")
        )

    def problems_after(self, change: Callable[[dict[str, Any]], None]) -> list[str]:
        doc = deep(self.manifest)
        change(doc)
        target = self.path.with_name("tampered.json")
        target.write_text(json.dumps(doc))
        return manifest_problems(self.root, target)

    def test_manifest_validation_detects_tampering(self) -> None:
        self.assertEqual(manifest_problems(self.root, self.path), [])

        def counts(d: dict[str, Any]) -> None:
            d["summary"]["validated"] = 99

        def duplicate(d: dict[str, Any]) -> None:
            d["records"].append(d["records"][0])

        def unsorted(d: dict[str, Any]) -> None:
            d["records"].reverse()

        def verified(d: dict[str, Any]) -> None:
            d["records"][0]["validation_status"] = "checksum_verified"

        def foreign_host(d: dict[str, Any]) -> None:
            d["records"][0]["source_url"] = "https://evil.example/x"

        def download(d: dict[str, Any]) -> None:
            d["binary_downloads"] = 1

        def unknown_source(d: dict[str, Any]) -> None:
            d["records"][0]["source_id"] = "not_in_registry"

        for change in (
            counts,
            duplicate,
            unsorted,
            verified,
            foreign_host,
            download,
            unknown_source,
        ):
            with self.subTest(change=change.__name__):
                self.assertTrue(self.problems_after(change))

    def test_invalid_json_and_oversized_manifests(self) -> None:
        bad = self.path.with_name("bad.json")
        bad.write_text("{not json")
        self.assertTrue(manifest_problems(self.root, bad))
        big = self.path.with_name("big.json")
        big.write_bytes(b" " * (1024 * 1024 + 1))
        self.assertIn("exceeds", manifest_problems(self.root, big)[0])
        self.assertTrue(manifest_problems(self.root, self.path.with_name("missing.json")))

    def test_summary_has_no_record_contents(self) -> None:
        text = json.dumps(summarize(self.manifest))
        self.assertNotIn('records":', text)
        self.assertNotIn("synthalpha", text)
        self.assertIn('"validated": 3', text)
