"""DumprX runner guards (with a fake DumprX install), download reliability, resource limits,
classification additions and container definitions. All offline."""

from __future__ import annotations

import re
import urllib.error
from pathlib import Path

import pytest
import yaml

from afid import resources
from afid.classification import Classifier
from afid.download import HttpClient
from afid.dumprx import CREDENTIAL_FILES, MARKER, DumprX
from afid.errors import ConfigError, PolicyViolationError, ProviderError, ResourceError
from afid.hashing import sha256_file
from afid.ingest import ingest_local
from afid.parsers import configs
from tests.conftest import BUILD_PROP_SYSTEM, BUILD_PROP_VENDOR, REPO

COMMIT = "303f5bba1f583c2c857a5e11d46812361a1d4625"
# Stand-in for dumper.sh: records its environment and "extracts" a vendor partition.
FAKE_DUMPER = f"""#!/bin/bash
set -eu
here="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
mkdir -p "$here/out/vendor" "$here/out/system" "$here/out/tmp"
env > "$here/out/env.txt"
cat > "$here/out/vendor/build.prop" <<'P'
{BUILD_PROP_VENDOR}P
cat > "$here/out/system/build.prop" <<'P'
{BUILD_PROP_SYSTEM}P
echo "input=$1"
"""


def fake_install(tmp_path: Path) -> DumprX:
    d = tmp_path / "dumprx"
    d.mkdir(parents=True)
    (d / "dumper.sh").write_text(FAKE_DUMPER)
    (d / MARKER).write_text(COMMIT + "\n")
    return DumprX(d, COMMIT, sha256_file(d / "dumper.sh"), probe_network=lambda: False)


@pytest.fixture
def firmware(tmp_path: Path) -> Path:
    f = tmp_path / "in" / "firmware.zip"
    f.parent.mkdir()
    f.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    return f


def test_dumprx_runs_with_clean_environment(tmp_path, firmware, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret_value")
    monkeypatch.setenv("AFID_PUSH_TOKEN", "x")
    res = fake_install(tmp_path).run(firmware, tmp_path / "work")
    assert res.status == "ok" and res.partitions == ["system", "vendor"]
    env = (res.output_dir / "env.txt").read_text()
    assert "ghs_secret_value" not in env and "TOKEN" not in env
    assert not (res.output_dir / "tmp").exists()
    assert not (tmp_path / "dumprx" / "out").exists()  # ran in a private copy


@pytest.mark.parametrize("name", CREDENTIAL_FILES)
def test_dumprx_refuses_credential_files(tmp_path, firmware, name):
    runner = fake_install(tmp_path)
    (runner.install_dir / name).write_text("token")
    with pytest.raises(PolicyViolationError, match="credential file"):
        runner.run(firmware)


def test_dumprx_refuses_wrong_revision_url_network_and_missing(tmp_path, firmware):
    runner = fake_install(tmp_path)
    (runner.install_dir / MARKER).write_text("0" * 40)
    assert any("expected" in p for p in runner.problems())
    runner = fake_install(tmp_path / "b")
    (runner.install_dir / "dumper.sh").write_text(FAKE_DUMPER + "# modified\n")
    assert any("SHA-256" in p for p in runner.problems())
    runner = fake_install(tmp_path / "c")
    with pytest.raises(Exception, match="local file"):
        runner.run(Path("https://example.org/fw.zip"))
    runner.probe_network = lambda: True
    with pytest.raises(PolicyViolationError, match="network"):
        runner.run(firmware)
    gone = DumprX(tmp_path / "none", COMMIT, "0" * 64, probe_network=lambda: False)
    assert "not installed" in gone.problems()[0]


def test_dumprx_output_is_ingested_as_extracted_tree(repo, tmp_path, firmware):
    res = fake_install(tmp_path).run(firmware, tmp_path / "work")
    out = ingest_local(repo, res.output_dir, "dumprx")
    assert out.status == "cataloged" and out.device_id == "google_pixel_fixturecode"


def test_settings_pin_matches_worker_dockerfile():
    settings = yaml.safe_load((REPO / "config/settings.yml").read_text())["dumprx"]
    worker = (REPO / ".docker/afid-firmware-worker.Dockerfile").read_text()
    assert f"ARG DUMPRX_COMMIT={settings['commit']}" in worker
    assert f"ARG DUMPER_SHA256={settings['dumper_sha256']}" in worker
    assert settings["require_offline"] is True and settings["license"] == "GPL-3.0-only"


# ---- downloads ---------------------------------------------------------------------------
class Stream:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self.body, self.headers, self.status = body, headers, 200

    def geturl(self):
        return "https://example.org/f"

    def read(self, n=-1):
        b, self.body = (
            self.body[: n if n > 0 else None],
            self.body[n if n > 0 else len(self.body) :],
        )
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client():
    c = HttpClient(frozenset({"example.org"}), max_retries=1, backoff=0, min_interval=0)
    c.sleep = lambda s: None
    return c


def test_download_rejects_html_oversize_and_truncation(monkeypatch, tmp_path):
    dest = tmp_path / "f.zip"
    monkeypatch.setattr(
        HttpClient, "_open", lambda s, r: Stream(b"<html>", {"Content-Type": "text/html"})
    )
    with pytest.raises(ProviderError, match="HTML page"):
        _client().download("https://example.org/f", dest, 100)
    monkeypatch.setattr(
        HttpClient, "_open", lambda s, r: Stream(b"x" * 50, {"Content-Length": "500"})
    )
    with pytest.raises(ProviderError, match="exceeds limit"):
        _client().download("https://example.org/f", dest, 100)
    monkeypatch.setattr(HttpClient, "_open", lambda s, r: Stream(b"x" * 500, {}))
    with pytest.raises(ProviderError, match="exceeds 100 bytes"):
        _client().download("https://example.org/f", dest, 100)
    monkeypatch.setattr(
        HttpClient, "_open", lambda s, r: Stream(b"x" * 10, {"Content-Length": "20"})
    )
    with pytest.raises(ProviderError, match="truncated"):
        _client().download("https://example.org/f", dest, 100)
    assert not dest.exists() and not dest.with_name("f.zip.part").exists()


def test_download_checks_disk_budget(monkeypatch, tmp_path):
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100, 90, 10))
    monkeypatch.setattr(
        HttpClient, "_open", lambda s, r: Stream(b"x" * 50, {"Content-Length": "50"})
    )
    with pytest.raises(ResourceError, match="reserve"):
        _client().download("https://example.org/f", tmp_path / "f", 1000, reserve_bytes=5)


