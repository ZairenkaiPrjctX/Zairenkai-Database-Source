import json
import shutil

import pytest

from afid.catalog import Store
from afid.catalog import index as catalog_index
from afid.catalog.validate import validate
from afid.errors import CorruptArchiveError, ValidationError
from afid.hashing import sha256_file
from afid.ingest import ingest_local
from afid.updates import history
from afid.utils import jsonio
from tests.conftest import build_tree, write, zip_tree


@pytest.fixture
def archive(tmp_path, tree):
    return zip_tree(tree, tmp_path / "fixturecode-fix1.230101.001-factory-0123abcd.zip")


def test_local_zip_ingest_end_to_end(repo, archive):
    res = ingest_local(repo, archive, "google_pixel", expected_sha256=sha256_file(archive))
    assert res.status == "cataloged"
    assert res.device_id == "google_pixel_fixturecode"
    assert res.firmware_id == "google_pixel_fixturecode__FIX1.230101.001-1"
    store = Store(repo.database)
    dev = store.find_device(res.device_id)
    assert dev["codename_status"] == "verified"
    assert {e["evidence_type"] for e in dev["sources"]} == {"firmware_build_prop"}
    path, fw = store.find_firmware(res.firmware_id)
    assert fw["android_release"] == "16" and fw["api_level"] == 36
    assert fw["source"]["official_checksum"]["matched"] is True
    assert fw["distribution_status"] == "user_supplied"
    text = json.dumps([jsonio.load(p) for p in sorted(repo.database.rglob("*.json"))])
    assert "MUST-NOT-BE-STORED" not in text  # serial number never stored
    assert path.parent.as_posix().endswith("firmware/google_pixel/fixturecode/FIX1.230101.001-1")
    assert (
        repo.database / "components/google_pixel/fixturecode/FIX1.230101.001-1/thermal_hal.json"
    ).exists()
    catalog_index.write(store, repo.brand_ids)
    result = validate(repo.database, repo.schemas_dir, repo.brand_ids)
    assert result.errors == [], result.errors
    stats = jsonio.load(repo.database / "statistics.json")
    assert stats["devices"] == 1 and stats["thermal_hal"] >= 2 and stats["power_config"] == 1
    assert stats["pending_license_review"] == stats["components"]  # nothing auto-publishable
    assert not (repo.cache / "work").exists() or not any((repo.cache / "work").iterdir())


def test_reingest_identical_writes_nothing(repo, archive, monkeypatch):
    ingest_local(repo, archive, "google_pixel")
    # Force a different clock on the second run: timestamps alone must not cause writes.
    import afid.ingest

    monkeypatch.setattr(afid.ingest, "utc_now", lambda: "2099-01-01T00:00:00Z")
    store = Store(repo.database)
    catalog_index.write(store, repo.brand_ids)
    before = {p: p.read_bytes() for p in repo.database.rglob("*.json")}
    res = ingest_local(repo, archive, "google_pixel")
    assert res.written == []
    assert catalog_index.write(store, repo.brand_ids) == []
    assert {p: p.read_bytes() for p in repo.database.rglob("*.json")} == before


def test_wrong_checksum_rejected(repo, archive):
    with pytest.raises(CorruptArchiveError):
        ingest_local(repo, archive, "google_pixel", expected_sha256="0" * 64)


def test_codename_contradiction_refused(repo, archive):
    with pytest.raises(ValidationError, match="contradicts"):
        ingest_local(repo, archive, "google_pixel", codename="othercode")


def test_directory_without_identity_goes_to_staging(repo, tmp_path):
    t = build_tree(tmp_path / "noprops", build_props=False)
    res = ingest_local(repo, t, "local_firmware", brand="xiaomi", codename="claimed")
    assert res.status == "staged" and "no device codename" in res.detail
    assert not list(Store(repo.database).device_files())
    (staged,) = list(Store(repo.database).staging_files())
    assert jsonio.load(staged)["codename_status"] == "unresolved"
    assert validate(repo.database, repo.schemas_dir, repo.brand_ids).errors == []


def test_staging_candidate_promoted_on_verified_ingest(repo, tmp_path):
    from afid.updates import check

    check(repo, provider="lineageos_wiki", write=True)
    assert any("fixpix" in p.name for p in Store(repo.database).staging_files())
    t = build_tree(tmp_path / "t")
    prop = t / "vendor/build.prop"
    prop.write_text(prop.read_text().replace("fixturecode", "fixpix"))
    res = ingest_local(repo, t, "google_pixel")
    dev = Store(repo.database).find_device("google_pixel_fixpix")
    assert "Pixel Fixture" in dev["product_names"] and "GFX01" in dev["model_numbers"]
    assert {"firmware_build_prop", "community_repository"} <= {
        e["evidence_type"] for e in dev["sources"]
    }
    assert not any("fixpix" in p.name for p in Store(repo.database).staging_files())
    assert any("promoted" in w for w in res.written)


def test_history_detects_changed_and_new_files(repo, tmp_path):
    t1 = build_tree(tmp_path / "b1")
    ingest_local(repo, t1, "google_pixel")
    t2 = tmp_path / "b2"
    shutil.copytree(t1, t2, symlinks=True)
    for f in (t2 / "vendor/build.prop", t2 / "system/build.prop"):
        f.write_text(
            f.read_text()
            .replace("FIX1.230101.001", "FIX2.230201.001")
            .replace("2026-09-05", "2026-10-05")
        )
    write(t2 / "vendor/etc/thermal_info_config.json", '{"Sensors": [{"Name": "new"}]}')
    write(t2 / "vendor/etc/thermal-extra.xml", "<thermal/>")
    ingest_local(repo, t2, "google_pixel")
    (rep,) = history(Store(repo.database), "google_pixel_fixturecode")
    kinds = {(c["change"], c["record_id"]) for c in rep["changes"]}
    assert ("checksum_changed", "vendor/etc/thermal_info_config.json") in kinds
    assert ("added", "vendor/etc/thermal-extra.xml") in kinds
    assert rep["from"].endswith("FIX1.230101.001-1") and rep["to"].endswith("FIX2.230201.001-1")


def test_validator_catches_broken_references(repo, archive):
    ingest_local(repo, archive, "google_pixel")
    fw_path = next(Store(repo.database).firmware_files())
    fw = jsonio.load(fw_path)
    fw["device_id"] = "google_pixel_ghost"
    fw_path.write_text(json.dumps(fw))
    dev_path = next(Store(repo.database).device_files())
    dev = jsonio.load(dev_path)
    dev["codename_key"] = "renamed"
    dev_path.write_text(json.dumps(dev))
    (repo.database / "devices/google_pixel/fixturecode/blob.so").write_bytes(b"\x7fELF")
    errors = "\n".join(validate(repo.database, repo.schemas_dir, repo.brand_ids).errors)
    assert "does not exist" in errors
    assert "must equal codename key" in errors
    assert "only JSON metadata" in errors
