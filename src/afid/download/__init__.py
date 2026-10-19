"""HTTPS client for providers: timeouts, bounded retries with exponential backoff, per-host
rate limiting, host allowlist (checked on every redirect hop), conditional requests,
byte limits, disk-budget checks, HTML-error-page rejection, optional verified resume.

Credentials come only from environment variables named in the provider registry and are
never logged.
"""

from __future__ import annotations

import email.utils
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afid.errors import ProviderError, ResourceError
from afid.hashing import sha256_file
from afid.utils import log

LOG = log.get("http")
RETRY_STATUS = {429, 500, 502, 503, 504}
HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]
    url: str = ""

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


def _lower(headers: Any) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    """Validate every redirect target against the same scheme/host rules as the first URL."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self.client._check_url(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            new is not None
            and self.client.token
            and urllib.parse.urlparse(newurl).hostname
            != urllib.parse.urlparse(req.full_url).hostname
        ):
            new.remove_header("Authorization")  # never forward credentials to another host
        return new


def _retry_after(headers: dict[str, str], fallback: float) -> float:
    value = headers.get("retry-after")
    if not value:
        return fallback
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return fallback
    return max(0.0, when - time.time())


@dataclass
class HttpClient:
    allowed_hosts: frozenset[str]
    timeout: float = 60
    max_retries: int = 3
    backoff: float = 2.0
    min_interval: float = 1.0
    user_agent: str = "AFID"
    token: str | None = None
    max_body: int = 64 * 1024 * 1024
    max_wait: float = 300.0
    _last: dict[str, float] = field(default_factory=dict)
    sleep = staticmethod(time.sleep)

    def _check_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise ProviderError(f"refusing non-HTTPS URL {url}")
        host = parsed.hostname or ""
        if host not in self.allowed_hosts:
            raise ProviderError(f"host '{host}' is not in this provider's allowed hosts")
        return host

    def _throttle(self, host: str) -> None:
        wait = self._last.get(host, 0) + self.min_interval - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        self._last[host] = time.monotonic()

    def _request(
        self, url: str, headers: dict[str, str], method: str = "GET"
    ) -> urllib.request.Request:
        h = {"User-Agent": self.user_agent, **headers}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(url, headers=h, method=method)  # noqa: S310 - scheme checked

    def _open(self, req: urllib.request.Request) -> Any:
        opener = urllib.request.build_opener(_RedirectGuard(self))
        return opener.open(req, timeout=self.timeout)

    def _backoff(self, url: str, attempt: int, headers: dict[str, str] | None = None) -> None:
        delay = min(self.max_wait, _retry_after(headers or {}, self.backoff * (2**attempt)))
        LOG.warning("retrying %s in %.0fs (attempt %d)", url, delay, attempt + 1)
        self.sleep(delay)

    def get(
        self,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
        method: str = "GET",
        allow_status: frozenset[int] = frozenset(),
        max_bytes: int | None = None,
    ) -> Response:
        """GET (or HEAD). Statuses in allow_status (e.g. 404) are returned instead of raised;
        max_bytes lowers the body limit for this call."""
        host = self._check_url(url)
        limit = min(self.max_body, max_bytes) if max_bytes is not None else self.max_body
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        attempt = 0
        while True:
            self._throttle(host)
            try:
                with self._open(self._request(url, headers, method)) as resp:
                    body = resp.read(limit + 1) if method != "HEAD" else b""
                    if len(body) > limit:
                        raise ProviderError(f"{url}: response larger than {limit} bytes")
                    return Response(resp.status, body, _lower(resp.headers), resp.geturl())
            except urllib.error.HTTPError as exc:
                hdrs = _lower(exc.headers)
                if exc.code == 304 or exc.code in allow_status:
                    return Response(exc.code, b"", hdrs, url)
                if exc.code not in RETRY_STATUS or attempt >= self.max_retries:
                    raise ProviderError(f"{method} {url} failed: HTTP {exc.code}") from None
                self._backoff(url, attempt, hdrs)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError(
                        f"{method} {url} failed: {_redact(str(exc), self.token)}"
                    ) from None
                self._backoff(url, attempt)
            attempt += 1

    def download(
        self,
        url: str,
        dest: Path,
        max_bytes: int,
        expected_sha256: str | None = None,
        reserve_bytes: int = 0,
        resume: bool = False,
    ) -> Path:
        """Stream url to dest (via dest.part). Rejects HTML error pages, enforces max_bytes
        while streaming, and checks free disk against Content-Length before writing.
        Resume is used only when the caller enables it for a server known to honour Range."""
        host = self._check_url(url)
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not resume:
            part.unlink(missing_ok=True)
        attempt = 0
        while True:
            offset = part.stat().st_size if resume and part.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            self._throttle(host)
            try:
                with self._open(self._request(url, headers)) as resp:
                    hdrs = _lower(resp.headers)
                    ctype = hdrs.get("content-type", "").split(";")[0].strip().lower()
                    if ctype in HTML_TYPES:
                        raise ProviderError(
                            f"{url}: server returned an HTML page ({ctype}), "
                            "not firmware (expired link, login or error page?)"
                        )
                    length = (
                        int(hdrs["content-length"])
                        if hdrs.get("content-length", "").isdigit()
                        else None
                    )
                    if length is not None and offset + length > max_bytes:
                        raise ProviderError(
                            f"{url}: {offset + length} bytes exceeds limit {max_bytes}"
                        )
                    free = shutil.disk_usage(dest.parent).free
                    if length is not None and length + reserve_bytes > free:
                        raise ResourceError(
                            f"{url}: needs {length} bytes + {reserve_bytes} "
                            f"reserve, only {free} free"
                        )
                    mode = "ab" if offset and resp.status == 206 else "wb"
                    written = offset if mode == "ab" else 0
                    with part.open(mode) as out:
                        while chunk := resp.read(1 << 20):
                            written += len(chunk)
                            if written > max_bytes:
                                raise ProviderError(f"{url}: exceeds {max_bytes} bytes")
                            out.write(chunk)
                    if length is not None:
                        expected_total = offset + length if mode == "ab" else length
                        if written != expected_total:
                            raise ProviderError(
                                f"{url}: truncated ({written} of {expected_total} bytes)"
                            )
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_STATUS or attempt >= self.max_retries:
                    part.unlink(missing_ok=True)
                    raise ProviderError(f"download {url} failed: HTTP {exc.code}") from None
                self._backoff(url, attempt, _lower(exc.headers))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= self.max_retries:
                    if not resume:
                        part.unlink(missing_ok=True)
                    raise ProviderError(
                        f"download {url} failed: {_redact(str(exc), self.token)}"
                    ) from None
                self._backoff(url, attempt)
            except (ProviderError, ResourceError):
                part.unlink(missing_ok=True)
                raise
            attempt += 1
        if expected_sha256:
            got = sha256_file(part)
            if got != expected_sha256.lower():
                part.unlink()
                raise ProviderError(
                    f"{url}: SHA-256 mismatch (expected {expected_sha256}, got {got})"
                )
        part.replace(dest)
        return dest


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text
