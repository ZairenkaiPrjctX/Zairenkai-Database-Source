import json

from afid import updates
from afid.catalog import Store
from afid.catalog.validate import validate
from afid.cli import main
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
    code, out = run(capsys, "firmware", "inspect", "google_pixel_fixturecode__FIX1.230101.001")
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
