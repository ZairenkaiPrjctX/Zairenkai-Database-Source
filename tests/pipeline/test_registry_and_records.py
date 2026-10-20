"""Pipeline schemas, registry rules, deterministic records, provenance and checksums."""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from afid.errors import ConfigError, ValidationError
from afid.pipeline.records import (
    DATA_FIELDS,
    Item,
    Value,
    build_record,
    dump_branch_item,
    parse_build_description,
    record_id,
    record_problems,
    verify_file,
)
from afid.pipeline.registry import (
    Provider,
    fixture_problems,
    load_fixture,
    load_registry,
    registry_problems,
    validators,
)
from afid.pipeline.validation import config_problems
from tests.pipeline.support import REPO, PipelineCase

SYNTHETIC_BYTES = b"AFID synthetic fixture: not firmware\n"


class SchemaAndRegistryTest(PipelineCase):
    def test_pipeline_schemas_are_valid_draft_2020_12(self) -> None:
        for name in ("source-registry", "firmware-record", "run-manifest"):
            Draft202012Validator.check_schema(
                json.loads((REPO / "schemas" / f"{name}.schema.json").read_text())
            )
        self.assertEqual(config_problems(self.root), [])

    def test_registry_passes_schema_and_rules(self) -> None:
        reg = load_registry(self.root)
        self.assertEqual(
            sorted(reg.providers), ["android_dumps_gitlab", "dumprx", "tadiphone_dumps"]
        )
        self.assertEqual(len(reg.sha256), 64)

    def test_every_registry_provider_is_disabled_by_default(self) -> None:
        for p in self.registry()["providers"]:
            self.assertFalse(p["enabled"], p["id"])
            self.assertEqual(p["review"]["status"], "pending", p["id"])
            self.assertIsNone(p["last_successful_discovery"], p["id"])

    def test_enabling_requires_an_approved_review(self) -> None:
        doc = self.registry()
        self.provider(doc, "tadiphone_dumps")["enabled"] = True
        problems = registry_problems(self.root, doc)
        self.assertTrue(any("without an approved review" in p for p in problems), problems)
        self.write_registry(doc)
        with self.assertRaises(ConfigError):
            load_registry(self.root)
        # An approval needs a named reviewer and a date.
        self.provider(doc, "tadiphone_dumps")["review"]["status"] = "approved"
        problems = registry_problems(self.root, doc)
        self.assertTrue(any("must name reviewed_by" in p for p in problems), problems)

    def test_tool_cannot_be_enabled(self) -> None:
        doc = self.registry()
        p = self.provider(doc, "dumprx")
        p["enabled"] = True
        p["review"].update(status="approved", reviewed_by="x", reviewed_on="2026-10-20")
        problems = registry_problems(self.root, doc)
        self.assertTrue(any("no discovery strategy" in m for m in problems), problems)
        p["discovery"] = {
            "strategy": "gitlab_group_branches",
            "api_base": "https://github.com/api/v4",
            "group": 1,
            "group_path": "x",
        }
        self.assertTrue(
            any("strategy must be 'none'" in m for m in registry_problems(self.root, doc))
        )

    def test_registry_must_agree_with_provider_registry(self) -> None:
        doc = self.registry()
        p = self.provider(doc, "android_dumps_gitlab")
        p["discovery"]["group"] = 1
        p["allowed_hosts"].append("example.org")
        problems = registry_problems(self.root, doc)
        self.assertTrue(any("discovery.group" in m for m in problems), problems)
        self.assertTrue(any("not allowed for 'android_dumps_gitlab'" in m for m in problems))

    def test_registry_rejects_unsafe_urls_and_hosts(self) -> None:
        doc = self.registry()
        p = self.provider(doc, "tadiphone_dumps")
        p["base_url"] = "https://evil.example/dumps"
        p["allowed_hosts"] = ["dumps.tadiphone.dev", "10.0.0.1"]
        problems = registry_problems(self.root, doc)
        self.assertTrue(any("schema" in m or "10.0.0.1" in m for m in problems), problems)
        p["allowed_hosts"] = ["dumps.tadiphone.dev"]
        problems = registry_problems(self.root, doc)
        self.assertTrue(any("base_url" in m and "allowlist" in m for m in problems), problems)

    def test_fixture_hosts_must_be_reserved(self) -> None:
        provider, items = load_fixture(self.root)
        self.assertEqual(provider.allowed_hosts, frozenset({"fixtures.afid.invalid"}))
        self.assertFalse(provider.enabled)
        doc = json.loads((self.root / "registry/fixtures/synthetic-dry-run.json").read_text())
        doc["provider"]["allowed_hosts"] = ["gitlab.com"]
        doc["provider"]["base_url"] = "https://gitlab.com/x"
        self.assertTrue(any(".invalid" in p for p in fixture_problems(self.root, doc)))


