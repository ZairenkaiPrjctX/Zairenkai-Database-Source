"""HTTPS client for providers: timeouts, bounded retries with exponential backoff, per-host
rate limiting, host allowlist, conditional requests, resumable downloads, size limits.

Credentials come only from environment variables named in the provider registry and are
never logged.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from afid.errors import ProviderError
from afid.hashing import sha256_file
from afid.utils import log

LOG = log.get("http")
RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]

    @property
    def not_modified(self) -> bool:
        return self.status == 304


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

    def _request(self, url: str, headers: dict[str, str]) -> urllib.request.Request:
        h = {"User-Agent": self.user_agent, **headers}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(url, headers=h)  # noqa: S310 - scheme checked

    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> Response:
        host = self._check_url(url)
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        attempt = 0
        while True:
            self._throttle(host)
            try:
                with urllib.request.urlopen(  # noqa: S310 - scheme and host checked
                    self._request(url, headers),
                    timeout=self.timeout,
                ) as resp:
                    body = resp.read(self.max_body + 1)
                    if len(body) > self.max_body:
                        raise ProviderError(f"{url}: response larger than {self.max_body} bytes")
                    return Response(resp.status, body, dict(resp.headers.items()))
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    return Response(304, b"", dict(exc.headers.items()))
                if exc.code not in RETRY_STATUS or attempt >= self.max_retries:
                    raise ProviderError(f"GET {url} failed: HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError(
                        f"GET {url} failed: {_redact(str(exc), self.token)}"
                    ) from None
            delay = self.backoff * (2**attempt)
            LOG.warning("retrying %s in %.0fs (attempt %d)", url, delay, attempt + 1)
            self.sleep(delay)
            attempt += 1

    def download(
        self, url: str, dest: Path, max_bytes: int, expected_sha256: str | None = None
    ) -> Path:
        """Download to dest, resuming a partial file (dest.part) when the server supports it."""
        host = self._check_url(url)
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        offset = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        self._throttle(host)
        try:
            with urllib.request.urlopen(  # noqa: S310 - scheme and host checked
                self._request(url, headers),
                timeout=self.timeout,
            ) as resp:
                mode = "ab" if offset and resp.status == 206 else "wb"
                written = offset if mode == "ab" else 0
                with part.open(mode) as out:
                    while chunk := resp.read(1 << 20):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ProviderError(f"{url}: exceeds {max_bytes} bytes")
                        out.write(chunk)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"download {url} failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"download {url} failed: {_redact(str(exc), self.token)}") from None
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
