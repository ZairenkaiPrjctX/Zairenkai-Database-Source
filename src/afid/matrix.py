"""Bounded, deterministic work planning for GitHub Actions matrices.

The planner reads discovery snapshots (database/sources/), the catalog's source refs and
the ingestion state (database/state/) and decides, per item, whether it still needs work.
Eligible items are ordered by (provider, item_id) so every run plans the same thing for the
same inputs, then cut into batches of at most `batch_size` (never above GitHub's 256-job
matrix limit or MAX_ITEMS_PER_RUN). Each matrix entry carries a stable id derived from
provider, item and revision, used for artifact names; one failing entry never affects the
others (fail-fast is off in the workflows).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from afid import resources
from afid.catalog import Store
from afid.config import Config
from afid.errors import ValidationError
from afid.providers import registry
from afid.reconcile import FINAL, load_state
from afid.utils import jsonio
from afid.utils.timeutil import utc_now

GITHUB_MATRIX_LIMIT = 256
MODES = ("metadata-only", "selected-item", "eligible-batch", "full-eligible-catalog")


def entry_id(provider_id: str, item_id: str, revision: str | None) -> str:
    raw = f"{provider_id}\n{item_id}\n{revision or ''}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class ItemStatus:
    provider_id: str
    item_id: str
    revision: str | None
    status: str
    eligible: bool


def item_statuses(cfg: Config, store: Store, providers: list[str]) -> list[ItemStatus]:
    retry_limit = int(resources.limits(cfg)["RETRY_LIMIT"])
    refs: set[tuple[str, str, str | None]] = set()
    for fw in store.firmware():
        for r in fw.get("source_refs", []):
            refs.add((r["provider_id"], r["item_id"], r.get("revision")))
    out: list[ItemStatus] = []
    for pid in sorted(providers):
        snap = store.source_path(pid)
        if not snap.exists():
            continue
        state = load_state(store, pid)["items"]
        for it in jsonio.load(snap)["items"]:
            if it.get("kind") != "firmware":
                continue
            iid, rev = it["item_id"], it["revision"]
            st = state.get(iid, {})
            same = st.get("revision") == rev
            if (pid, iid, rev) in refs:
                status, ok = "unchanged", False
            elif same and st.get("status") in FINAL:
                status, ok = str(st["status"]), False
            elif same and st.get("status") == "failed":
                exhausted = bool(st.get("exhausted")) or int(st.get("attempts", 0)) >= retry_limit
                status, ok = "failed", not exhausted
            else:
                status, ok = "discovered", True
            out.append(ItemStatus(pid, iid, rev, status, ok))
    return out


def plan(
    cfg: Config,
    mode: str,
    providers: list[str] | None = None,
    items: list[str] | None = None,
    batch_size: int | None = None,
    batch_index: int = 0,
    store: Store | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValidationError(f"unknown mode '{mode}' (one of {', '.join(MODES)})")
    store = store or Store(cfg.database)
    dump_providers = [
        e["id"] for e in registry.entries(cfg) if e["capabilities"].get("discover_firmware")
    ]
    chosen = providers or dump_providers
    unknown = sorted(set(chosen) - set(dump_providers))
    if unknown:
        raise ValidationError(f"not firmware-item providers: {', '.join(unknown)}")
    lim = resources.limits(cfg)
    cap = min(GITHUB_MATRIX_LIMIT, int(lim["MAX_ITEMS_PER_RUN"]))
    size = min(cap, batch_size) if batch_size else cap
    if size < 1:
        raise ValidationError("batch size must be at least 1")

    statuses = item_statuses(cfg, store, chosen)
    summary: dict[str, int] = {}
    for s in statuses:
        summary[s.status] = summary.get(s.status, 0) + 1
    if mode == "metadata-only":
        work: list[ItemStatus] = []
    elif mode == "selected-item":
        wanted = set(items or [])
        if not wanted:
            raise ValidationError("selected-item mode needs at least one --item")
        work = [s for s in statuses if s.item_id in wanted]
        missing = wanted - {s.item_id for s in work}
        if missing:
            raise ValidationError(f"items not in any discovery snapshot: {sorted(missing)}")
    else:
        work = [s for s in statuses if s.eligible]
    work.sort(key=lambda s: (s.provider_id, s.item_id))
    batches = [work[i : i + size] for i in range(0, len(work), size)] or [[]]
    if mode == "eligible-batch":
        batches = batches[:1]
    if not 0 <= batch_index < len(batches):
        raise ValidationError(f"batch index {batch_index} out of range (0..{len(batches) - 1})")
    include = [
        {
            "id": entry_id(s.provider_id, s.item_id, s.revision),
            "provider": s.provider_id,
            "item": s.item_id,
            "revision": s.revision,
            "status": s.status,
        }
        for s in batches[batch_index]
    ]
    return {
        "schema_version": "1.0",
        "kind": "matrix_plan",
        "generated_at": utc_now(),
        "mode": mode,
        "providers": sorted(chosen),
        "summary": dict(sorted(summary.items())),
        "eligible": sum(1 for s in statuses if s.eligible),
        "batch_size": size,
        "batch_index": batch_index,
        "batch_count": len(batches) if work else 0,
        "matrix": {"include": include},
    }
