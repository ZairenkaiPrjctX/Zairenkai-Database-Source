"""URL policy for every URL the pipeline requests or records.

A URL is accepted only if it is HTTPS on the default port, carries no credentials, names a
host on the provider's explicit allowlist (never an IP literal), and, when a resolver is
given, that host resolves only to public addresses. GuardedHttpClient applies the policy to
the first URL and to every redirect hop, and refuses to download files at all.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from afid.download import HttpClient, Response
from afid.errors import CapabilityError, PolicyViolationError, ResourceError

Resolver = Callable[[str], list[str]]

_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")


class UrlPolicyError(PolicyViolationError):
    """A URL failed the pipeline's URL policy."""


class BudgetExceeded(ResourceError):
    """The run's time or request budget is exhausted."""


class RequestBudgetExceeded(BudgetExceeded):
    """max_requests reached: an expected bound, so the source is reported as truncated."""


class TimeBudgetExceeded(BudgetExceeded):
    """max_run_seconds reached (or a wait would cross it): the source is reported as partial."""


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return sorted({str(info[4][0]) for info in infos})


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def valid_hostname(host: str) -> bool:
    """Lowercase DNS name with at least one dot; no IP literal, wildcard or trailing dot."""
    if not host or len(host) > 253 or host != host.lower() or "." not in host:
        return False
    if _is_ip_literal(host) or not set(host) <= _HOST_CHARS:
        return False
    return all(
        0 < len(label) <= 63 and not label.startswith("-") and not label.endswith("-")
        for label in host.split(".")
    )


def check_url(url: str, allowed_hosts: Iterable[str], resolver: Resolver | None = None) -> str:
    """Return the URL's host if the URL passes the policy, else raise UrlPolicyError."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise UrlPolicyError("URL is empty or longer than 2048 characters")
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        raise UrlPolicyError("URL contains whitespace or control characters")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise UrlPolicyError(f"scheme '{parts.scheme}' refused: only https is allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UrlPolicyError("URLs with embedded credentials are refused")
    host = (parts.hostname or "").lower()
    if not host:
        raise UrlPolicyError("URL has no host")
    try:
        port = parts.port
    except ValueError:
        raise UrlPolicyError("URL has an invalid port") from None
    if port not in (None, 443):
        raise UrlPolicyError(f"port {port} refused: only the default HTTPS port is allowed")
    if _is_ip_literal(host):
        raise UrlPolicyError(f"IP literal '{host}' refused: hosts must be named on the allowlist")
    if host not in frozenset(allowed_hosts):
        raise UrlPolicyError(f"host '{host}' is not on this source's allowlist")
    if resolver is not None:
        try:
            addresses = resolver(host)
        except OSError as exc:
            raise UrlPolicyError(
                f"host '{host}' does not resolve ({exc.strerror or exc})"
            ) from None
        if not addresses:
            raise UrlPolicyError(f"host '{host}' does not resolve")
        for address in addresses:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
            if not ip.is_global or ip.is_multicast:
                raise UrlPolicyError(
                    f"host '{host}' resolves to non-public address {address}; refused"
                )
    return host


@dataclass
class GuardedHttpClient(HttpClient):
    """HttpClient with the URL policy on every hop, a request budget and a run deadline.

    Retries (transient statuses and network errors only), exponential backoff, Retry-After,
    per-host pacing and response size limits come from HttpClient unchanged.
    """

    resolver: Resolver | None = system_resolver
    deadline: float | None = None  # time.monotonic() value after which no request starts
    max_requests: int | None = None
    requests: int = 0
    clock: Callable[[], float] = time.monotonic
    _real_sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    def __post_init__(self) -> None:
        self.sleep = self._sleep  # type: ignore[assignment]

    def remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - self.clock()

    def _sleep(self, seconds: float) -> None:
        left = self.remaining()
        if left is not None and seconds >= left:
            raise TimeBudgetExceeded(f"run time budget would be exceeded by a {seconds:.0f}s wait")
        self._real_sleep(seconds)

    def _check_url(self, url: str) -> str:
        return check_url(url, self.allowed_hosts, self.resolver)

    def _open(self, req):  # type: ignore[no-untyped-def]
        # Every attempt, including retries, counts against the budget.
        left = self.remaining()
        if left is not None and left <= 0:
            raise TimeBudgetExceeded("run time budget exhausted")
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise RequestBudgetExceeded(f"request budget of {self.max_requests} exhausted")
        self.requests += 1
        return self._transport(req)  # type: ignore[no-untyped-call]

    def _transport(self, req):  # type: ignore[no-untyped-def]
        """The network leg (urllib with the redirect guard); tests replace only this."""
        return super()._open(req)

    def get(
        self,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
        method: str = "GET",
        allow_status: frozenset[int] = frozenset(),
        max_bytes: int | None = None,
    ) -> Response:
        if method != "GET":
            raise UrlPolicyError(f"method {method} refused: the pipeline only sends GET")
        return super().get(url, etag, last_modified, method, allow_status, max_bytes)

    def download(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
        raise CapabilityError(
            "the metadata pipeline never downloads files; binary acquisition is a separate, "
            "operator-approved stage"
        )
