"""Shared fixtures. Every test gets an isolated repository copy (config + schemas + empty
database) and builds synthetic firmware trees from tests/fixtures. Nothing touches the network."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from afid.config import Config

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ELF64 = FIXTURES / "elf" / "arm64"
ELF32 = FIXTURES / "elf" / "arm"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "schemas", root / "schemas")
    (root / "database").mkdir()
    monkeypatch.setenv("AFID_ROOT", str(root))
    monkeypatch.setenv("AFID_LINEAGE_WIKI_DIR", str(FIXTURES / "lineage_wiki"))
    return Config(root)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def copy(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest


BUILD_PROP_VENDOR = """# vendor build properties (synthetic test fixture)
ro.product.vendor.device=fixturecode
ro.product.vendor.brand=google
ro.product.vendor.model=Pixel Fixture
ro.product.vendor.manufacturer=Google
ro.vendor.build.id=FIX1.230101.001
ro.vendor.build.security_patch=2026-09-05
ro.vendor.build.fingerprint=google/fixturecode/fixturecode:16/FIX1.230101.001/1:user/release-keys
ro.board.platform=fixtureplatform
ro.serialno=MUST-NOT-BE-STORED
"""
BUILD_PROP_SYSTEM = """ro.build.id=FIX1.230101.001
ro.build.version.release=16
ro.build.version.sdk=36
ro.build.version.security_patch=2026-09-05
ro.build.version.incremental=1
ro.product.system.device=generic
"""
THERMAL_RC = """# thermal service (fixture)
service vendor.thermal-hal /vendor/bin/hw/android.hardware.thermal-service.fixture
    class hal
    user system
    group system \\
          readproc
    capabilities SYS_NICE
    interface aidl android.hardware.thermal.IThermal/default

on property:vendor.thermal.ready=1 && property:sys.boot_completed=1
    start vendor.thermal-hal
"""
VINTF = """<manifest version="1.0" type="device">
    <hal format="aidl">
        <name>android.hardware.thermal</name>
        <version>2</version>
        <fqname>IThermal/default</fqname>
    </hal>
    <hal format="aidl">
        <name>android.hardware.power</name>
        <fqname>IPower/default</fqname>
    </hal>
</manifest>
"""
THERMAL_JSON = {
    "Sensors": [{"Name": "VIRTUAL-SKIN", "Type": "SKIN"}, {"Name": "cpu0"}],
    "CoolingDevices": [{"Name": "cpu_cluster0"}],
}
POWERHINT = {
    "Nodes": [{"Name": "CPUMin", "Path": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq"}],
    "Actions": [{"PowerHint": "LAUNCH", "Node": "CPUMin", "Duration": 500}],
}
ENGINE_CONF = """[SKIN-MONITOR]
algo_type monitor
sensor skin-therm
sampling 1000
thresholds 45000
actions shutdown
"""


def build_tree(root: Path, powerhint: bool = True, build_props: bool = True) -> Path:
    v = root / "vendor"
    if build_props:
        write(v / "build.prop", BUILD_PROP_VENDOR)
        write(root / "system" / "build.prop", BUILD_PROP_SYSTEM)
    copy(ELF64 / "thermal_service", v / "bin/hw/android.hardware.thermal-service.fixture")
    copy(ELF64 / "libthermal_fixture.so", v / "lib64/libthermal_fixture.so")
    copy(ELF64 / "libfixture_dep.so", v / "lib64/libfixture_dep.so")
    copy(ELF64 / "libthermal_fixture.so", v / "lib64/hw/thermal.fixture.so")  # same content
    copy(ELF32 / "libfixture_dep.so", v / "lib/libfixture_dep.so")
    copy(ELF64 / "libfixture_dep.so", v / "lib64/libvendor_thermalutil.so")  # name-only match
    copy(ELF64 / "libfixture_dep.so", v / "bin/hw/vendor.example.unknown-service")
    write(v / "etc/thermal_info_config.json", json.dumps(THERMAL_JSON))
    write(root / "odm/etc/thermal/thermal-engine.conf", ENGINE_CONF)
    write(v / "etc/init/android.hardware.thermal-service.fixture.rc", THERMAL_RC)
    write(v / "etc/init/unrelated.rc", "service camera /vendor/bin/camera\n    class main\n")
    write(v / "etc/vintf/manifest/thermal.xml", VINTF)
    write(v / "app/README.txt", "not a component\n")
    if powerhint:
        write(v / "etc/powerhint.json", json.dumps(POWERHINT))
    os.symlink("libthermal_fixture.so", v / "lib64/libthermal_link.so")
    os.symlink("../../../../../../etc/passwd", v / "lib64/libescape.so")
    return root


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return build_tree(tmp_path / "tree")


def zip_tree(src: Path, dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file() and not p.is_symlink():
                zf.write(p, p.relative_to(src).as_posix())
    return dest


def tar_tree(src: Path, dest: Path) -> Path:
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(src, arcname=".")
    return dest
