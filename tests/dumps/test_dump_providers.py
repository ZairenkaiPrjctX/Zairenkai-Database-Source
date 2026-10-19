"""Dump providers end to end against fake GitLab hosts: listing, pagination, incremental
discovery, rate limits, remote analysis, mirror dedup, conflicts, budgets."""

from __future__ import annotations

import json

import pytest

from afid import reconcile, updates
from afid.catalog import Store
from afid.catalog.validate import validate
from afid.errors import ProviderError
from afid.providers import registry
from afid.remote import RemoteAnalyzer, normalize
from afid.utils import jsonio
from tests.dumps.conftest import GL, LFS, TAD, dump_tree

BRANCH = "fixturecode-user-16-FIX1.230101.001-1-release-keys"
C1 = "1" * 40
C2 = "2" * 40


def _discover(cfg, provider):
    out = updates.check(cfg, provider, write=True)
    assert not out.failed, out.provider_status
    return out


def _analyze(cfg, provider, item, tmp_path, name):
    delta = tmp_path / "deltas" / name
    rep = RemoteAnalyzer(cfg, provider).analyze(item, Store(delta / "database"))
    delta.mkdir(parents=True, exist_ok=True)
    (delta / reconcile.REPORT).write_text(json.dumps(rep))
    return rep, delta


def test_listing_pagination_items_and_empty_projects(dumps_repo, hosts, tmp_path):
    gl = hosts[GL]
    tree = dump_tree(tmp_path / "t")
    gl.add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, tree)
    gl.add_dump(1, "Android-Dumps/google/fixturecode", "second-build", C2, tree)
    gl.add_dump(2, "Android-Dumps/alps/thing", "b", "3" * 40, tree)
    from tests.dumps.fake_gitlab import Project

    gl.projects.append(Project(3, "Android-Dumps/alps/empty", default_branch=None))
    res = registry.get(dumps_repo, "android_dumps_gitlab").discover_firmware()
    assert res.status == "ok" and res.skipped == 1
    assert [i.item_id for i in res.items] == [
        "alps/thing@b",
        f"google/fixturecode@{BRANCH}",
        "google/fixturecode@second-build",
    ]
    item = res.items[1]
    assert item.revision == C1 and item.metadata["project_id"] == 1
    assert item.metadata["namespace_hint"] == "google"  # a hint, never identity
    assert sum("groups/13303221/projects" in u for u in gl.requests) == 2  # 3 projects, 2/page


def test_incremental_discovery_skips_unchanged_projects(dumps_repo, hosts, tmp_path):
    gl = hosts[GL]
    tree = dump_tree(tmp_path / "t")
    gl.add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, tree)
    gl.add_dump(2, "Android-Dumps/google/other", "b", C2, tree)
    from tests.dumps.fake_gitlab import Project

    gl.projects.append(Project(5, "Android-Dumps/google/nobranches"))  # default branch, none listed
    _discover(dumps_repo, "android_dumps_gitlab")
    gl.requests.clear()
    gl.projects[1].branches["b"] = "4" * 40
    gl.projects[1].last_activity_at = "2026-10-02T00:00:00.000Z"
    out = updates.check(dumps_repo, "android_dumps_gitlab", write=True)
    branch_calls = [u for u in gl.requests if "/branches" in u]
    assert branch_calls and all("/projects/2/" in u for u in branch_calls)
    assert [c.change for c in out.changes] == ["changed"]
    # Same listing again: nothing changes, nothing is written (no empty PR).
    again = updates.check(dumps_repo, "android_dumps_gitlab", write=True)
    assert again.changes == [] and again.written == []


def test_truncated_listing_is_a_failure_and_keeps_snapshot(dumps_repo, hosts, tmp_path):
    gl = hosts[GL]
    gl.add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, dump_tree(tmp_path / "t"))
    _discover(dumps_repo, "android_dumps_gitlab")
    snap = Store(dumps_repo.database).source_path("android_dumps_gitlab")
    before = snap.read_text()
    prov = registry.get(dumps_repo, "android_dumps_gitlab")
    prov.settings["min_projects"] = 5
    with pytest.raises(ProviderError, match="expected at"):
        prov.discover_firmware()
    gl.projects.clear()  # the source suddenly lists nothing
    out = updates.check(dumps_repo, "android_dumps_gitlab", write=True)
    assert out.failed and snap.read_text() == before


