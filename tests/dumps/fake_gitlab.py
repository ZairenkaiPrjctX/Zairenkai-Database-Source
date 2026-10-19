"""In-process fake of the GitLab REST v4 endpoints AFID uses. Serves synthetic dump trees;
installed by monkeypatching HttpClient._open, so no socket is ever opened."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Any


class Resp:
    def __init__(self, body: bytes, headers: dict[str, str], url: str, status: int = 200):
        self._buf = io.BytesIO(body)
        self.headers = headers
        self.status = status
        self._url = url

    def geturl(self) -> str:
        return self._url

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self) -> Resp:
        return self

    def __exit__(self, *a: Any) -> bool:
        return False


def http_error(
    url: str, code: int, headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(url, code, "fake", msg, None)


@dataclass
class Project:
    id: int
    path: str  # path_with_namespace, including the group
    branches: dict[str, str] = field(default_factory=dict)  # branch -> commit
    files: dict[str, dict[str, bytes]] = field(default_factory=dict)  # commit -> path -> bytes
    last_activity_at: str = "2026-10-01T00:00:00.000Z"
    default_branch: str | None = "main"


@dataclass
class FakeGitLab:
    host: str
    group: int
    projects: list[Project] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    rate_limit_remaining: int | None = None
    fail_once: dict[str, int] = field(default_factory=dict)  # path substring -> status

    def add_dump(
        self,
        pid: int,
        path: str,
        branch: str,
        commit: str,
        tree: Path,
        extra: dict[str, bytes] | None = None,
    ) -> Project:
        files = {
            p.relative_to(tree).as_posix(): p.read_bytes()
            for p in sorted(tree.rglob("*"))
            if p.is_file() and not p.is_symlink()
        }
        files.update(extra or {})
        files["all_files.txt"] = ("\n".join(sorted(files)) + "\n").encode()
        proj = next((p for p in self.projects if p.id == pid), None)
        if proj is None:
            proj = Project(pid, path, default_branch=branch)
            self.projects.append(proj)
        proj.branches[branch] = commit
        proj.files[commit] = files
        return proj

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.rate_limit_remaining is not None:
            h.update(
                {
                    "RateLimit-Limit": "500",
                    "RateLimit-Remaining": str(self.rate_limit_remaining),
                    "RateLimit-Reset": "0",
                }
            )
        h.update(extra or {})
        return h

    def _page(self, url: str, items: list[Any], q: dict[str, str]) -> Resp:
        per = int(q.get("per_page", "20"))
        page = int(q.get("page", "1"))
        chunk = items[(page - 1) * per : page * per]
        nxt = str(page + 1) if page * per < len(items) else ""
        return Resp(
            json.dumps(chunk).encode(),
            self._headers({"X-Next-Page": nxt, "X-Total": str(len(items))}),
            url,
        )

    def open(self, req: Any) -> Resp:
        url = req.full_url
        self.requests.append(url)
        for frag, code in list(self.fail_once.items()):
            if frag in url:
                del self.fail_once[frag]
                raise http_error(url, code, {"Retry-After": "7"})
        u = urllib.parse.urlparse(url)
        if u.hostname != self.host:
            raise AssertionError(f"unexpected host {u.hostname}")
        q = dict(urllib.parse.parse_qsl(u.query))
        parts = u.path.split("/")[3:]  # after /api/v4
        if parts[:1] == ["groups"] and parts[2:] == ["projects"]:
            rows = [
                {
                    "id": p.id,
                    "path_with_namespace": p.path,
                    "web_url": f"https://{self.host}/{p.path}",
                    "default_branch": p.default_branch,
                    "last_activity_at": p.last_activity_at,
                }
                for p in sorted(self.projects, key=lambda p: p.id)
            ]
            return self._page(url, rows, q)
        proj = next(p for p in self.projects if str(p.id) == parts[1])
        if parts[2:] == ["repository", "branches"]:
            rows = [
                {"name": b, "commit": {"id": c, "committed_date": "2026-10-01T00:00:00Z"}}
                for b, c in sorted(proj.branches.items())
            ]
            return self._page(url, rows, q)
        if parts[2:4] == ["repository", "files"] and parts[-1] == "raw":
            path = urllib.parse.unquote(parts[4])
            data = proj.files.get(q["ref"], {}).get(path)
            if data is None:
                raise http_error(url, 404)
            return Resp(data, self._headers({"Content-Type": "text/plain"}), url)
        if parts[2:] == ["repository", "tree"]:
            rows = [{"path": p, "type": "blob"} for p in sorted(proj.files.get(q["ref"], {}))]
            return self._page(url, rows, q)
        raise http_error(url, 404)
