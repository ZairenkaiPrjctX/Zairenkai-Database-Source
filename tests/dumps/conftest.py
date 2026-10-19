"""Fixtures for dump-provider tests: a repo whose dump providers talk to in-process fake
GitLab hosts, and synthetic DumprX-style dump trees."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from afid.config import Config
from afid.download import HttpClient
from tests.conftest import build_tree, write
from tests.dumps.fake_gitlab import FakeGitLab

GL = "gitlab.com"
TAD = "dumps.tadiphone.dev"
LFS = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 123456789\n"


def dump_tree(root: Path, fingerprint_suffix: str = "", brand: str = "google") -> Path:
    """A system-as-root DumprX dump: system/system/build.prop, root files under system/."""
    build_tree(root)
    (root / "system" / "system").mkdir(parents=True)
    shutil.move(root / "system" / "build.prop", root / "system" / "system" / "build.prop")
    write(root / "system" / "init.rc", "# root filesystem, not a partition\n")
    vb = root / "vendor" / "build.prop"
    text = vb.read_text().replace(
        "ro.product.vendor.brand=google", f"ro.product.vendor.brand={brand}"
    )
    if fingerprint_suffix:
        text = text.replace("release-keys", f"release-keys{fingerprint_suffix}")
    vb.write_text(text)
    write(root / "README.md", "dump readme\n")
    write(root / "aosp-device-tree" / "Android.bp", "// generated\n")
    return root


@pytest.fixture
def dumps_repo(repo: Config, monkeypatch: pytest.MonkeyPatch) -> Config:
    path = repo.root / "config" / "provider_registry.yml"
    doc = yaml.safe_load(path.read_text())
    for e in doc["providers"]:
        if e["id"] in ("android_dumps_gitlab", "tadiphone_dumps"):
            e["settings"].update({"min_projects": 1, "per_page": 2})
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    monkeypatch.setattr(HttpClient, "sleep", staticmethod(lambda s: None))
    return Config(repo.root)


@pytest.fixture
def hosts(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeGitLab]:
    fakes = {GL: FakeGitLab(GL, 13303221), TAD: FakeGitLab(TAD, 64)}

    def route(self: HttpClient, req):  # noqa: ANN001
        from urllib.parse import urlparse

        self._check_url(req.full_url)
        return fakes[urlparse(req.full_url).hostname].open(req)

    monkeypatch.setattr(HttpClient, "_open", route)
    return fakes
