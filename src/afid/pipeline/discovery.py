"""Bounded metadata discovery. Each strategy returns items, never file contents.

gitlab_group_branches lists a group's projects (at most max_pages pages of 100, by project
id) and one page of branches per project, and stops at max_records items or when the
client's request budget runs out. It reuses afid's GitLab client conventions: unauthenticated
GET only, X-Next-Page pagination, 404 meaning "repository not readable".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from afid.errors import ProviderError
from afid.pipeline.records import COMMIT, DATA_FIELDS, Item, Value, dump_branch_item
from afid.pipeline.registry import Provider
from afid.pipeline.urlpolicy import GuardedHttpClient
from afid.providers.gitlab import GitLabClient

PER_PAGE = 100


@dataclass
class Outcome:
    items: list[Item] = field(default_factory=list)
    malformed: list[tuple[str | None, str]] = field(default_factory=list)  # (item id, problem)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0
    truncated: bool = False


def _json_list(body: bytes, what: str) -> list[Any]:
    try:
        data = json.loads(body)
    except ValueError:
        raise ProviderError(f"{what}: response is not valid JSON") from None
    if not isinstance(data, list):
        raise ProviderError(f"{what}: expected a JSON list, got {type(data).__name__}")
    return data


def gitlab_group_branches(
    provider: Provider, http: GuardedHttpClient, max_pages: int, max_records: int, out: Outcome
) -> None:
    """Fill `out` in place, so items found before a budget error are kept."""
    d = provider.discovery
    gl = GitLabClient(http, str(d["api_base"]), PER_PAGE)
    prefix = str(d["group_path"]).strip("/") + "/"
    projects: list[Any] = []
    page: str | None = "1"
    pages = 0
    while page and pages < max_pages:
        resp = http.get(
            gl._url(
                f"groups/{int(d['group'])}/projects",
                {
                    "include_subgroups": "true",
                    "archived": "false",
                    "order_by": "id",
                    "sort": "asc",
                    "simple": "true",
                    "per_page": PER_PAGE,
                    "page": page,
                },
            )
        )
        projects += _json_list(resp.body, "group project listing")
        pages += 1
        page = resp.header("x-next-page") or None
    out.truncated = bool(page)
    for proj in sorted(
        (p for p in projects if isinstance(p, dict) and isinstance(p.get("id"), int)),
        key=lambda p: int(p["id"]),
    ):
        if len(out.items) >= max_records:
            out.truncated = True
            return
        path = proj.get("path_with_namespace")
        web_url = proj.get("web_url")
        if not isinstance(path, str) or not isinstance(web_url, str):
            out.malformed.append((None, f"project {proj['id']}: missing path or web_url"))
            continue
        if not proj.get("default_branch"):
            out.skipped += 1  # empty repository
            continue
        rel = path[len(prefix) :] if path.lower().startswith(prefix.lower()) else path
        try:
            resp = http.get(
                gl._url(
                    f"projects/{proj['id']}/repository/branches",
                    {"per_page": PER_PAGE, "page": 1},
                ),
                allow_status=frozenset({404}),
            )
            if resp.status == 404:
                out.skipped += 1  # project without a readable repository
                continue
            branches = _json_list(resp.body, f"branches of {rel}")
        except ProviderError as exc:
            out.errors.append(f"{rel}: {exc}")
            continue
        if resp.header("x-next-page"):
            out.truncated = True
        for b in sorted(branches, key=lambda b: str(b.get("name")) if isinstance(b, dict) else ""):
            name = b.get("name") if isinstance(b, dict) else None
            commit = (b.get("commit") or {}).get("id") if isinstance(b, dict) else None
            if not isinstance(name, str) or not name or not isinstance(commit, str):
                out.malformed.append((f"{rel}@{name}", "branch entry without a name or commit id"))
                continue
            if not COMMIT.match(commit):
                out.malformed.append((f"{rel}@{name}", "branch commit id is not a 40-hex SHA-1"))
                continue
            if len(out.items) >= max_records:
                out.truncated = True
                return
            out.items.append(dump_branch_item(rel, name, commit, web_url))


def synthetic_items(provider: Provider, raw_items: list[dict[str, Any]], out: Outcome) -> None:
    """Items from the offline fixture. 'dump_branch' entries go through the same mapping as
    real GitLab branches; 'package' entries carry explicit field values."""
    for raw in raw_items:
        kind = raw.get("kind")
        if kind == "dump_branch":
            out.items.append(
                dump_branch_item(raw["project_path"], raw["branch"], raw["commit"], raw["web_url"])
            )
        elif kind == "package":
            unknown = sorted(set(raw.get("fields", {})) - set(DATA_FIELDS))
            if unknown:
                out.malformed.append((raw.get("item_id"), f"unknown record fields {unknown}"))
                continue
            fields = {
                k: Value(v["value"], v["origin"], v["method"], v.get("source_field"))
                for k, v in sorted(raw.get("fields", {}).items())
            }
            out.items.append(Item(raw["item_id"], raw.get("revision"), raw["url"], fields))
        else:
            out.malformed.append((raw.get("item_id"), f"unknown fixture item kind {kind!r}"))