class RecordTest(PipelineCase):
    def setUp(self) -> None:
        super().setUp()
        self.reg = load_registry(self.root)
        self.dumps = self.reg.providers["android_dumps_gitlab"]
        self.v = validators(self.root)["firmware-record"]
        self.item = dump_branch_item(
            "xiaomi/achilles",
            "achilles-user-7.1.1-NMF26X-7.6.14-release-keys",
            "3e4652487779acfbd6077e2cc559f7e786be696e",
            "https://gitlab.com/Android-Dumps/xiaomi/achilles",
        )

    def test_record_ids_are_deterministic_and_time_independent(self) -> None:
        a = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        b = build_record(self.dumps, self.item, "2027-01-01T12:00:00Z")
        self.assertEqual(a["record_id"], b["record_id"])
        self.assertRegex(a["record_id"], r"^fwr_[0-9a-f]{32}$")
        other = self.reg.providers["tadiphone_dumps"]
        self.assertNotEqual(record_id(other.id, self.item.source_item_id), a["record_id"])
        self.assertNotEqual(
            record_id(self.dumps.id, self.item.source_item_id + "x"), a["record_id"]
        )

    def test_build_description_parsing(self) -> None:
        self.assertEqual(
            parse_build_description("achilles-user-7.1.1-NMF26X-7.6.14-release-keys"),
            {
                "product": "achilles",
                "type": "user",
                "release": "7.1.1",
                "build_id": "NMF26X",
                "incremental": "7.6.14",
                "tags": "release-keys",
            },
        )
        parsed = parse_build_description(
            "missi_phone_global-user-14-UP1A.231005.007-V816.0.11.0.UKWMIXM-release-keys"
        )
        assert parsed is not None
        self.assertEqual(
            (parsed["release"], parsed["build_id"], parsed["incremental"]),
            ("14", "UP1A.231005.007", "V816.0.11.0.UKWMIXM"),
        )
        self.assertIsNone(parse_build_description("main"))
        self.assertIsNone(parse_build_description("x-user-14-ID-1-unsigned"))

    def test_inferred_values_are_labelled_inferred(self) -> None:
        rec = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        self.assertEqual(record_problems(rec, self.dumps, self.v), [])
        self.assertEqual(
            (rec["manufacturer"], rec["device_codename"], rec["android_version"], rec["build_id"]),
            ("xiaomi", "achilles", "7.1.1", "NMF26X"),
        )
        for name in ("manufacturer", "device_codename", "android_version", "build_id"):
            self.assertEqual(rec["provenance"][name]["origin"], "inferred")
        self.assertEqual(rec["validation_status"], "unverified")
        self.assertEqual(
            rec["source_url"],
            "https://gitlab.com/Android-Dumps/xiaomi/achilles/-/tree/"
            "3e4652487779acfbd6077e2cc559f7e786be696e",
        )

    def test_missing_fields_are_null_with_unknown_provenance(self) -> None:
        rec = build_record(
            self.dumps, Item("a@b", None, "https://gitlab.com/x"), "2026-10-20T00:00:00Z"
        )
        self.assertEqual(record_problems(rec, self.dumps, self.v), [])
        for name in DATA_FIELDS:
            self.assertIsNone(rec[name])
            self.assertEqual(rec["provenance"][name]["origin"], "unknown")

    def test_provenance_must_match_values(self) -> None:
        rec = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        rec["soc"] = "sm8150"  # a value nobody accounted for
        self.assertTrue(
            any("soc: provenance" in p for p in record_problems(rec, self.dumps, self.v))
        )
        rec = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        del rec["provenance"]["region"]
        self.assertTrue(record_problems(rec, self.dumps, self.v))

    def test_unverified_records_cannot_claim_checksum_verification(self) -> None:
        rec = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        rec["validation_status"] = "checksum_verified"
        self.assertTrue(
            any("checksum_verified" in p for p in record_problems(rec, self.dumps, self.v))
        )
        rec["validation_status"] = "verified"
        self.assertTrue(record_problems(rec, self.dumps, self.v))  # not a status at all

    def test_record_urls_must_use_allowed_hosts(self) -> None:
        rec = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        rec["download_url"] = "https://downloads.example.org/fw.zip"
        rec["provenance"]["download_url"] = {
            "origin": "source",
            "method": "m",
            "source_field": None,
        }
        self.assertTrue(
            any(
                "download_url" in p and "allowlist" in p
                for p in record_problems(rec, self.dumps, self.v)
            )
        )
        rec["download_url"] = "http://gitlab.com/fw.zip"
        self.assertTrue(record_problems(rec, self.dumps, self.v))
        rec = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        rec["record_id"] = "fwr_" + "0" * 32
        self.assertTrue(
            any("deterministic id" in p for p in record_problems(rec, self.dumps, self.v))
        )

    def test_invalid_dates_and_checksums_rejected(self) -> None:
        item = Item(
            "pkg",
            None,
            "https://gitlab.com/p",
            {
                "release_date": Value("2026-02-30", "source", "m"),
                "sha256": Value("ABC123", "source", "m"),
            },
        )
        problems = record_problems(
            build_record(self.dumps, item, "2026-10-20T00:00:00Z"), self.dumps, self.v
        )
        self.assertTrue(any("release_date" in p for p in problems), problems)
        self.assertTrue(any("sha256" in p for p in problems), problems)
        rec = build_record(self.dumps, self.item, "2026-13-45T99:00:00Z")
        self.assertTrue(record_problems(rec, self.dumps, self.v))

    def test_checksum_verification_matches_and_mismatches(self) -> None:
        provider, raw = load_fixture(self.root)
        pkg = next(i for i in raw if i["kind"] == "package")
        fields = {
            k: Value(v["value"], v["origin"], v["method"], v["source_field"])
            for k, v in pkg["fields"].items()
        }
        rec = build_record(
            provider, Item(pkg["item_id"], None, pkg["url"], fields), "2026-10-20T00:00:00Z"
        )
        good = self.root / "synthetic.bin"
        good.write_bytes(SYNTHETIC_BYTES)
        verified = verify_file(rec, good)
        self.assertEqual(verified["validation_status"], "checksum_verified")
        self.assertEqual(verified["provenance"]["sha256"]["origin"], "computed")
        self.assertEqual(record_problems(verified, provider, self.v), [])
        self.assertEqual(rec["validation_status"], "unverified")  # the input is not modified
        bad = self.root / "tampered.bin"
        bad.write_bytes(SYNTHETIC_BYTES.upper())  # same size, different content
        with self.assertRaisesRegex(ValidationError, "does not match"):
            verify_file(rec, bad)
        short = self.root / "short.bin"
        short.write_bytes(b"x")
        with self.assertRaisesRegex(ValidationError, "size"):
            verify_file(rec, short)
        no_sum = build_record(self.dumps, self.item, "2026-10-20T00:00:00Z")
        with self.assertRaisesRegex(ValidationError, "no SHA-256"):
            verify_file(no_sum, good)

    def test_provider_wrapper_reads_limits(self) -> None:
        p = Provider(self.provider(self.registry(), "android_dumps_gitlab"))
        self.assertEqual(p.limits.max_requests, 40)
        self.assertEqual(p.strategy, "gitlab_group_branches")
