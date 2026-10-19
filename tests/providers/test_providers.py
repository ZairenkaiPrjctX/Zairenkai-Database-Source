import urllib.error

import pytest

from afid.download import HttpClient
from afid.errors import CapabilityError, ProviderError
from afid.providers import registry
from afid.providers.base import Release


def test_registry_entries_match_implementations(repo):
    for e in registry.entries(repo):
        assert registry.self_test(repo, e) == [], e["id"]
    ids = {e["id"] for e in registry.entries(repo)}
    assert set(repo.core_brand_ids) <= ids  # one provider per core brand


def test_no_provider_claims_download(repo):
    for e in registry.entries(repo):
        prov = registry.build(repo, e)
        assert not prov.capabilities().download
        with pytest.raises(CapabilityError, match=e["id"]):
            prov.download(Release(e["id"], "x", "y", None, None, None), repo.cache)


def test_registry_rejects_bad_entries(repo):
    repo.providers  # load
    bad = dict(
        repo.providers[0], capabilities={**repo.providers[0]["capabilities"], "download": True}
    )
    assert registry.self_test(repo, bad)
    with pytest.raises(Exception, match="afid.providers"):
        registry._load_class("os.system")


def test_pixel_filename_hints_are_hints(repo):
    prov = registry.get(repo, "google_pixel")
    h = prov.filename_hints("oriole-ap2a.240805.005-factory-0123abcd.zip")
    assert h == {
        "package_type": "factory_image",
        "codename": "oriole",
        "build_id": "AP2A.240805.005",
        "basis": "file name pattern (hint)",
    }
    assert prov.filename_hints("random.zip") == {}


def test_lineage_discovery_from_fixture(repo):
    res = registry.get(repo, "lineageos_wiki").discover_devices()
    by = {c.item_id: c for c in res.candidates}
    assert set(by) == {"fixpix", "Fix439_variant1", "Fix439_variant2", "fixpoco"}
    assert res.skipped == 2  # Nexus (Google, not Pixel) and Motorola are out of scope
    assert res.status == "partial" and any("broken.yml" in e for e in res.errors)
    assert by["fixpix"].brand_id == "google_pixel" and by["fixpix"].model_numbers == [
        "GFX01",
        "GFX02",
    ]
    assert by["fixpix"].soc["vendor"] == "google"
    assert by["Fix439_variant1"].brand_id == by["Fix439_variant2"].brand_id == "redmi"
    assert by["Fix439_variant2"].release_date == "2019-10-09"
    assert by["fixpoco"].brand_id == "poco" and "prefix 'POCO'" in by["fixpoco"].brand_inference
    assert by["fixpoco"].soc["architecture"] == "arm64"
    assert by["fixpix"].evidence["evidence_type"] == "community_repository"


class FakeResp:
    def __init__(self, body=b"ok", status=200, headers=None):
        self.body, self.status = body, status
        self.headers = headers if headers is not None else {"ETag": '"x"'}

    def geturl(self):
        return "https://example.org/x"

    def read(self, n=-1):
        b, self.body = self.body, b""
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def client(**kw):
    c = HttpClient(
        allowed_hosts=frozenset({"example.org"}), max_retries=2, backoff=0, min_interval=0, **kw
    )
    c.sleep = lambda s: None
    return c


def test_http_only_https_and_allowed_hosts():
    with pytest.raises(ProviderError, match="non-HTTPS"):
        client().get("http://example.org/x")
    with pytest.raises(ProviderError, match="allowed hosts"):
        client().get("https://evil.example/x")


def test_http_retries_then_succeeds(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return FakeResp(b"data")

    monkeypatch.setattr(HttpClient, "_open", lambda self, req: fake(req, 1))
    assert client().get("https://example.org/x").body == b"data"
    assert len(calls) == 3


def test_http_gives_up_and_redacts_token(monkeypatch):
    def fake(req, timeout):
        raise urllib.error.URLError("boom secret-token-123")

    monkeypatch.setattr(HttpClient, "_open", lambda self, req: fake(req, 1))
    with pytest.raises(ProviderError) as exc:
        client(token="secret-token-123").get("https://example.org/x")
    assert "secret-token-123" not in str(exc.value)


def test_http_304_and_download_checksum(monkeypatch, tmp_path):
    def not_mod(req, timeout):
        assert req.headers["If-none-match"] == '"x"'
        raise urllib.error.HTTPError(req.full_url, 304, "nm", {}, None)

    monkeypatch.setattr(HttpClient, "_open", lambda self, req: not_mod(req, 1))
    assert client().get("https://example.org/x", etag='"x"').not_modified
    monkeypatch.setattr(HttpClient, "_open", lambda self, req: FakeResp(b"abc"))
    with pytest.raises(ProviderError, match="mismatch"):
        client().download("https://example.org/f", tmp_path / "f", 100, "0" * 64)
    assert not (tmp_path / "f").exists()
