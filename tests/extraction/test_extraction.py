import io
import shutil
import struct
import subprocess
import tarfile
import zipfile

import pytest

from afid.errors import (
    CorruptArchiveError,
    ToolMissingError,
    UnsafeArchiveError,
    UnsupportedFormatError,
)
from afid.extraction import archives, sparse, tools
from afid.extraction.detect import detect
from afid.extraction.pipeline import Pipeline, partition_name
from tests.conftest import build_tree, tar_tree, zip_tree

LIMITS = archives.Limits(max_members=1000, max_bytes=10 * 1024 * 1024)


def pipeline(repo, **kw):
    return Pipeline(
        repo.cache,
        repo.settings["scan"]["partitions"],
        kw.get("max_archive", 1 << 30),
        kw.get("max_bytes", 1 << 30),
        10000,
    )


def test_zip_and_tar_trees_extract(repo, tmp_path, tree):
    with pytest.raises(UnsafeArchiveError, match="escapes root"):  # fixture has an escaping link
        pipeline(repo).prepare(tar_tree(tree, tmp_path / "evil.tgz"))
    (tree / "vendor/lib64/libescape.so").unlink()
    for arch in (zip_tree(tree, tmp_path / "t.zip"), tar_tree(tree, tmp_path / "t.tgz")):
        prepared = pipeline(repo).prepare(arch)
        assert (prepared.tree / "vendor/etc/thermal_info_config.json").is_file()
        assert {p.name for p in prepared.partitions} >= {"vendor", "odm", "system"}


def test_corrupt_archives_rejected(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"PK\x03\x04" + b"\0" * 30)
    with pytest.raises(CorruptArchiveError):
        archives.extract_zip(bad, tmp_path / "o", LIMITS)
    tb = tmp_path / "bad.tar"
    tb.write_bytes(b"\0" * 257 + b"ustar" + b"\x01" * 300)
    with pytest.raises((CorruptArchiveError, UnsafeArchiveError)):
        archives.extract_tar(tb, tmp_path / "o2", LIMITS)


def test_truncated_zip_member_rejected(tmp_path, tree):
    z = zip_tree(tree, tmp_path / "t.zip")
    data = z.read_bytes()
    z.write_bytes(data[: len(data) // 2])
    with pytest.raises(CorruptArchiveError):
        archives.extract_zip(z, tmp_path / "o", LIMITS)


@pytest.mark.parametrize("name", ["../evil.txt", "a/../../evil.txt", "/abs/evil.txt"])
def test_zip_path_traversal_rejected(tmp_path, name):
    z = tmp_path / "t.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(name, "x")
    with pytest.raises(UnsafeArchiveError):
        archives.extract_zip(z, tmp_path / "out", LIMITS)
    assert not (tmp_path / "evil.txt").exists()


def test_tar_symlink_escape_and_traversal_rejected(tmp_path):
    for member in ("link", "../up"):
        t = tmp_path / f"{member.strip('./')}.tar"
        with tarfile.open(t, "w") as tf:
            info = tarfile.TarInfo(member)
            if member == "link":
                info.type, info.linkname = tarfile.SYMTYPE, "../../../etc/passwd"
                tf.addfile(info)
            else:
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))
        with pytest.raises(UnsafeArchiveError):
            archives.extract_tar(t, tmp_path / f"out-{member.strip('./')}", LIMITS)


def test_tar_device_files_skipped(tmp_path):
    t = tmp_path / "dev.tar"
    with tarfile.open(t, "w") as tf:
        info = tarfile.TarInfo("vendor/dev/null")
        info.type = tarfile.CHRTYPE
        tf.addfile(info)
    rep = archives.extract_tar(t, tmp_path / "out", LIMITS)
    assert rep.skipped and not (tmp_path / "out/vendor/dev/null").exists()


def test_zip_bomb_limits(tmp_path):
    z = tmp_path / "bomb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\0" * (2 * 1024 * 1024))
    with pytest.raises(UnsafeArchiveError):
        archives.extract_zip(z, tmp_path / "o", archives.Limits(1000, 1024 * 1024))
    with zipfile.ZipFile(tmp_path / "many.zip", "w") as zf:
        for i in range(5):
            zf.writestr(f"f{i}", "x")
    with pytest.raises(UnsafeArchiveError):
        archives.extract_zip(tmp_path / "many.zip", tmp_path / "o2", archives.Limits(3, 1 << 20))


