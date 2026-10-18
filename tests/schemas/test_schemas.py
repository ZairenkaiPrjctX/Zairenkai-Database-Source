import glob
import json
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
        "techno",
        "x",
        [
            {
                "evidence_type": "official_source",
                "source": "s",
                "retrieved_at": "2026-10-18T00:00:00Z",
            }
        ],
    )
    assert list(v["device"].iter_errors(dev))  # "techno" is an alias, not a brand id
    fw = models.new_firmware("xiaomi_x", "B1", "xiaomi", "user_supplied_local_firmware")
    fw["source"]["archive_sha256"] = "not-a-sha"
    fw["distribution_status"] = "free"
    assert len(list(v["firmware"].iter_errors(fw))) >= 2


@pytest.mark.parametrize("path", WORKFLOWS)
def test_workflows_are_valid_and_least_privilege(path):
    doc = yaml.safe_load(Path(path).read_text())
    assert doc["permissions"] == {"contents": "read"}
    assert "concurrency" in doc
    for job in doc["jobs"].values():
        assert "timeout-minutes" in job
        for step in job["steps"]:
            uses = step.get("uses", "")
            assert not uses or uses.startswith("./") or len(uses.split("@")[1]) == 40
        if "permissions" in job:  # write access only in PR-proposing jobs
            assert set(job["permissions"]) <= {"contents", "pull-requests", "actions"}
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
    }


def test_brand_registry_has_exactly_nine_brands():
    brands = yaml.safe_load((REPO / "config/brands.yml").read_text())["brands"]
    assert [b["brand_id"] for b in brands] == [
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
