"""URL policy: schemes, credentials, ports, IP literals, allowlist, private addresses,
redirects, GET-only and no downloads."""

from __future__ import annotations

import urllib.request
from pathlib import Path

from afid.download import _RedirectGuard
from afid.errors import CapabilityError
from afid.pipeline.urlpolicy import (
    GuardedHttpClient,
    UrlPolicyError,
    check_url,
    valid_hostname,
)
from tests.pipeline.support import PipelineCase

ALLOWED = frozenset({"gitlab.com"})


class UrlPolicyTest(PipelineCase):
    def test_rejects_unsafe_schemes_and_hosts(self) -> None:
        self.assertEqual(check_url("https://gitlab.com/api/v4/groups/1", ALLOWED), "gitlab.com")
        self.assertEqual(check_url("https://GITLAB.com:443/x", ALLOWED), "gitlab.com")
        for url in (
            "http://gitlab.com/x",
            "ftp://gitlab.com/x",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://user:secret@gitlab.com/x",
            "https://gitlab.com@evil.example/x",
            "https://gitlab.com:8443/x",
            "https://gitlab.com:notaport/x",
            "https://127.0.0.1/x",
            "https://[::1]/x",
            "https://169.254.169.254/latest/meta-data/",
            "https://evil.example/x",
            "https://gitlab.com.evil.example/x",
            "https://gitlab.com/x y",
            "https://gitlab.com/x\n",
            "",
            "https://gitlab.com/" + "a" * 3000,
        ):
            with self.subTest(url=url), self.assertRaises(UrlPolicyError):
                check_url(url, ALLOWED)

    def test_rejects_hosts_resolving_to_private_addresses(self) -> None:
        for address in (
            "10.0.0.5",
            "127.0.0.1",
            "169.254.169.254",
            "192.168.1.1",
            "100.64.0.1",
            "fd00::1",
            "::1",
        ):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(UrlPolicyError, "non-public"),
            ):
                check_url(
                    "https://gitlab.com/x", ALLOWED, resolver=lambda h, a=address: ["1.1.1.1", a]
                )
        with self.assertRaisesRegex(UrlPolicyError, "does not resolve"):
            check_url("https://gitlab.com/x", ALLOWED, resolver=lambda h: [])

        def fails(host: str) -> list[str]:
            raise OSError("name not known")

        with self.assertRaisesRegex(UrlPolicyError, "does not resolve"):
            check_url("https://gitlab.com/x", ALLOWED, resolver=fails)
        self.assertEqual(
            check_url("https://gitlab.com/x", ALLOWED, resolver=lambda h: ["1.1.1.1"]), "gitlab.com"
        )

    def test_hostname_rules(self) -> None:
        self.assertTrue(valid_hostname("dumps.tadiphone.dev"))
        for host in ("localhost", "GitLab.com", "*.gitlab.com", "10.0.0.1", "-a.com", "a..com", ""):
            self.assertFalse(valid_hostname(host), host)

    def test_redirects_outside_allowlist_are_refused(self) -> None:
        client = GuardedHttpClient(allowed_hosts=ALLOWED, resolver=lambda h: ["1.1.1.1"])
        guard = _RedirectGuard(client)
        req = urllib.request.Request("https://gitlab.com/api/v4/x")
        for target in (
            "https://evil.example/x",
            "http://gitlab.com/x",
            "https://169.254.169.254/latest/meta-data/",
        ):
            with self.subTest(target=target), self.assertRaises(UrlPolicyError):
                guard.redirect_request(req, None, 302, "Found", {}, target)
        client.resolver = lambda h: ["10.1.2.3"]  # DNS now points inside the network
        with self.assertRaisesRegex(UrlPolicyError, "non-public"):
            guard.redirect_request(req, None, 302, "Found", {}, "https://gitlab.com/y")

    def test_client_never_downloads_and_only_sends_get(self) -> None:
        client = GuardedHttpClient(allowed_hosts=ALLOWED, resolver=None)
        with self.assertRaises(CapabilityError):
            client.download("https://gitlab.com/fw.zip", Path("fw.zip"), 1)
        with self.assertRaises(UrlPolicyError):
            client.get("https://gitlab.com/x", method="HEAD")