def test_rate_limit_and_retry_after(dumps_repo, hosts, tmp_path, monkeypatch):
    from afid.download import HttpClient

    slept = []
    monkeypatch.setattr(HttpClient, "sleep", staticmethod(slept.append))
    gl = hosts[GL]
    gl.add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, dump_tree(tmp_path / "t"))
    gl.rate_limit_remaining = 1
    gl.fail_once["/branches"] = 429
    res = registry.get(dumps_repo, "android_dumps_gitlab").discover_firmware()
    assert len(res.items) == 1
    assert 7.0 in slept  # Retry-After honoured
    assert any(s >= 1.0 for s in slept if s != 7.0)  # waited for the rate-limit window


def test_normalize_system_as_root_and_ignores_non_partitions():
    sel = normalize(
        [
            "system/system/build.prop",
            "system/init.rc",
            "vendor/build.prop",
            "README.md",
            "aosp-device-tree/x",
            "system/system/lib64/libx.so",
        ],
        ["system", "vendor"],
    )
    assert sel.system_as_root
    assert sel.mapping == {
        "system/system/build.prop": "system/build.prop",
        "vendor/build.prop": "vendor/build.prop",
        "system/system/lib64/libx.so": "system/lib64/libx.so",
    }


def test_remote_analysis_catalogs_verified_device(dumps_repo, hosts, tmp_path):
    gl = hosts[GL]
    tree = dump_tree(tmp_path / "t")
    gl.add_dump(
        1,
        "Android-Dumps/google/fixturecode",
        BRANCH,
        C1,
        tree,
        {"vendor/lib64/hw/thermal.big.so": LFS},
    )
    _discover(dumps_repo, "android_dumps_gitlab")
    rep, delta = _analyze(
        dumps_repo, "android_dumps_gitlab", f"google/fixturecode@{BRANCH}", tmp_path, "a"
    )
    assert rep["status"] == "analyzed", rep
    assert rep["fetch"]["lfs_pointers_count"] == 1
    assert all(f"ref={C1}" in u for u in gl.requests if "/files/" in u)  # pinned to the commit
    main = Store(dumps_repo.database)
    out = reconcile.reconcile(dumps_repo, [delta], main)
    assert out.merged == ["google_pixel_fixturecode__FIX1.230101.001-1"] and not out.rejected
    dev = main.find_device("google_pixel_fixturecode")
    assert dev["sources"][0]["evidence_type"] == "dump_build_prop"
    assert f"/-/blob/{C1}/vendor/build.prop" in dev["sources"][0]["url"]
    _, fw = main.find_firmware("google_pixel_fixturecode__FIX1.230101.001-1")
    assert fw["distribution_status"] == "unknown"
    assert fw["source"]["source_type"] == "community_firmware_dump"
    assert [(r["provider_id"], r["revision"]) for r in fw["source_refs"]] == [
        ("android_dumps_gitlab", C1)
    ]
    comps = main.components_of(
        main.firmware_dir("google_pixel", "fixturecode", "FIX1.230101.001-1") / "firmware.json"
    )
    paths = {f"{c['partition']}/{c['path']}" for c in comps}
    assert "vendor/bin/hw/android.hardware.thermal-service.fixture" in paths
    assert "system/build.prop" in paths  # system/system/build.prop normalized
    assert not any(p.startswith(("aosp-device-tree", "system/init.rc")) for p in paths)
    assert all(c["distribution_status"] == "unknown" for c in comps)
    state = jsonio.load(reconcile.state_path(main, "android_dumps_gitlab"))
    assert state["items"][f"google/fixturecode@{BRANCH}"]["status"] == "analyzed"
    from afid.catalog import index

    index.write(main, dumps_repo.brand_ids)
    assert validate(dumps_repo.database, dumps_repo.schemas_dir, dumps_repo.brand_ids).errors == []


