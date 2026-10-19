"""Remote-tree analysis of one community dump item, without downloading the firmware.

For a dump item (one branch of a dump repository, pinned to its commit SHA):
1. list the dump's files (all_files.txt, or the tree API);
2. map dump paths onto AFID's partition layout (system-as-root `system/system/X` becomes
   `system/X`; non-partition files such as README.md or generated device trees are ignored);
3. select build.prop files plus every path a classification rule could match;
4. fetch those files one by one, pinned to the commit, within MAX_FETCH_FILES /
   MAX_FETCH_BYTES; Git LFS pointers are recorded, never resolved;
5. follow DT_NEEDED of fetched vendor-side ELF files transitively and fetch those libraries
   while the budget lasts;
6. catalog the partial tree with afid.ingest, where identity comes only from the fetched
   build.prop (evidence type `dump_build_prop`) and files that were listed but not fetched
   still resolve dependency edges.

Fetched bytes are untrusted: they are written under a private work directory through
safe_join, parsed with bounds checks and never executed. Nothing is written back to the
source.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid import resources
from afid.catalog import Store
from afid.classification import Classifier
from afid.config import Config
from afid.errors import AfidError, NotFoundError, ValidationError
from afid.extraction.pipeline import Prepared
from afid.ingest import PROP_FILES, IngestResult, SourceContext, _catalog
from afid.parsers import elf
from afid.providers import registry
from afid.providers.dumps import GitLabDumpsProvider
from afid.providers.gitlab import is_lfs_pointer, lfs_pointer_size
from afid.providers.lineageos_wiki import git_blob_sha
from afid.scanning import FileEntry
from afid.utils import log
from afid.utils.paths import safe_join
from afid.utils.timeutil import utc_now

LOG = log.get("remote")
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 6
VENDOR_SIDE = ("vendor", "odm", "vendor_dlkm", "odm_dlkm")
LIB_DIRS = ("lib", "lib64", "lib/hw", "lib64/hw")
EXTRA_PROPS = ("system_ext/etc/build.prop", "product/etc/build.prop", "vendor/odm/etc/build.prop")


@dataclass
class Selection:
    """Dump path -> local (normalized) path for everything kept, in fetch priority order."""

    mapping: dict[str, str]
    order: list[str]
    system_as_root: bool


@dataclass
class FetchReport:
    listed: int = 0
    listing_source: str = ""
    selected: int = 0
    fetched: int = 0
    fetched_bytes: int = 0
    missing: list[str] = field(default_factory=list)
    lfs_pointers: list[str] = field(default_factory=list)
    skipped_budget: list[str] = field(default_factory=list)
    dependency_fetches: int = 0
    build_prop_blob: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = dict(vars(self))
        for k in ("missing", "lfs_pointers", "skipped_budget"):
            d[f"{k}_count"] = len(d[k])
            d[k] = d[k][:50]
        return d


def normalize(paths: list[str], partitions: list[str]) -> Selection:
    """Map dump paths to AFID's <partition>/<path> layout."""
    sar = "system/system/build.prop" in paths
    mapping: dict[str, str] = {}
    for p in paths:
        if sar and p.startswith("system/"):
            if not p.startswith("system/system/"):
                continue  # root filesystem of a system-as-root image: not a partition
            local = "system/" + p[len("system/system/") :]
        else:
            local = p
        if local.split("/", 1)[0] not in partitions or "/" not in local:
            continue
        mapping[p] = local
    return Selection(mapping, [], sar)


def priority(local: str, classifier: Classifier) -> tuple[int, float, str]:
    """Fetch order when the budget cannot cover every candidate: thermal/power-named files
    first, vendor-side partitions before system ones, and generic init/VINTF files (relevant
    only if their content mentions thermal/power) and unmatched HAL files last."""
    vendor = local.split("/", 1)[0] in VENDOR_SIDE
    rule = classifier.best_rule(local)
    conf = rule.confidence if rule else 0.0
    generic = rule is None or rule.category in ("init_script", "vintf_manifest")
    if classifier.relevant(local):
        tier = 1 if vendor else 2
    elif not generic:
        tier = 3 if vendor else 4
    elif rule is not None:
        tier = 5 if vendor else 6
    else:
        tier = 7
    return tier, -conf, local


