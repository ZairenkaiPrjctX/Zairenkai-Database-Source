"""Matrix planner boundaries, determinism, statuses, retry state and delta hardening."""

from __future__ import annotations

import json

import pytest

from afid import matrix, reconcile
from afid.catalog import Store
from afid.errors import ValidationError
from afid.providers.base import SourceItem
from afid.utils import jsonio


def _snapshot(cfg, provider, n):
    items = [
        SourceItem(f"brand/dev{i:04d}@b", f"{i:040x}", None, {"project_id": i}).as_snapshot()
        for i in range(n)
    ]
    jsonio.write_if_changed(
        Store(cfg.database).source_path(provider),
        {
            "schema_version": "1.0",
            "provider_id": provider,
            "status": "ok",
            "checked_at": "2026-10-19T00:00:00Z",
            "items": items,
            "errors": [],
        },
    )


def test_batches_never_exceed_github_limit(repo, monkeypatch):
    monkeypatch.setenv("AFID_MAX_ITEMS_PER_RUN", "1000")  # clamped to the hard cap 256
    _snapshot(repo, "android_dumps_gitlab", 300)
    p = matrix.plan(repo, "full-eligible-catalog", batch_size=500)
    assert p["batch_size"] == 256 and p["batch_count"] == 2
    assert len(p["matrix"]["include"]) == 256
    last = matrix.plan(repo, "full-eligible-catalog", batch_size=500, batch_index=1)
    assert len(last["matrix"]["include"]) == 44
    with pytest.raises(ValidationError, match="out of range"):
        matrix.plan(repo, "full-eligible-catalog", batch_index=5)


def test_plan_is_deterministic_and_ids_are_stable(repo):
    _snapshot(repo, "tadiphone_dumps", 30)
    a = matrix.plan(repo, "eligible-batch")
    b = matrix.plan(repo, "eligible-batch")
    assert a["matrix"] == b["matrix"] and len(a["matrix"]["include"]) == 20  # MAX_ITEMS_PER_RUN
    ids = [e["id"] for e in a["matrix"]["include"]]
    assert len(set(ids)) == len(ids) and all(len(i) == 16 for i in ids)
    assert [e["item"] for e in a["matrix"]["include"]] == sorted(
        e["item"] for e in a["matrix"]["include"]
    )


def test_modes(repo):
    _snapshot(repo, "android_dumps_gitlab", 3)
    assert matrix.plan(repo, "metadata-only")["matrix"]["include"] == []
    sel = matrix.plan(repo, "selected-item", items=["brand/dev0001@b"])
    assert [e["item"] for e in sel["matrix"]["include"]] == ["brand/dev0001@b"]
    with pytest.raises(ValidationError, match="not in any discovery snapshot"):
        matrix.plan(repo, "selected-item", items=["nope"])
    with pytest.raises(ValidationError, match="not firmware-item providers"):
        matrix.plan(repo, "eligible-batch", providers=["lineageos_wiki"])
    empty = matrix.plan(repo, "eligible-batch", providers=["tadiphone_dumps"])
    assert empty["batch_count"] == 0 and empty["matrix"]["include"] == []


def test_failed_items_retry_until_exhausted_and_new_revision_resets(repo):
    _snapshot(repo, "android_dumps_gitlab", 2)
    store = Store(repo.database)
    item, rev = "brand/dev0000@b", f"{0:040x}"
    report = {
        "provider_id": "android_dumps_gitlab",
        "item_id": item,
        "revision": rev,
        "status": "failed",
        "error": "boom",
    }
    for attempt in range(1, 4):
        reconcile.record_item(store, report, retry_limit=3)
        statuses = {
            s.item_id: s for s in matrix.item_statuses(repo, store, ["android_dumps_gitlab"])
        }
        assert statuses[item].status == "failed"
        assert statuses[item].eligible is (attempt < 3)
    reconcile.record_item(store, {**report, "revision": "f" * 40}, retry_limit=3)
    state = jsonio.load(reconcile.state_path(store, "android_dumps_gitlab"))
    assert state["items"][item]["attempts"] == 1 and not state["items"][item]["exhausted"]
    reconcile.record_item(
        store,
        {**report, "item_id": "brand/dev0001@b", "revision": f"{1:040x}", "status": "unresolved"},
        3,
    )
    statuses = {s.item_id: s for s in matrix.item_statuses(repo, store, ["android_dumps_gitlab"])}
    assert statuses["brand/dev0001@b"].status == "unresolved"
    assert not statuses["brand/dev0001@b"].eligible


def test_reconcile_rejects_tampered_or_foreign_deltas(repo, tmp_path):
    delta = tmp_path / "d" / "database"
    dev = {"schema_version": "1.0", "device_id": "xiaomi_other"}  # invalid device record
    jsonio.write_if_changed(delta / "devices" / "xiaomi" / "x" / "device.json", dev)
    (tmp_path / "d" / reconcile.REPORT).write_text(
        json.dumps({"provider_id": "not_a_provider", "item_id": "x", "status": "analyzed"})
    )
    out = reconcile.reconcile(repo, [tmp_path / "d"], Store(repo.database))
    assert out.rejected and out.merged == [] and out.items == {}
    assert not reconcile.state_path(Store(repo.database), "not_a_provider").exists()
