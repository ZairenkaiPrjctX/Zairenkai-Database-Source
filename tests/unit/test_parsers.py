import shutil
import subprocess

import pytest

from afid.parsers import buildprop, configs, elf, init_rc, vintf
from tests.conftest import ELF32, ELF64, THERMAL_RC, VINTF


def test_elf_arm64_dynamic_metadata():
    info = elf.parse_file(ELF64 / "libthermal_fixture.so")
    assert (info.elf_class, info.machine, info.endianness) == ("ELF64", "aarch64", "little")
    assert info.soname == "libthermal_fixture.so"
    assert info.needed == ["libfixture_dep.so", "libmissing_fixture.so"]


def test_elf_arm32_and_executable_interpreter():
    lib = elf.parse_file(ELF32 / "libthermal_fixture.so")
    assert (lib.elf_class, lib.machine) == ("ELF32", "arm")
    svc = elf.parse_file(ELF64 / "thermal_service")
    assert svc.interpreter == "/system/bin/linker64"
    assert svc.needed[0] == "libthermal_fixture.so"


@pytest.mark.skipif(shutil.which("readelf") is None, reason="readelf cross-check needs binutils")
@pytest.mark.parametrize("path", sorted(list(ELF64.iterdir()) + list(ELF32.iterdir())))
def test_elf_matches_readelf(path):
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
    needed = [ln.split("[")[1].rstrip("]") for ln in out.splitlines() if "(NEEDED)" in ln]
    soname = [ln.split("[")[1].rstrip("]") for ln in out.splitlines() if "(SONAME)" in ln]
    info = elf.parse_file(path)
    assert info.needed == needed
    assert ([info.soname] if info.soname else []) == soname


@pytest.mark.parametrize(
    "data", [b"", b"\x7fELF", b"\x7fELF\x02\x01" + b"\0" * 50, b"not elf at all" * 10]
)
def test_elf_malformed_rejected(data):
    with pytest.raises(elf.ElfError):
        elf.parse(data)


def test_elf_truncated_real_file_rejected():
    data = (ELF64 / "libthermal_fixture.so").read_bytes()
    with pytest.raises(elf.ElfError):
        elf.parse(data[:200])


def test_init_rc_services_triggers_and_continuation():
    doc = init_rc.parse(THERMAL_RC)
    (svc,) = doc["services"]
    assert svc["name"] == "vendor.thermal-hal"
    assert svc["binary"] == "/vendor/bin/hw/android.hardware.thermal-service.fixture"
    assert svc["classes"] == ["hal"] and svc["user"] == "system"
    assert svc["groups"] == ["system", "readproc"]  # backslash continuation joined
    assert svc["capabilities"] == ["SYS_NICE"]
    assert svc["interfaces"] == [
        {"name": "aidl", "instance": "android.hardware.thermal.IThermal/default"}
    ]
    (act,) = doc["actions"]
    assert act["property_triggers"] == ["vendor.thermal.ready=1", "sys.boot_completed=1"]
    assert act["starts"] == ["vendor.thermal-hal"]


def test_init_rc_is_data_only_and_tolerates_bad_quotes():
    doc = init_rc.parse(
        'service x /vendor/bin/x "unterminated\n    oneshot\nimport /vendor/etc/init/a.rc\n'
    )
    assert doc["services"][0]["oneshot"] and doc["imports"] == ["/vendor/etc/init/a.rc"]


def test_vintf_parse_and_dtd_rejected():
    doc = vintf.parse(VINTF.encode())
    assert [h["name"] for h in doc["hals"]] == [
        "android.hardware.thermal",
        "android.hardware.power",
    ]
    assert doc["hals"][0]["versions"] == ["2"]
    bomb = b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "aaaa">]><manifest>&a;</manifest>'
    with pytest.raises(vintf.XmlRejected):
        vintf.parse(bomb)
    with pytest.raises(vintf.XmlRejected):
        vintf.parse(b"<manifest><hal>")


def test_buildprop_keeps_only_allowlisted_non_personal_keys():
    props = buildprop.parse("ro.serialno=ABC\nro.product.device=x\n# c\nro.boot.serialno=Z\nbad\n")
    assert props == {"ro.product.device": "x"}


def test_config_summaries():
    name, s = configs.summarize(
        b'{"Sensors":[{"Name":"a"}],"CoolingDevices":[]}',
        "thermal_hal_config_json",
        "thermal_info_config.json",
    )
    assert name == "json" and s["sensors"] == ["a"]
    name, s = configs.summarize(
        b"[ZONE]\nalgo_type ss\nsensor cpu\n# x\n", "thermal_engine_conf", "thermal-engine.conf"
    )
    assert s["sections"] == ["ZONE"] and s["algo_types"] == ["ss"] and s["sensors"] == ["cpu"]
    _, s = configs.summarize(
        b"use /vendor/etc/x.json and /sys/class/thermal/tz0/temp", "generic", "thermal.conf"
    )
    assert s["partition_paths"] == ["/vendor/etc/x.json"]
    assert s["runtime_nodes"] == ["/sys/class/thermal/tz0/temp"]
    with pytest.raises(ValueError):
        configs.summarize(b"{not json", "powerhint_json", "powerhint.json")
