import json

from afid import updates
from afid.catalog import Store
from afid.catalog.validate import validate
from afid.cli import main
from afid.utils import jsonio
from tests.conftest import zip_tree


def test_discovery_write_then_rerun_is_unchanged(repo):
    first = updates.check(repo, provider="lineageos_wiki", write=True)
    assert {c.change for c in first.changes} == {"added"}
    assert first.written
    snap = repo.database / "sources/lineageos_wiki.json"
    before = snap.read_bytes()
    second = updates.check(repo, provider="lineageos_wiki", write=True)
    assert [c for c in second.changes if c.change != "unverified"] == []
    assert second.written == [] and snap.read_bytes() == before
    assert validate(repo.database, repo.schemas_dir, repo.brand_ids).errors == []


def test_provider_failure_keeps_data(repo, monkeypatch):
    updates.check(repo, provider="lineageos_wiki", write=True)
    files = {p: p.read_bytes() for p in repo.database.rglob("*.json")}
    monkeypatch.setenv("AFID_LINEAGE_WIKI_DIR", "/nonexistent")
    out = updates.check(repo, provider="lineageos_wiki", write=True)
    assert out.failed and out.changes[0].change == "unavailable"
    assert {p: p.read_bytes() for p in repo.database.rglob("*.json")} == files


def test_changed_and_removed_items_detected(repo, tmp_path, monkeypatch):
    import shutil

    from tests.conftest import FIXTURES

    wiki = tmp_path / "wiki"
    shutil.copytree(FIXTURES / "lineage_wiki", wiki)
    monkeypatch.setenv("AFID_LINEAGE_WIKI_DIR", str(wiki))
    (wiki / "_data/devices/broken.yml").unlink()  # make listing complete (status ok)
    updates.check(repo, provider="lineageos_wiki", write=True)
    (wiki / "_data/devices/fixpoco.yml").unlink()
    f = wiki / "_data/devices/fixpix.yml"
    f.write_text(f.read_text().replace("GFX02", "GFX03"))
    out = updates.check(repo, provider="lineageos_wiki")
    kinds = {(c.change, c.record_id) for c in out.changes}
    assert ("changed", "fixpix") in kinds and ("removed_from_source", "fixpoco") in kinds


def run(capsys, *args):
    code = main(["--json", *args])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else None)


def test_cli_exit_codes_and_outputs(repo, capsys, tmp_path, tree):
    assert run(capsys, "version")[0] == 0
    assert run(capsys, "providers", "list")[1][0]["id"] == "google_pixel"
    assert run(capsys, "providers", "test")[0] == 0
    code, out = run(capsys, "devices", "show", "nope_x")
    assert code == 10 and out["error"] == "NotFoundError"
    assert run(capsys, "database", "validate")[0] == 0
    code, out = run(
        capsys,
        "ingest",
        "--local",
        str(zip_tree(tree, tmp_path / "f.zip")),
        "--provider",
        "google_pixel",
        "--dry-run",
    )
    assert code == 0 and out["status"] == "dry_run" and out["written"] == []
    assert not list(Store(repo.database).device_files())
    code, out = run(
        capsys, "ingest", "--local", str(tmp_path / "f.zip"), "--provider", "google_pixel"
    )
    assert code == 0 and out["status"] == "cataloged"
    assert run(capsys, "database", "index", "--check")[0] == 3  # stale until indexed
    assert run(capsys, "database", "index")[0] == 0
    assert run(capsys, "database", "validate", "--check-index")[0] == 0
    assert run(capsys, "devices", "list")[1][0]["device_id"] == "google_pixel_fixturecode"
    code, out = run(capsys, "firmware", "inspect", "google_pixel_fixturecode__FIX1.230101.001-1")
    assert code == 0 and out["components_by_category"]["thermal_hal"] >= 2
    code, out = run(capsys, "database", "stats")
    assert out["firmware_builds"] == 1
    assert run(capsys, "dependencies", "build")[0] == 0
    assert run(capsys, "report", "--format", "json")[0] == 0
    assert run(capsys, "policy", "check")[0] == 0
    assert run(capsys, "ingest", "--source", "nothing:here")[0] == 10
    assert run(capsys, "cache", "clean")[0] == 0
    code, out = run(capsys, "scan", "--input", str(tree))
    assert code == 0 and out["files"] > 10
    assert run(capsys, "classify", "--input", str(tmp_path / "missing"))[0] == 10


