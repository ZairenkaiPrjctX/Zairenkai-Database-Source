"""Shared helpers for the metadata pipeline tests (plain unittest, so CodeBuild can run them
with `python -m unittest` and no test dependencies; pytest collects them too).

Every PipelineCase works on a copy of config/, schemas/ and registry/ in a temporary
directory, and blocks real network access (sockets, DNS, urllib) and subprocesses for the
duration of each test. Fake GitLab traffic goes through GuardedHttpClient._transport.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from afid.pipeline.registry import Limits, Provider
from afid.pipeline.urlpolicy import GuardedHttpClient
from tests.dumps.fake_gitlab import FakeGitLab, Project

REPO = Path(__file__).resolve().parents[2]
PUBLIC_IP = ["1.1.1.1"]


def _no_network(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("pipeline tests must never open a network connection")


class PipelineCase(unittest.TestCase):
    # End-to-end tests that start the tools as child processes set this; the children get
    # an environment without credentials and with a dead proxy instead.
    allow_subprocess = False

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()
        for name in ("config", "schemas", "registry"):
            shutil.copytree(REPO / name, self.root / name)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "socket.create_connection",
            "urllib.request.OpenerDirector.open",
            *(() if self.allow_subprocess else ("subprocess.run", "subprocess.Popen")),
        ):
            patcher = mock.patch(target, side_effect=_no_network)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(
            "os.environ",
            {"ENABLE_S3_PUBLISH": "", "SOURCE_DATE_EPOCH": "", "AFID_LOG_FORMAT": ""},
        )
        env.start()
        self.addCleanup(env.stop)
        # Fake-transport retries log warnings that read like real traffic; keep them out of
        # build logs (assertLogs still captures them where a test checks logging).
        logger = logging.getLogger("afid")
        saved = (logger.handlers[:], logger.propagate)
        logger.handlers, logger.propagate = [logging.NullHandler()], False
        self.addCleanup(lambda: setattr(logger, "handlers", saved[0]))
        self.addCleanup(lambda: setattr(logger, "propagate", saved[1]))

    # ---- registry helpers ------------------------------------------------------------
    def registry(self) -> dict[str, Any]:
        return json.loads((self.root / "registry" / "sources.json").read_text())

    def write_registry(self, doc: dict[str, Any]) -> None:
        (self.root / "registry" / "sources.json").write_text(json.dumps(doc, indent=2))

    def provider(self, doc: dict[str, Any], pid: str) -> dict[str, Any]:
        return next(p for p in doc["providers"] if p["id"] == pid)

    def enable(self, pid: str, **limits: Any) -> None:
        """Enable a provider in the temporary registry with an approved review."""
        doc = self.registry()
        p = self.provider(doc, pid)
        p["enabled"] = True
        p["review"].update(status="approved", reviewed_by="test reviewer", reviewed_on="2026-10-20")
        p["limits"].update(limits)
        self.write_registry(doc)


def fake_gitlab(host: str = "gitlab.com", group: int = 13303221) -> FakeGitLab:
    return FakeGitLab(host, group)


def add_project(
    fake: FakeGitLab,
    pid: int,
    rel: str,
    branches: dict[str, str],
    group_path: str = "Android-Dumps",
) -> Project:
    proj = Project(
        pid, f"{group_path}/{rel}", dict(branches), default_branch=next(iter(branches), None)
    )
    fake.projects.append(proj)
    return proj


class Clock:
    """Fake monotonic clock; sleeping advances it, so budgets can be tested instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def http_factory(transport: Any, clock: Clock, resolver: Any = None) -> Any:
    """run() http factory: a real GuardedHttpClient whose network leg is `transport`."""

    def make(provider: Provider, limits: Limits, deadline: float) -> GuardedHttpClient:
        client = GuardedHttpClient(
            allowed_hosts=provider.allowed_hosts,
            timeout=limits.request_timeout_seconds,
            max_retries=limits.max_retries,
            backoff=limits.backoff_seconds,
            min_interval=0,
            max_body=limits.max_response_bytes,
            max_wait=60,
            resolver=resolver or (lambda host: list(PUBLIC_IP)),
            deadline=deadline,
            max_requests=limits.max_requests,
            clock=clock,
            _real_sleep=clock.sleep,
        )
        client._transport = transport  # type: ignore[method-assign]
        return client

    return make


def deep(doc: Any) -> Any:
    return copy.deepcopy(doc)