def test_same_build_on_two_hosts_is_one_firmware(dumps_repo, hosts, tmp_path):
    tree = dump_tree(tmp_path / "t")
    hosts[GL].add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, tree)
    hosts[TAD].add_dump(9, "dumps/google/fixturecode", BRANCH, C2, tree)
    _discover(dumps_repo, "android_dumps_gitlab")
    _discover(dumps_repo, "tadiphone_dumps")
    _, d1 = _analyze(
        dumps_repo, "android_dumps_gitlab", f"google/fixturecode@{BRANCH}", tmp_path, "gl"
    )
    r2, d2 = _analyze(
        dumps_repo, "tadiphone_dumps", f"google/fixturecode@{BRANCH}", tmp_path, "tad"
    )
    main = Store(dumps_repo.database)
    out = reconcile.reconcile(dumps_repo, [d1, d2], main)
    assert out.refs_added == ["google_pixel_fixturecode__FIX1.230101.001-1"] and not out.conflicts
    _, fw = main.find_firmware("google_pixel_fixturecode__FIX1.230101.001-1")
    refs = {r["provider_id"]: r["content_marker"] for r in fw["source_refs"]}
    assert set(refs) == {"android_dumps_gitlab", "tadiphone_dumps"}
    assert len(set(refs.values())) == 1  # identical vendor/build.prop git blob id
    assert reconcile.reconcile(dumps_repo, [d1, d2], main).written == []  # idempotent


def test_conflicting_dump_is_quarantined(dumps_repo, hosts, tmp_path):
    hosts[GL].add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, dump_tree(tmp_path / "a"))
    hosts[TAD].add_dump(
        9,
        "dumps/google/fixturecode",
        BRANCH,
        C2,
        dump_tree(tmp_path / "b", fingerprint_suffix="-modified"),
    )
    _discover(dumps_repo, "android_dumps_gitlab")
    _discover(dumps_repo, "tadiphone_dumps")
    _, d1 = _analyze(
        dumps_repo, "android_dumps_gitlab", f"google/fixturecode@{BRANCH}", tmp_path, "gl"
    )
    _, d2 = _analyze(dumps_repo, "tadiphone_dumps", f"google/fixturecode@{BRANCH}", tmp_path, "tad")
    main = Store(dumps_repo.database)
    reconcile.reconcile(dumps_repo, [d1], main)
    before = (
        main.firmware_dir("google_pixel", "fixturecode", "FIX1.230101.001-1") / "firmware.json"
    ).read_text()
    out = reconcile.reconcile(dumps_repo, [d2], main)
    assert out.conflicts and "fingerprint" in out.conflicts[0]["reason"]
    assert (
        main.firmware_dir("google_pixel", "fixturecode", "FIX1.230101.001-1") / "firmware.json"
    ).read_text() == before
    staged = [jsonio.load(p) for p in main.staging_files()]
    assert [
        c["codename_status"] for c in staged if c["source"]["provider_id"] == "tadiphone_dumps"
    ] == ["conflict"]


def test_unknown_brand_stays_in_staging(dumps_repo, hosts, tmp_path):
    hosts[GL].add_dump(
        2, "Android-Dumps/alps/fixturecode", "b", C1, dump_tree(tmp_path / "t", brand="alps")
    )
    _discover(dumps_repo, "android_dumps_gitlab")
    rep, delta = _analyze(dumps_repo, "android_dumps_gitlab", "alps/fixturecode@b", tmp_path, "x")
    assert rep["status"] == "unresolved" and "does not map" in rep["detail"]
    main = Store(dumps_repo.database)
    reconcile.reconcile(dumps_repo, [delta], main)
    assert list(main.device_files()) == []
    assert [jsonio.load(p)["codename_status"] for p in main.staging_files()] == ["unresolved"]


def test_fetch_budget_keeps_build_prop_first(dumps_repo, hosts, tmp_path, monkeypatch):
    monkeypatch.setenv("AFID_MAX_FETCH_FILES", "4")
    hosts[GL].add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, dump_tree(tmp_path / "t"))
    _discover(dumps_repo, "android_dumps_gitlab")
    rep, _ = _analyze(
        dumps_repo, "android_dumps_gitlab", f"google/fixturecode@{BRANCH}", tmp_path, "a"
    )
    assert rep["status"] == "analyzed"  # identity came from the first fetched file
    assert rep["fetch"]["fetched"] == 4 and rep["fetch"]["skipped_budget_count"] > 0


def test_analysis_failure_is_reported_not_raised(dumps_repo, hosts, tmp_path):
    hosts[GL].add_dump(1, "Android-Dumps/google/fixturecode", BRANCH, C1, dump_tree(tmp_path / "t"))
    _discover(dumps_repo, "android_dumps_gitlab")
    hosts[GL].projects[0].files.clear()  # the commit vanished upstream
    rep, delta = _analyze(
        dumps_repo, "android_dumps_gitlab", f"google/fixturecode@{BRANCH}", tmp_path, "a"
    )
    assert rep["status"] in ("failed", "unresolved")
