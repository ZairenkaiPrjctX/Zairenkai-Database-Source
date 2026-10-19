"""Minimal read-only GitLab REST v4 client for public dump groups.

Verified against gitlab.com (group "Android-Dumps") and dumps.tadiphone.dev (self-hosted
GitLab, group "dumps") on 2026-10-18; see docs/SOURCE_INTEGRATION.md. Only unauthenticated
GET/HEAD requests are made. Pagination follows `x-next-page`; gitlab.com rate-limit headers
(`ratelimit-remaining`, `ratelimit-reset`) are honoured; HTTP 429 `Retry-After` is handled
by HttpClient.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from afid.download import HttpClient, Response
from afid.errors import ProviderError
from afid.utils import log

LOG = log.get("gitlab")
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
RATE_LIMIT_FLOOR = 5


def is_lfs_pointer(data: bytes) -> bool:
    return data.startswith(LFS_POINTER_PREFIX) and len(data) < 1024


def lfs_pointer_size(data: bytes) -> int | None:
    for line in data.decode("ascii", "replace").splitlines():
        if line.startswith("size ") and line[5:].strip().isdigit():
            return int(line[5:].strip())
    return None


@dataclass
class GitLabClient:
    http: HttpClient
    api_base: str  # e.g. https://gitlab.com/api/v4
    per_page: int = 100

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        query = urllib.parse.urlencode(params or {})
        return f"{self.api_base.rstrip('/')}/{path.lstrip('/')}" + (f"?{query}" if query else "")

    def _pace(self, resp: Response) -> None:
        """Sleep until the window resets when gitlab.com says we are nearly out of requests."""
        remaining = resp.header("ratelimit-remaining")
        reset = resp.header("ratelimit-reset")
        if remaining and remaining.isdigit() and int(remaining) <= RATE_LIMIT_FLOOR:
            wait = (int(reset) - time.time()) if reset and reset.isdigit() else 60.0
            wait = min(max(wait, 1.0), self.http.max_wait)
            LOG.warning("GitLab rate limit nearly exhausted; waiting %.0fs", wait)
            self.http.sleep(wait)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.http.get(self._url(path, params))
        self._pace(resp)
        try:
            return json.loads(resp.body)
        except ValueError as exc:
            raise ProviderError(f"{path}: invalid JSON from GitLab ({exc})") from None

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, max_pages: int = 1000
    ) -> Iterator[dict[str, Any]]:
        page: str | None = "1"
        pages = 0
        while page:
            if pages >= max_pages:
                raise ProviderError(f"{path}: more than {max_pages} pages; refusing to continue")
            resp = self.http.get(
                self._url(path, {**(params or {}), "per_page": self.per_page, "page": page})
            )
            self._pace(resp)
            try:
                batch = json.loads(resp.body)
            except ValueError as exc:
                raise ProviderError(f"{path}: invalid JSON from GitLab ({exc})") from None
            if not isinstance(batch, list):
                raise ProviderError(f"{path}: expected a JSON list, got {type(batch).__name__}")
            yield from batch
            pages += 1
            page = resp.header("x-next-page") or None

    def group_projects(self, group: str | int, max_pages: int) -> list[dict[str, Any]]:
        return list(
            self.paginate(
                f"groups/{urllib.parse.quote(str(group), safe='')}/projects",
                {
                    "include_subgroups": "true",
                    "archived": "false",
                    "order_by": "id",
                    "sort": "asc",
                    "simple": "true",
                },
                max_pages,
            )
        )

    def branches(self, project_id: int, max_pages: int = 20) -> list[dict[str, Any]]:
        return list(self.paginate(f"projects/{project_id}/repository/branches", None, max_pages))

    def raw_file(self, project_id: int, path: str, ref: str, max_bytes: int) -> bytes | None:
        """File content at `ref` (a commit SHA for reproducibility); None when absent."""
        url = self._url(
            f"projects/{project_id}/repository/files/{urllib.parse.quote(path, safe='')}/raw",
            {"ref": ref},
        )
        resp = self.http.get(url, allow_status=frozenset({404}), max_bytes=max_bytes)
        self._pace(resp)
        return None if resp.status == 404 else resp.body

    def tree(self, project_id: int, ref: str, max_pages: int) -> list[str]:
        """Recursive file list (blobs only). Used when a dump has no all_files.txt."""
        return [
            e["path"]
            for e in self.paginate(
                f"projects/{project_id}/repository/tree",
                {"ref": ref, "recursive": "true"},
                max_pages,
            )
            if e.get("type") == "blob"
        ]
