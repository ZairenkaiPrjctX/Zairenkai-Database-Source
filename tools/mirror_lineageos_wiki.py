#!/usr/bin/env python3
"""Mirror licensed LineageOS device YAML files with immutable per-snapshot provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

UPSTREAM = "https://github.com/LineageOS/lineage_wiki"
DATA_PATH = "_data/devices"
LICENSE = "CC-BY-SA-3.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
MAX_FILES = 1500
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MIN_FILES = 100
NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}\.yml$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


class MirrorError(ValueError):
    """The upstream checkout or existing mirror is incomplete or unsafe."""


def _head(upstream: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MirrorError(f"cannot read upstream Git revision: {exc}") from exc
    revision = result.stdout.strip()
    if not REVISION.fullmatch(revision):
        raise MirrorError("upstream checkout did not resolve to a full Git commit")
    try:
        remote = subprocess.run(
            ["git", "-C", str(upstream), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise MirrorError(f"cannot verify upstream Git remote: {exc}") from exc
    if remote.removesuffix(".git").lower() != UPSTREAM.lower():
        raise MirrorError("upstream checkout is not the official LineageOS Wiki repository")
    return revision


def _tree_blobs(upstream: Path) -> dict[str, tuple[str, str, str]]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(upstream),
                "ls-tree",
                "-r",
                "-z",
                "HEAD",
                "--",
                DATA_PATH,
                "_includes/layout/footer.html",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MirrorError(f"cannot verify upstream Git tree: {exc}") from exc
    tree: dict[str, tuple[str, str, str]] = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        tree[raw_path.decode("utf-8")] = (mode, kind, object_id)
    return tree


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data,
        usedforsecurity=False,
    ).hexdigest()


def _load_documents(upstream: Path) -> tuple[str, dict[str, bytes]]:
    data_dir = upstream / DATA_PATH
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise MirrorError(f"upstream has no safe {DATA_PATH}/ directory")
    revision = _head(upstream)
    tree = _tree_blobs(upstream)
    try:
        footer = subprocess.run(
            ["git", "-C", str(upstream), "show", "HEAD:_includes/layout/footer.html"],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise MirrorError("upstream license evidence footer is missing or unsafe") from exc
    if len(footer) > 65_536:
        raise MirrorError("upstream license evidence footer exceeds the size limit")
    if tree.get("_includes/layout/footer.html") != ("100644", "blob", _git_blob_sha(footer)):
        raise MirrorError("upstream license footer does not match the pinned Git commit")
    footer_text = footer.decode("utf-8", errors="replace")
    if (
        "creativecommons.org/licenses/by-sa/3.0/" not in footer_text
        or "CC BY-SA 3.0" not in footer_text
    ):
        raise MirrorError("upstream footer no longer declares CC BY-SA 3.0")
    paths = sorted(data_dir.glob("*.yml"))
    if not MIN_FILES <= len(paths) <= MAX_FILES:
        raise MirrorError(
            f"unexpected upstream file count: {len(paths)} (expected {MIN_FILES}..{MAX_FILES})"
        )

    files: dict[str, bytes] = {}
    total_bytes = 0
    for path in paths:
        name = path.name
        if not NAME.fullmatch(name) or path.is_symlink() or not path.is_file():
            raise MirrorError(f"unsafe upstream device filename: {name!r}")
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise MirrorError(f"unexpected size for {name}: {len(raw)} bytes")
        if tree.get(f"{DATA_PATH}/{name}") != ("100644", "blob", _git_blob_sha(raw)):
            raise MirrorError(
                f"upstream file is not the committed regular file at this revision: {name}"
            )
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_BYTES:
            raise MirrorError("upstream device data exceeds the 64 MiB mirror limit")
        try:
            document = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise MirrorError(f"invalid upstream YAML in {name}: {exc}") from exc
        if not isinstance(document, dict) or not all(
            isinstance(document.get(field), str) and document[field].strip()
            for field in ("codename", "name", "vendor")
        ):
            raise MirrorError(f"missing required device identity fields in {name}")
        if len(document["codename"]) > 128:
            raise MirrorError(f"invalid codename in {name}")
        files[name] = raw
    return revision, files


def _safe_manifest(output: Path) -> dict:
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        return {"files": []}
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MirrorError("existing manifest is not a regular file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MirrorError(f"cannot parse existing source manifest: {exc}") from exc
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise MirrorError("existing source manifest has an unsupported schema")
    names = [entry.get("path") for entry in manifest["files"] if isinstance(entry, dict)]
    if (
        len(names) != len(manifest["files"])
        or any(not isinstance(name, str) or not NAME.fullmatch(name) for name in names)
        or len(names) != len(set(names))
    ):
        raise MirrorError("existing source manifest contains unsafe or duplicate paths")
    return manifest


def _validate_output(output: Path, manifest: dict) -> None:
    if output.is_symlink() or not output.is_dir():
        raise MirrorError("source mirror directory is missing or is a symlink")
    devices = output / "devices"
    if devices.is_symlink() or not devices.is_dir():
        raise MirrorError("source devices directory is missing or is a symlink")
    entries = {entry["path"]: entry for entry in manifest["files"]}
    actual = {path.name for path in devices.iterdir() if path.is_file() or path.is_symlink()}
    if actual != set(entries):
        raise MirrorError("source mirror files do not match manifest")
    for name, entry in entries.items():
        path = devices / name
        if path.is_symlink() or not path.is_file():
            raise MirrorError(f"unsafe mirrored file: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.get("sha256"):
            raise MirrorError(f"SHA-256 mismatch for mirrored file: {name}")
        url = f"{UPSTREAM}/blob/{manifest.get('source_revision')}/{DATA_PATH}/{name}"
        if entry.get("source_url") != url:
            raise MirrorError(f"source URL mismatch for mirrored file: {name}")


def check(output: Path) -> dict:
    manifest = _safe_manifest(output)
    if manifest.get("source_repository") != UPSTREAM or manifest.get("license") != LICENSE:
        raise MirrorError("manifest source or license is not the approved LineageOS source")
    if not isinstance(manifest.get("source_revision"), str) or not REVISION.fullmatch(
        manifest["source_revision"]
    ):
        raise MirrorError("manifest has no immutable source revision")
    _validate_output(output, manifest)
    return manifest


def mirror(upstream: Path, output: Path) -> dict:
    """Copy validated source files; delete only stale files previously owned by this manifest."""
    revision, files = _load_documents(upstream)
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise MirrorError("source mirror output must be a real directory")
    old_manifest = _safe_manifest(output) if output.exists() else {"files": []}
    if output.exists():
        old_devices = output / "devices"
        if old_devices.exists() and (old_devices.is_symlink() or not old_devices.is_dir()):
            raise MirrorError("existing source devices path is unsafe")
        managed = {entry["path"] for entry in old_manifest["files"]}
        if old_devices.exists():
            existing = list(old_devices.iterdir())
            if any(path.is_symlink() or not path.is_file() for path in existing):
                raise MirrorError("existing source devices directory contains an unsafe entry")
            if {path.name for path in existing} != managed:
                raise MirrorError("existing source devices directory contains unmanaged files")
        for name in files:
            dest = old_devices / name
            if dest.exists() and name not in managed and dest.read_bytes() != files[name]:
                raise MirrorError(f"refusing to overwrite an untracked source file: {name}")
    else:
        managed = set()

    output.mkdir(parents=True, exist_ok=True)
    devices = output / "devices"
    devices.mkdir(exist_ok=True)
    for name, raw in files.items():
        dest = devices / name
        if dest.is_symlink():
            raise MirrorError(f"refusing to overwrite a symlink: {name}")
        dest.write_bytes(raw)
    for stale in managed - files.keys():
        dest = devices / stale
        if dest.is_symlink():
            raise MirrorError(f"refusing to remove a symlink: {stale}")
        if dest.exists():
            dest.unlink()

    entries = [
        {
            "path": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob_sha1": _git_blob_sha(raw),
            "source_url": f"{UPSTREAM}/blob/{revision}/{DATA_PATH}/{name}",
        }
        for name, raw in sorted(files.items())
    ]
    manifest = {
        "schema_version": 1,
        "source_repository": UPSTREAM,
        "source_revision": revision,
        "source_path": DATA_PATH,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "license_evidence_url": f"{UPSTREAM}/blob/{revision}/_includes/layout/footer.html",
        "attribution": "The LineageOS Project",
        "files": entries,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _validate_output(output, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("source-files/lineageos_wiki"))
    parser.add_argument("--check", action="store_true", help="validate an existing mirror")
    args = parser.parse_args()
    if args.check:
        if args.upstream_dir is not None:
            parser.error("--upstream-dir cannot be combined with --check")
        manifest = check(args.output_dir)
    else:
        if args.upstream_dir is None:
            parser.error("--upstream-dir is required unless --check is used")
        manifest = mirror(args.upstream_dir, args.output_dir)
    print(
        f"LineageOS source mirror: {len(manifest['files'])} files at {manifest['source_revision']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MirrorError as exc:
        sys.exit(f"source mirror refused: {exc}")
