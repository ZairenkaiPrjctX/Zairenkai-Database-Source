"""The LineageOS source mirror copies only bounded, valid YAML with pinned provenance."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REPO

spec = importlib.util.spec_from_file_location(
    "mirror_lineageos_wiki", REPO / "tools" / "mirror_lineageos_wiki.py"
)
assert spec and spec.loader
mirror_tool = importlib.util.module_from_spec(spec)
sys.modules["mirror_lineageos_wiki"] = mirror_tool
spec.loader.exec_module(mirror_tool)


def make_upstream(tmp_path: Path, documents: dict[str, str]) -> Path:
    upstream = tmp_path / "upstream"
    data = upstream / "_data" / "devices"
    data.mkdir(parents=True)
    footer = upstream / "_includes" / "layout" / "footer.html"
    footer.parent.mkdir(parents=True)
    footer.write_text(
        '<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>\n',
        encoding="utf-8",
    )
    for name, content in documents.items():
        (data / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    subprocess.run(["git", "-C", str(upstream), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(upstream), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(upstream), "remote", "add", "origin", mirror_tool.UPSTREAM],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(upstream), "add", "_data/devices", "_includes/layout/footer.html"],
        check=True,
    )
    subprocess.run(["git", "-C", str(upstream), "commit", "-qm", "fixture"], check=True)
    return upstream


def documents(*names: str) -> dict[str, str]:
    return {
        f"{name}.yml": f"codename: {name}\nname: Device {name}\nvendor: Samsung\n" for name in names
    }


def test_mirror_copies_source_and_records_commit_and_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_tool, "MIN_FILES", 2)
    upstream = make_upstream(tmp_path, documents("one", "two"))
    output = tmp_path / "mirror"
    manifest = mirror_tool.mirror(upstream, output)

    assert manifest["source_revision"] == mirror_tool._head(upstream)
    assert manifest["license"] == "CC-BY-SA-3.0"
    assert (output / "devices/one.yml").read_text().startswith("codename: one")
    assert mirror_tool.check(output) == manifest
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])
    assert all(manifest["source_revision"] in entry["source_url"] for entry in manifest["files"])


def test_mirror_removes_only_stale_files_in_its_previous_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_tool, "MIN_FILES", 2)
    upstream = make_upstream(tmp_path, documents("one", "two"))
    output = tmp_path / "mirror"
    mirror_tool.mirror(upstream, output)
    (output / "ATTRIBUTION.md").write_text("attribution")
    (upstream / "_data/devices/two.yml").unlink()
    (upstream / "_data/devices/three.yml").write_text(
        "codename: three\nname: Device three\nvendor: Samsung\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(upstream), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(upstream), "commit", "-qm", "update"], check=True)

    manifest = mirror_tool.mirror(upstream, output)
    assert {entry["path"] for entry in manifest["files"]} == {"one.yml", "three.yml"}
    assert not (output / "devices/two.yml").exists()
    assert (output / "ATTRIBUTION.md").read_text() == "attribution"
    assert mirror_tool.check(output) == manifest


def test_malformed_or_partial_upstream_is_rejected_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_tool, "MIN_FILES", 2)
    upstream = make_upstream(
        tmp_path,
        {"one.yml": "codename: one\nname: One\nvendor: Samsung\n", "two.yml": "[]\n"},
    )
    output = tmp_path / "mirror"
    with pytest.raises(mirror_tool.MirrorError, match="required device identity"):
        mirror_tool.mirror(upstream, output)
    assert not output.exists()


def test_upstream_file_symlinks_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_tool, "MIN_FILES", 2)
    upstream = make_upstream(tmp_path, documents("one", "two"))
    device_dir = upstream / "_data/devices"
    (device_dir / "three.yml").symlink_to(device_dir / "one.yml")
    with pytest.raises(mirror_tool.MirrorError, match="unsafe upstream device filename"):
        mirror_tool.mirror(upstream, tmp_path / "mirror")


def test_check_detects_modified_mirror_data(tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_tool, "MIN_FILES", 2)
    upstream = make_upstream(tmp_path, documents("one", "two"))
    output = tmp_path / "mirror"
    mirror_tool.mirror(upstream, output)
    (output / "devices/one.yml").write_text("modified\n")
    with pytest.raises(mirror_tool.MirrorError, match="SHA-256 mismatch"):
        mirror_tool.check(output)


def test_manifest_source_revision_is_a_full_commit(tmp_path):
    output = tmp_path / "mirror"
    output.mkdir()
    (output / "devices").mkdir()
    (output / "manifest.json").write_text(
        '{"schema_version":1,"source_repository":"https://github.com/LineageOS/lineage_wiki",'
        '"license":"CC-BY-SA-3.0","source_revision":"main","files":[]}\n'
    )
    with pytest.raises(mirror_tool.MirrorError, match="immutable source revision"):
        mirror_tool.check(output)