def test_download_retries_then_verifies_checksum(monkeypatch, tmp_path):
    calls = []

    def flaky(self, req):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return Stream(b"firmware", {"Content-Length": "8"})

    monkeypatch.setattr(HttpClient, "_open", flaky)
    import hashlib

    want = hashlib.sha256(b"firmware").hexdigest()
    path = _client().download("https://example.org/f", tmp_path / "f", 100, want)
    assert path.read_bytes() == b"firmware" and len(calls) == 2


# ---- resource limits ---------------------------------------------------------------------
def test_limits_env_override_is_clamped(repo):
    lim = resources.limits(repo, {"AFID_MAX_ITEMS_PER_RUN": "100000", "AFID_RATE_LIMIT_DELAY": "0"})
    assert lim["MAX_ITEMS_PER_RUN"] == 256 and lim["RATE_LIMIT_DELAY"] == 0.2
    with pytest.raises(ConfigError, match="not a number"):
        resources.limits(repo, {"AFID_RETRY_LIMIT": "many"})
    with pytest.raises(ConfigError, match="negative"):
        resources.limits(repo, {"AFID_HTTP_TIMEOUT": "-1"})


def test_profile_is_sequential_on_small_machines(repo):
    m = resources.Machine(64, 4 * 1024**3, 3 * 1024**3, "/", 10**12, 10**12, 10**6)
    prof = resources.profile(m, resources.limits(repo, {"AFID_MAX_EXTRACT_PARALLEL": "2"}))
    assert prof["extract_parallel"] == 1
    with pytest.raises(ResourceError):
        resources.ensure_disk(Path("."), 10**18, 0, "test")


# ---- classification ----------------------------------------------------------------------
def test_mediatek_rules_and_false_positive_exclusions(repo):
    c = Classifier(repo.rules)
    assert (
        c.classify(
            "vendor/bin/hw/vendor.mediatek.hardware.mtkpower-service.mediatek", True
        ).category
        == "power_hal"
    )
    assert c.classify("vendor/etc/powercontable.xml", False).category == "power_config"
    assert (
        c.classify("vendor/etc/advance_thermal_mitigation/atmc.json", False).category
        == "thermal_config"
    )
    assert c.classify("vendor/bin/thermal_core", True).category == "thermal_engine"
    for fp in (
        "vendor/etc/audio_param/Power_AudioParam.xml",
        "vendor/etc/media_codecs_performance.xml",
    ):
        assert c.classify(fp, False) is None and not c.candidate(fp)
    assert c.candidate("vendor/lib64/libpowerhal.so")  # content not known yet
    assert not c.candidate("system/app/Foo/Foo.apk")