def select(sel: Selection, classifier: Classifier) -> Selection:
    by_local = {v: k for k, v in sel.mapping.items()}
    props = [by_local[p] for p in (*PROP_FILES, *EXTRA_PROPS) if p in by_local]
    rest = sorted(
        (
            remote
            for remote, local in sel.mapping.items()
            if remote not in props and classifier.candidate(local)
        ),
        key=lambda r: priority(sel.mapping[r], classifier),
    )
    sel.order = props + rest
    return sel


class RemoteAnalyzer:
    def __init__(self, cfg: Config, provider_id: str, workdir: Path | None = None) -> None:
        self.cfg = cfg
        prov = registry.get(cfg, provider_id)
        if not isinstance(prov, GitLabDumpsProvider):
            raise ValidationError(f"provider '{provider_id}' has no remote dump trees")
        self.provider = prov
        self.provider_id = provider_id
        self.lim = resources.limits(cfg)
        self.classifier = Classifier(cfg.rules)
        self.workdir = workdir

    def item(self, store: Store, item_id: str) -> dict[str, Any]:
        items = store.source_items(self.provider_id)
        if not items:
            raise NotFoundError(
                f"no discovery snapshot for {self.provider_id}; run `afid discover "
                f"--provider {self.provider_id} --write` first"
            )
        for it in items:
            if it["item_id"] == item_id:
                return dict(it)
        raise NotFoundError(f"{self.provider_id}: item '{item_id}' not in the discovery snapshot")

    def fetch_tree(
        self, meta: dict[str, Any], tree: Path
    ) -> tuple[FetchReport, list[FileEntry], Selection]:
        rep = FetchReport()
        budget_files = int(self.lim["MAX_FETCH_FILES"])
        budget_bytes = int(self.lim["MAX_FETCH_BYTES"])
        resources.ensure_disk(
            tree.parent, budget_bytes, int(self.lim["DISK_RESERVE_BYTES"]), "remote fetch"
        )
        paths, rep.listing_source = self.provider.list_files(meta, MAX_FILE_BYTES)
        rep.listed = len(paths)
        sel = select(normalize(paths, self.cfg.settings["scan"]["partitions"]), self.classifier)
        rep.selected = len(sel.order)
        fetched: set[str] = set()

        def fetch(remote: str, share: float = 1.0) -> Path | None:
            """Fetch one file unless `share` of the budget is already used."""
            if rep.fetched >= budget_files * share or rep.fetched_bytes >= budget_bytes * share:
                if share == 1.0:
                    rep.skipped_budget.append(remote)
                return None
            cap = min(MAX_FILE_BYTES, budget_bytes - rep.fetched_bytes)
            try:
                data = self.provider.fetch_file(meta, remote, cap)
            except AfidError as exc:
                rep.missing.append(f"{remote}: {exc}"[:200])
                return None
            fetched.add(remote)
            if data is None:
                rep.missing.append(remote)
                return None
            rep.fetched += 1
            rep.fetched_bytes += len(data)
            if is_lfs_pointer(data):
                rep.lfs_pointers.append(f"{remote} (LFS object, {lfs_pointer_size(data)} bytes)")
                return None
            dest = safe_join(tree, sel.mapping[remote])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if (
                remote.endswith("/build.prop")
                and rep.build_prop_blob is None
                and sel.mapping[remote].startswith("vendor/")
            ):
                rep.build_prop_blob = git_blob_sha(data)
            return dest

        # Pass 1 uses at most 75% of the budget, leaving room for the libraries that the
        # fetched binaries need (pass 2); pass 3 spends what is left on the remaining files.
        for remote in sel.order:
            if (
                fetch(remote, 0.75) is None
                and remote not in fetched
                and (rep.fetched >= budget_files * 0.75 or rep.fetched_bytes >= budget_bytes * 0.75)
            ):
                break
        if rep.build_prop_blob is None:  # no vendor build.prop: use the first prop file fetched
            for remote in sel.order:
                prop = safe_join(tree, sel.mapping[remote])
                if remote.endswith("build.prop") and prop.is_file():
                    rep.build_prop_blob = git_blob_sha(prop.read_bytes())
                    break

        # Transitive DT_NEEDED of fetched vendor-side ELF files.
        libs: dict[str, list[str]] = {}
        for remote, local in sel.mapping.items():
            part, _, inner = local.partition("/")
            if part in VENDOR_SIDE and inner.rsplit("/", 1)[0] in LIB_DIRS:
                libs.setdefault(inner.rsplit("/", 1)[-1], []).append(remote)
        queue = [(r, 0) for r in sel.order if r in fetched]
        while queue:
            remote, depth = queue.pop(0)
            path = safe_join(tree, sel.mapping[remote])
            if depth >= MAX_DEPTH or not path.is_file() or not elf.is_elf(path):
                continue
            try:
                info = elf.parse_file(path)
            except (elf.ElfError, OSError):
                continue
            want = "/lib64/" if info.elf_class == "ELF64" else "/lib/"
            for name in info.needed:
                # Same ELF class first (lib64 for 64-bit), then a stable order.
                for cand in sorted(libs.get(name, []), key=lambda r: (want not in f"/{r}", r)):
                    if cand in fetched:
                        continue
                    if fetch(cand) is not None:
                        rep.dependency_fetches += 1
                        queue.append((cand, depth + 1))
                    break
        for remote in sel.order:
            if remote not in fetched:
                fetch(remote)

        extra = [
            FileEntry(
                local.split("/", 1)[0], local.split("/", 1)[1], None, None, False, None, False
            )
            for remote, local in sorted(sel.mapping.items())
            if not safe_join(tree, local).exists()
        ]
        return rep, extra, sel

    def analyze(
        self,
        item_id: str,
        out_store: Store,
        source_store: Store | None = None,
        dry_run: bool = False,
        keep_work: bool = False,
    ) -> dict[str, Any]:
        """Analyze one item into `out_store` (normally a delta store, see afid.reconcile)."""
        it = self.item(source_store or Store(self.cfg.database), item_id)
        meta = it["metadata"]
        base = self.workdir or Path(tempfile.mkdtemp(prefix="afid-remote-"))
        tree = base / "tree"
        tree.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        report: dict[str, Any] = {
            "provider_id": self.provider_id,
            "item_id": item_id,
            "revision": it["revision"],
            "status": "failed",
            "error": None,
        }
        try:
            fetch, extra, sel = self.fetch_tree(meta, tree)
            remote_of = {v: k for k, v in sel.mapping.items()}
            report["fetch"] = fetch.as_dict()
            prop_path = next(
                (p for p in ("vendor/build.prop", "system/build.prop") if (tree / p).is_file()),
                None,
            )
            ctx = SourceContext(
                source_type="community_firmware_dump",
                evidence_type="dump_build_prop",
                distribution_status="unknown",
                user_supplied=False,
                source_url=it["url"],
                source_ref={
                    "provider_id": self.provider_id,
                    "item_id": item_id,
                    "url": it["url"],
                    "revision": it["revision"],
                    "content_marker": fetch.build_prop_blob,
                    "retrieved_at": now,
                },
                extra_inventory=extra,
                store=out_store,
                evidence_url=self.provider.file_url(meta, remote_of[prop_path])
                if prop_path
                else None,
            )
            prepared = Prepared(
                tree=tree,
                workdir=base,
                archive_name=None,
                archive_sha256=None,
                archive_size=None,
                warnings=[f"remote analysis of {item_id} at {it['revision']}"],
            )
            if fetch.lfs_pointers:
                prepared.warnings.append(
                    f"{len(fetch.lfs_pointers)} file(s) are Git LFS pointers and were not fetched"
                )
            if fetch.skipped_budget:
                prepared.warnings.append(
                    f"{len(fetch.skipped_budget)} selected file(s) not fetched: budget reached"
                )
            res: IngestResult = _catalog(
                self.cfg, self.provider_id, prepared, None, None, None, None, None, dry_run, {}, ctx
            )
            report.update(res.as_dict())
            report["status"] = {"cataloged": "analyzed", "staged": "unresolved"}.get(
                res.status, res.status
            )
        except AfidError as exc:
            report["error"] = str(exc)[:500]
        finally:
            if not keep_work:
                shutil.rmtree(base, ignore_errors=True)
        return report