def _make_sparse(raw: bytes, blk: int = 4096) -> bytes:
    """Encode raw (multiple of blk) as: RAW chunk, FILL chunk, DONT_CARE chunk."""
    n = len(raw) // blk
    a, b = n // 3, n // 3
    chunks = struct.pack("<HHII", sparse.RAW, 0, a, 12 + a * blk) + raw[: a * blk]
    chunks += struct.pack("<HHII", sparse.FILL, 0, b, 16) + raw[a * blk : a * blk + 4]
    chunks += struct.pack("<HHII", sparse.DONT_CARE, 0, n - a - b, 12)
    hdr = struct.pack("<IHHHHIIII", sparse.MAGIC, 1, 0, 28, 12, blk, n, 3, 0)
    return hdr + chunks


def test_sparse_roundtrip(tmp_path):
    blk, n = 4096, 9
    raw = (
        bytes(range(256)) * (3 * blk // 256)
        + b"\xab\xcd\xef\x01" * (3 * blk // 4)
        + b"\0" * (3 * blk)
    )
    src = tmp_path / "s.img"
    src.write_bytes(_make_sparse(raw, blk))
    assert detect(src) == "android_sparse"
    out = tmp_path / "r.img"
    assert sparse.unsparse(src, out, 1 << 30) == n * blk
    assert out.read_bytes() == raw


def test_sparse_corrupt_rejected(tmp_path):
    src = tmp_path / "s.img"
    src.write_bytes(
        struct.pack("<IHHHHIIII", sparse.MAGIC, 1, 0, 28, 12, 4096, 2, 1, 0)
        + struct.pack("<HHII", 0xBEEF, 0, 1, 12)
    )
    with pytest.raises(CorruptArchiveError):
        sparse.unsparse(src, tmp_path / "o.img", 1 << 30)


@pytest.mark.skipif(
    not (shutil.which("mke2fs") and shutil.which("debugfs")),
    reason="needs e2fsprogs (mke2fs, debugfs) to build and read ext4",
)
def test_ext4_image_extracted_with_debugfs(repo, tmp_path):
    src = build_tree(tmp_path / "t") / "vendor"
    img = tmp_path / "pkg" / "vendor.img"
    img.parent.mkdir()
    subprocess.run(["mke2fs", "-q", "-t", "ext4", "-d", str(src), str(img), "8M"], check=True)
    assert detect(img) == "ext4"
    prepared = pipeline(repo).prepare(img.parent)
    assert (prepared.tree / "vendor/etc/thermal_info_config.json").is_file()
    assert (prepared.tree / "vendor/lib64/libthermal_link.so").is_symlink()
    (part,) = [p for p in prepared.partitions if p.name == "vendor"]
    assert part.filesystem == "ext4" and part.extracted
    assert any(t["name"] == "debugfs" for t in prepared.tools)


def test_missing_tool_reported_not_faked(repo, tmp_path, monkeypatch):
    img = tmp_path / "pkg" / "vendor.img"
    img.parent.mkdir()
    img.write_bytes(b"\0" * 1024 + b"\xe2\xe1\xf5\xe0" + b"\0" * 4096)  # EROFS magic
    monkeypatch.setattr(tools, "which", lambda name: None)
    prepared = pipeline(repo).prepare(img.parent)
    (part,) = prepared.partitions
    assert not part.extracted and "fsck.erofs" in part.note
    with pytest.raises(ToolMissingError):
        tools.require("payload-dumper-go")


def test_unknown_format_and_size_limit(repo, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x00\x01" * 3000)
    with pytest.raises(UnsupportedFormatError):
        pipeline(repo).prepare(f)
    with pytest.raises(UnsafeArchiveError):
        pipeline(repo, max_archive=10).prepare(f)


def test_partition_names():
    assert partition_name("vendor_a.img") == "vendor"
    assert partition_name("system_ext.img.lz4") == "system_ext"
    assert partition_name("odm.raw.img") == "odm"