def test_yaml_config_summary_is_structural_only():
    name, s = configs.summarize(
        b"zones:\n  - name: skin\n    path: /sys/class/thermal/x\nmode: a\n",
        "generic",
        "thermal_zones.yaml",
    )
    assert name == "yaml" and s["top_level_keys"] == ["mode", "zones"]
    assert s["runtime_nodes"] == ["/sys/class/thermal/x"]
    with pytest.raises(ValueError, match="invalid YAML"):
        configs.summarize(b"a: [unclosed", "generic", "x.yaml")


# ---- container definitions ---------------------------------------------------------------
DOCKERFILES = sorted((REPO / ".docker").glob("*.Dockerfile"))


def test_five_images_defined():
    assert [p.name for p in DOCKERFILES] == [
        "afid-catalog.Dockerfile",
        "afid-discovery.Dockerfile",
        "afid-firmware-worker.Dockerfile",
        "afid-security.Dockerfile",
        "afid-validation.Dockerfile",
    ]


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.stem)
def test_dockerfile_hardening(path):
    text = path.read_text()
    for ref in re.findall(r"^ARG \w+_(?:BASE|IMAGE)=(\S+)$", text, re.M):
        assert re.search(r"@sha256:[0-9a-f]{64}$", ref), f"{ref} not pinned by digest"
    assert "USER afid" in text and "docker.sock" not in text
    assert "--privileged" not in text and "ADD http" not in text
    assert "proxy_ca" not in text.replace("--mount=type=secret,id=proxy_ca,required=false", "")


def test_worker_image_cannot_download_or_publish():
    text = (REPO / ".docker/afid-firmware-worker.Dockerfile").read_text()
    runtime = text.split("# ---- runtime", 1)[1]
    install = re.search(r"apt-get install -y --no-install-recommends(.*?)&&", runtime, re.S)
    assert install
    pkgs = set(install.group(1).replace("\\", " ").split())
    assert not pkgs & {"git", "curl", "wget", "sudo", "rar", "unrar", "p7zip-rar"}
    assert "rm -rf .git utils/android_tools/.git" in text and "utils/bin/transfer" in text
    for name in CREDENTIAL_FILES:
        assert name not in runtime


def test_runtime_lock_matches_dev_lock():
    def pins(name):
        return dict(re.findall(r"^([a-z0-9._-]+)==([^ ;\\]+)", (REPO / name).read_text(), re.M))

    runtime, dev = pins("requirements-runtime.lock"), pins("requirements.lock")
    assert {"pyyaml", "jsonschema"} <= runtime.keys()
    assert all(dev.get(k) == v for k, v in runtime.items()), "runtime and dev locks disagree"


def test_catalog_files_are_world_readable(tmp_path):
    from afid.utils import jsonio

    p = tmp_path / "x.json"
    jsonio.write_if_changed(p, {"a": 1})
    assert p.stat().st_mode & 0o777 == 0o644


def test_image_lock_lists_every_image_and_nothing_unpublished_is_referenced():
    lock = yaml.safe_load((REPO / "config/container_images.yml").read_text())
    names = {i["name"] for i in lock["images"]}
    assert names == {p.name.removesuffix(".Dockerfile") for p in DOCKERFILES}
    for img in lock["images"]:
        assert img["digest"] is None or re.fullmatch(r"sha256:[0-9a-f]{64}", img["digest"])
    published = {i["name"] for i in lock["images"] if i["digest"]}
    text = "\n".join(p.read_text() for p in (REPO / ".github/workflows").glob("*.yml"))
    for ref in re.findall(r"ghcr\.io/zairenkaiprjctx/([a-z-]+)", text, re.I):
        assert ref in published, f"workflow pulls unpublished image {ref}"


def test_firmware_download_refuses_without_allowlisted_host(repo, tmp_path, capsys):
    from afid.cli import main

    rc = main(
        [
            "--root",
            str(repo.root),
            "firmware",
            "download",
            "--url",
            "https://example.org/fw.zip",
            "--out",
            str(tmp_path / "fw.zip"),
        ]
    )
    assert rc == 3 and "no download hosts are allowed" in capsys.readouterr().err
