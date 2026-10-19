import glob
import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from afid import models
from afid.catalog.validate import load_validators
from tests.conftest import REPO

WORKFLOWS = sorted(glob.glob(str(REPO / ".github/workflows/*.yml")))


@pytest.mark.parametrize("path", sorted(glob.glob(str(REPO / "schemas/*.json"))))
def test_schemas_are_valid_draft_2020_12(path):
    Draft202012Validator.check_schema(json.loads(Path(path).read_text()))


def test_record_builders_match_schemas():
    v = load_validators(REPO / "schemas")
    dev = models.new_device(
        "redmi",
        "Mi439",
        [
            {
                "evidence_type": "firmware_build_prop",
                "source": "local_firmware",
                "retrieved_at": "2026-10-18T00:00:00Z",
            }
        ],
    )
    assert list(v["device"].iter_errors(dev)) == []
    fw = models.new_firmware(dev["device_id"], "V12.5.1.0", "redmi", "user_supplied_local_firmware")
    assert list(v["firmware"].iter_errors(fw)) == []
    assert dev["codename"] == "Mi439" and dev["codename_key"] == "mi439"


def test_invalid_records_rejected():
    v = load_validators(REPO / "schemas")
    dev = models.new_device("xiaomi", "x", [])
    assert list(v["device"].iter_errors(dev))  # no evidence -> invalid
    dev = models.new_device(
        "xiaomi",
        "x",
        [{"evidence_type": "guess", "source": "s", "retrieved_at": "2026-10-18T00:00:00Z"}],
    )
    assert list(v["device"].iter_errors(dev))
    dev = models.new_device(
        "Techno",
        "x",
        [
            {
                "evidence_type": "official_source",
                "source": "s",
                "retrieved_at": "2026-10-18T00:00:00Z",
            }
        ],
    )
    assert list(
        v["device"].iter_errors(dev)
    )  # brand ids are lowercase; the registry check is in the validator
    fw = models.new_firmware("xiaomi_x", "B1", "xiaomi", "user_supplied_local_firmware")
    fw["source"]["archive_sha256"] = "not-a-sha"
    fw["distribution_status"] = "free"
    assert len(list(v["firmware"].iter_errors(fw))) >= 2


@pytest.mark.parametrize("path", WORKFLOWS)
def test_workflows_are_valid_and_least_privilege(path):
    doc = yaml.safe_load(Path(path).read_text())
    assert doc["permissions"] == {"contents": "read"}
    assert "concurrency" in doc
    name = Path(path).name
    for job_name, job in doc["jobs"].items():
        if "uses" in job:  # reusable workflow call: local workflows only, no timeout allowed
            assert job["uses"].startswith("./.github/workflows/")
            continue
        assert "timeout-minutes" in job
        for step in job["steps"]:
            uses = step.get("uses", "")
            assert not uses or uses.startswith("./") or len(uses.split("@")[1]) == 40
        if "permissions" in job:  # write access only in PR-proposing and image-publishing jobs
            allowed = {"contents", "pull-requests", "actions"}
            if (name, job_name) == ("container-images.yml", "publish"):
                allowed = {"contents", "packages"}
            assert set(job["permissions"]) <= allowed
            assert all("run" not in s or "pull_request" not in s["run"] for s in job["steps"])


def test_required_workflows_exist():
    names = {p.rsplit("/", 1)[-1] for p in WORKFLOWS}
    assert names == {
        "validate.yml",
        "source-discovery.yml",
        "ingest-firmware.yml",
        "check-updates.yml",
        "refresh-catalog.yml",
        "security-audit.yml",
        "container-images.yml",
        "discover-dumps.yml",
        "plan-firmware-matrix.yml",
        "download-dumps.yml",
        "dump-and-analyze.yml",
        "analyze-components.yml",
        "reconcile-catalog.yml",
    }


def test_firmware_jobs_never_see_secrets_or_write_tokens():
    for name in (
        "analyze-components.yml",
        "dump-and-analyze.yml",
        "download-dumps.yml",
        "plan-firmware-matrix.yml",
    ):
        text = (REPO / ".github/workflows" / name).read_text()
        assert "secrets." not in text and "pull_request_target" not in text
    worker = yaml.safe_load((REPO / ".github/workflows/dump-and-analyze.yml").read_text())
    dump = worker["jobs"]["dump"]
    assert "permissions" not in dump  # read-only top-level token only
    run = next(s["run"] for s in dump["steps"] if s.get("name") == "Dump and ingest offline")
    for flag in ("--network none", "--cap-drop ALL", "no-new-privileges", "--read-only"):
        assert flag in run
    assert "docker.sock" not in run and "GH_TOKEN" not in run


def test_brand_registry_has_exactly_nine_core_brands():
    brands = yaml.safe_load((REPO / "config/brands.yml").read_text())["brands"]
    assert [b["brand_id"] for b in brands if b["scope"] == "core"] == [
        "samsung",
        "xiaomi",
        "poco",
        "redmi",
        "infinix",
        "oneplus",
        "tecno",
        "google_pixel",
        "nothing",
    ]
    tecno = next(b for b in brands if b["brand_id"] == "tecno")
    assert tecno["display_name"] == "TECNO" and "Techno" in tecno["aliases"]


def test_brand_registry_ids_and_aliases_are_unambiguous():
    brands = yaml.safe_load((REPO / "config/brands.yml").read_text())["brands"]
    assert {b["scope"] for b in brands} == {"core", "extended"}
    ids = [b["brand_id"] for b in brands]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_]{1,31}", i) for i in ids)
    owners: dict[str, set[str]] = {}
    for b in brands:
        for a in b["aliases"]:
            owners.setdefault(a.lower(), set()).add(b["brand_id"])
    # Only the Xiaomi family shares an alias, and model prefixes then decide (see resolve_brand).
    shared = {a: o for a, o in owners.items() if len(o) > 1}
    assert all(o <= {"xiaomi", "poco", "redmi"} for o in shared.values()), shared
