import json

import pytest

from afid.classification import Classifier, glob_match
from afid.errors import ConfigError, UnsafeArchiveError
from afid.hashing import sha256_bytes, sha256_file, stable_id
from afid.licensing import Policy
from afid.models import codename_key, device_id, firmware_id
from afid.utils import jsonio
from afid.utils.paths import normalize_member, safe_join, symlink_stays_inside


def test_glob_semantics():
    assert glob_match("vendor/etc/thermal/a/b.json", ["*/etc/thermal/**"])
    assert glob_match("vendor/lib64/libthermal.so", ["*/lib64/**/*thermal*.so"])
    assert not glob_match("vendor/lib64/hw/x.so", ["*/lib64/*.so"])
    assert glob_match("product/etc/power_profile.xml", ["**/power_profile*.xml"])


def test_classifier_hal_requires_elf_and_reasons(repo):
    c = Classifier(repo.rules)
    hit = c.classify("vendor/bin/hw/android.hardware.thermal-service.qti", True)
    assert hit.category == "thermal_hal" and hit.confidence == 0.95 and hit.reasons
    # Same name but not ELF: not a HAL service.
    assert c.classify("vendor/bin/hw/android.hardware.thermal-service.qti", False) is None
    weak = c.classify("vendor/lib64/libsomethermal.so", True)
    assert weak.category == "vendor_library" and weak.confidence < 0.5
    assert "does not prove" in weak.reasons[0]


def test_classifier_soc_specific_rules_are_tagged(repo):
    hit = Classifier(repo.rules).classify("vendor/etc/thermal-engine.conf", False)
    assert hit.category == "thermal_config" and hit.soc_vendors == ["qualcomm"]


@pytest.mark.parametrize(
    "bad",
    [
        {
            "rules": [
                {
                    "id": "x",
                    "category": "nope",
                    "subcategory": "s",
                    "paths": ["*"],
                    "confidence": 1,
                    "reason": "r",
                }
            ]
        },
        {
            "rules": [
                {
                    "id": "x",
                    "category": "unknown",
                    "subcategory": "s",
                    "paths": ["*"],
                    "confidence": 2,
                    "reason": "r",
                }
            ]
        },
        {"rules": [{"id": "x"}]},
    ],
)
def test_classifier_rejects_bad_rules(bad):
    with pytest.raises(ConfigError):
        Classifier(bad)


def test_sha256_consistent(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"abc")
    assert (
        sha256_file(p)
        == sha256_bytes(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert stable_id("c", "a", "b") == stable_id("c", "a", "b") != stable_id("c", "ab", "")


def test_ids():
    assert codename_key("Mi439") == "mi439"
    assert device_id("google_pixel", "oriole") == "google_pixel_oriole"
    assert firmware_id("xiaomi_x", "V14.0.1 / TKH", "global") == "xiaomi_x__V14.0.1-TKH_global"
    with pytest.raises(ValueError):
        codename_key("../x")


def test_write_if_changed_is_deterministic(tmp_path):
    p = tmp_path / "a.json"
    assert jsonio.write_if_changed(p, {"b": 1, "a": [1, 2], "last_checked_at": "1"})
    first = p.read_bytes()
    assert not jsonio.write_if_changed(
        p, {"a": [1, 2], "b": 1, "last_checked_at": "2"}, ["last_checked_at"]
    )
    assert p.read_bytes() == first
    assert json.loads(first) == {"a": [1, 2], "b": 1, "last_checked_at": "1"}
    assert jsonio.write_if_changed(p, {"a": [1], "b": 1})


@pytest.mark.parametrize("name", ["../x", "a/../../x", "/etc/passwd", "C:\\x", "a\x00b", "..", ""])
def test_unsafe_member_names(name, tmp_path):
    with pytest.raises(UnsafeArchiveError):
        safe_join(tmp_path, name)


def test_member_normalization_and_symlinks(tmp_path):
    assert normalize_member("a/./b//c") == "a/b/c"
    assert safe_join(tmp_path, "./") == tmp_path.resolve()  # tar root entry is the root itself
    (tmp_path / "d").mkdir()
    assert symlink_stays_inside(tmp_path, tmp_path / "d" / "l", "../x")
    assert not symlink_stays_inside(tmp_path, tmp_path / "d" / "l", "../../x")
    assert symlink_stays_inside(tmp_path, tmp_path / "d" / "l", "/system/lib64/libc.so")


def test_policy_unknown_blocks_publishing(repo, tmp_path):
    pol = Policy.from_config(repo.policy, repo.allowlist)
    assert pol.status_for("a" * 64, user_supplied=False) == "unknown"
    assert not pol.can_publish("unknown") and not pol.can_publish("restricted")
    assert not pol.can_publish("user_supplied")
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "thermal.json").write_text("{}")
    assert pol.check_publish_dir(pub)


def test_policy_allowlist_requires_evidence(repo, tmp_path):
    f = tmp_path / "pub" / "ok.json"
    f.parent.mkdir()
    f.write_text("{}")
    entry = {
        "sha256": sha256_file(f),
        "license": "Apache-2.0",
        "evidence_url": "https://x",
        "reviewed_by": "someone",
        "reviewed_at": "2026-10-18",
    }
    pol = Policy.from_config(repo.policy, [entry])
    assert pol.status_for(entry["sha256"], user_supplied=True) == "allowed"
    assert pol.check_publish_dir(f.parent) == []
    with pytest.raises(ConfigError):
        Policy.from_config(repo.policy, [{**entry, "evidence_url": ""}])
    with pytest.raises(ConfigError):
        Policy.from_config({**repo.policy, "default_distribution_status": "allowed"}, [])