def test_cli_validate_fails_on_invalid_record(repo, capsys):
    p = repo.database / "devices/xiaomi/bad/device.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"schema_version": "1.0"}))
    code, out = run(capsys, "database", "validate")
    assert code == 3 and any("schema" in e for e in out["errors"])


def test_cli_markdown_report(repo, capsys):
    assert main(["report", "--format", "markdown"]) == 0
    assert "# AFID catalog report" in capsys.readouterr().out


def test_candidates_are_unverified_licensed_and_not_devices(repo, capsys):
    updates.check(repo, provider="lineageos_wiki", write=True)
    staged = [jsonio.load(p) for p in Store(repo.database).staging_files()]
    assert len(staged) == 4
    for c in staged:
        assert c["codename_status"] == "community_reported"
        assert c["verification"]["status"] == "unverified"
        assert c["verification"]["outstanding_requirements"]
        assert c["firmware_payload_ingested"] is False
        assert c["distribution_status"] == "metadata_only"
        assert c["license"]["spdx"] == "CC-BY-SA-3.0" and c["license"]["share_alike"]
        assert "LineageOS" in c["license"]["attribution"]
        assert c["source"]["provider_id"] == "lineageos_wiki"
        assert c["source"]["source_type"] == "community_repository"
        assert len(c["source"]["revision"]) == 40 and c["source"]["url"]
    from afid.catalog import index as catalog_index

    _, stats, _ = catalog_index.build(Store(repo.database), repo.brand_ids)
    assert stats["devices"] == 0 and stats["staging_candidates"] == stats["staging_unverified"] == 4
    assert stats["staging_by_brand"] == {"google_pixel": 1, "poco": 1, "redmi": 2}
    assert all(b["devices"] == 0 for b in stats["coverage_by_brand"].values())
    assert run(capsys, "policy", "check")[0] == 0


def test_policy_rejects_tampered_candidates(repo, capsys):
    updates.check(repo, provider="lineageos_wiki", write=True)
    p = next(Store(repo.database).staging_files())
    c = jsonio.load(p)
    c["license"]["attribution"] = None
    p.write_text(json.dumps(c))
    code, out = run(capsys, "policy", "check")
    assert code == 9 and any("attribution" in x for x in out["problems"])


def test_registry_requires_license_evidence(repo):
    from afid.providers import registry

    e = next(x for x in registry.entries(repo) if x["id"] == "lineageos_wiki")
    bad = {**e, "data_license": {**e["data_license"], "attribution": None}}
    assert any("attribution" in p for p in registry.self_test(repo, bad))
    bad = {**e, "data_license": {**e["data_license"], "evidence_urls": []}}
    assert any("evidence_urls" in p for p in registry.self_test(repo, bad))


def test_index_marker_is_never_duplicated(repo, monkeypatch):
    """Regression: a partial run used to keep the old "_index" item and insert a new one, so
    the snapshot flapped between runs and every scheduled check opened a pull request."""
    from afid.providers.lineageos_wiki import LineageWikiProvider

    monkeypatch.setattr(LineageWikiProvider, "_head", staticmethod(lambda path: "a" * 40))
    updates.check(repo, provider="lineageos_wiki", write=True)  # fixture has a broken file
    snap = repo.database / "sources/lineageos_wiki.json"
    assert jsonio.load(snap)["status"] == "partial"
    second_run = updates.check(repo, provider="lineageos_wiki", write=True)
    ids = [i["item_id"] for i in jsonio.load(snap)["items"]]
    assert ids.count("_index") == 1
    assert second_run.written == []  # nothing but a check happened: no file change, no PR
