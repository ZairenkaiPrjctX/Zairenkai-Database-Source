"""Community firmware dump providers: public GitLab groups of DumprX-style dumps.

Verified layout (2026-10-18, docs/SOURCE_INTEGRATION.md):
- one GitLab project per device, `<group>/<namespace>/<project>`; the namespace is usually a
  brand name and the project name usually a codename, but both are only *hints*;
- each branch is one firmware dump, named after the build description;
- the tree holds extracted partitions (`vendor/`, `odm/`, `system/system/` ...) plus
  `all_files.txt` (one path per line); large files may be Git LFS pointers.

AFID never clones these repositories and never downloads firmware archives from them. It
lists projects and branches, and the analysis step fetches a bounded set of individual
files pinned to the branch's commit SHA (afid.remote). Identity comes from the fetched
build.prop only.
"""

from __future__ import annotations

import threading
from typing import Any

from afid.errors import ProviderError
from afid.providers.base import (
    Capabilities,
    DiscoveryResult,
    FirmwareProvider,
    Health,
    SourceItem,
)
from afid.providers.gitlab import GitLabClient
from afid.utils import log

LOG = log.get("dumps")
FILE_LIST = "all_files.txt"


class GitLabDumpsProvider(FirmwareProvider):
    """Settings (config/provider_registry.yml):
    api_base             https://<host>/api/v4
    group                numeric group id (stable even if the group is renamed)
    group_path           full path of the group, stripped from project paths in item ids
    max_project_pages    hard stop for the project listing
    min_projects         a listing with fewer projects is treated as a failure, so a broken
                         or truncated response can never make items look removed
    max_branches_per_project
    """

    CAPABILITIES = Capabilities(discover_firmware=True, fetch_metadata=True)

    @property
    def gitlab(self) -> GitLabClient:
        return GitLabClient(
            self.http, str(self.settings["api_base"]), int(self.settings.get("per_page", 100))
        )

    def _rel(self, path_with_namespace: str) -> str:
        prefix = str(self.settings["group_path"]).strip("/") + "/"
        if path_with_namespace.lower().startswith(prefix.lower()):
            return path_with_namespace[len(prefix) :]
        return path_with_namespace

    def health_check(self) -> Health:
        checks: list[dict[str, Any]] = []
        try:
            resp = self.http.get(
                self.gitlab._url(
                    f"groups/{self.settings['group']}/projects",
                    {"include_subgroups": "true", "per_page": 1, "simple": "true"},
                )
            )
        except ProviderError as exc:
            return Health(
                self.provider_id, "failed", [{"check": "list_projects", "result": str(exc)}]
            )
        checks.append({"check": "list_projects", "result": f"HTTP {resp.status}"})
        total = resp.header("x-total")
        checks.append({"check": "x-total", "result": total or "not reported"})
        limit = resp.header("ratelimit-limit")
        checks.append(
            {
                "check": "rate_limit",
                "result": f"{resp.header('ratelimit-remaining')}/{limit}"
                if limit
                else "no headers",
            }
        )
        status = "ok" if resp.status == 200 else "degraded"
        return Health(self.provider_id, status, checks)

    def discover_firmware(
        self,
        previous: dict[str, dict[str, Any]] | None = None,
        cancel: threading.Event | None = None,
    ) -> DiscoveryResult:
        previous = previous or {}
        res = DiscoveryResult(self.provider_id, "ok")
        gl = self.gitlab
        projects = gl.group_projects(
            self.settings["group"], int(self.settings.get("max_project_pages", 100))
        )
        minimum = int(self.settings.get("min_projects", 1))
        if len(projects) < minimum:
            raise ProviderError(
                f"{self.provider_id}: listing returned {len(projects)} projects, expected at "
                f"least {minimum}; treating as a failed check so no item is marked removed"
            )
        old_by_project: dict[int, list[dict[str, Any]]] = {}
        for item in previous.values():
            pid = (item.get("metadata") or {}).get("project_id")
            if isinstance(pid, int):
                old_by_project.setdefault(pid, []).append(item)
        stats = {"projects": len(projects), "reused": 0, "listed": 0, "empty": 0}
        max_branches = int(self.settings.get("max_branches_per_project", 50))
        for proj in sorted(projects, key=lambda p: p["id"]):
            if cancel is not None and cancel.is_set():
                res.status = "partial"
                res.errors.append("cancelled")
                break
            if not proj.get("default_branch"):
                stats["empty"] += 1
                res.skipped += 1
                continue
            old = old_by_project.get(proj["id"], [])
            activity = proj.get("last_activity_at")
            if old and all(o["metadata"].get("last_activity_at") == activity for o in old):
                res.items.extend(
                    SourceItem(
                        o["item_id"],
                        o["revision"],
                        o["url"],
                        dict(o["metadata"]),
                        o.get("kind", "firmware"),
                    )
                    for o in old
                )
                stats["reused"] += 1
                continue
            try:
                branches = gl.branches(proj["id"], max_pages=max(1, max_branches // 100 + 1))
            except ProviderError as exc:
                res.status = "partial"
                res.errors.append(f"{proj['path_with_namespace']}: {exc}")
                res.items.extend(
                    SourceItem(
                        o["item_id"],
                        o["revision"],
                        o["url"],
                        dict(o["metadata"]),
                        o.get("kind", "firmware"),
                    )
                    for o in old
                )
                continue
            stats["listed"] += 1
            if len(branches) > max_branches:
                res.errors.append(
                    f"{proj['path_with_namespace']}: {len(branches)} branches, only the "
                    f"{max_branches} most recent are listed"
                )
                branches = sorted(
                    branches, key=lambda b: b["commit"].get("committed_date") or "", reverse=True
                )[:max_branches]
            rel = self._rel(proj["path_with_namespace"])
            namespace, _, project = rel.rpartition("/")
            if not branches:  # remember the empty project so the next run can skip it
                stats["empty"] += 1
                res.items.append(
                    SourceItem(
                        f"_project/{proj['id']}",
                        activity,
                        proj.get("web_url"),
                        {
                            "project_id": proj["id"],
                            "project_path": rel,
                            "last_activity_at": activity,
                        },
                        kind="index",
                    )
                )
            for b in sorted(branches, key=lambda b: b["name"]):
                commit = b["commit"]["id"]
                res.items.append(
                    SourceItem(
                        item_id=f"{rel}@{b['name']}",
                        revision=commit,
                        url=f"{proj['web_url']}/-/tree/{commit}",
                        metadata={
                            "project_id": proj["id"],
                            "project_path": rel,
                            "namespace_hint": namespace or None,
                            "project_hint": project,
                            "branch": b["name"],
                            "default_branch": b["name"] == proj["default_branch"],
                            "commit": commit,
                            "committed_date": b["commit"].get("committed_date"),
                            "last_activity_at": activity,
                        },
                    )
                )
        res.items.sort(key=lambda i: i.item_id)
        res.stats = stats
        res.index_revision = None
        LOG.info(
            "%s: %d items from %d projects (%s)",
            self.provider_id,
            len(res.items),
            len(projects),
            stats,
        )
        return res

    # ---- per-item access (used by afid.remote) -------------------------------------------
    def list_files(self, meta: dict[str, Any], max_bytes: int) -> tuple[list[str], str]:
        """Paths in the dump at its pinned commit and how they were obtained."""
        raw = self.gitlab.raw_file(meta["project_id"], FILE_LIST, meta["commit"], max_bytes)
        if raw is not None:
            paths = [ln.strip() for ln in raw.decode("utf-8", "replace").splitlines()]
            return sorted(
                {p for p in paths if p and not p.startswith("/") and ".." not in p}
            ), FILE_LIST
        pages = int(self.settings.get("max_tree_pages", 400))
        return sorted(self.gitlab.tree(meta["project_id"], meta["commit"], pages)), "tree API"

    def fetch_file(self, meta: dict[str, Any], path: str, max_bytes: int) -> bytes | None:
        return self.gitlab.raw_file(meta["project_id"], path, meta["commit"], max_bytes)

    def file_url(self, meta: dict[str, Any], path: str) -> str:
        host = str(self.settings["api_base"]).split("/api/")[0]
        project = f"{host}/{self.settings['group_path']}/{meta['project_path']}"
        return f"{project}/-/blob/{meta['commit']}/{path}"


class AndroidDumpsGitLabProvider(GitLabDumpsProvider):
    """gitlab.com group "Android-Dumps" (id 13303221). Unauthenticated API limit verified at
    500 requests per window (`ratelimit-name: throttle_unauthenticated_api`)."""


class TadiphoneDumpsProvider(GitLabDumpsProvider):
    """dumps.tadiphone.dev, a self-hosted GitLab, group "dumps" (id 64). Sends no rate-limit
    headers; AFID paces itself with RATE_LIMIT_DELAY. Independent dumps, not a mirror of
    Android-Dumps (no shared commit SHAs in a 24-branch sample)."""
