#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ZairenkaiPrjctX contributors
"""Create a deterministic, SHA-256-manifested artifact archive for a Zairenkai release."""
from __future__ import annotations
import argparse, gzip, hashlib, json, os, re, tarfile, tempfile
from pathlib import Path, PurePosixPath

SHA1 = re.compile(r"^[0-9a-f]{40}$")
COMPONENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-dir', required=True, type=Path)
    ap.add_argument('--component', required=True)
    ap.add_argument('--repository', required=True)
    ap.add_argument('--source-commit', required=True)
    ap.add_argument('--version', required=True)
    ap.add_argument('--output-dir', required=True, type=Path)
    ns = ap.parse_args()
    root = ns.source_dir.resolve()
    if not root.is_dir(): raise SystemExit(f'not a directory: {root}')
    if not SHA1.fullmatch(ns.source_commit): raise SystemExit('source-commit must be a full lowercase SHA-1')
    if not COMPONENT.fullmatch(ns.component): raise SystemExit('invalid component id')
    if not re.fullmatch(r'[A-Za-z0-9_.+:-]{1,100}', ns.version): raise SystemExit('invalid version')
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', ns.repository): raise SystemExit('invalid repository owner/name')
    files = []
    for p in sorted(root.rglob('*')):
        if p.is_symlink(): raise SystemExit(f'symlink is forbidden in artifact input: {p}')
        if not p.is_file(): continue
        rel = p.relative_to(root).as_posix()
        pure = PurePosixPath(rel)
        if pure.is_absolute() or '..' in pure.parts or not re.fullmatch(r'[A-Za-z0-9._+/-]+', rel):
            raise SystemExit(f'unsafe artifact path: {rel!r}')
        files.append({'path': rel, 'size_bytes': p.stat().st_size, 'sha256': sha256_file(p),
                      'executable': bool(p.stat().st_mode & 0o111)})
    if not files: raise SystemExit(f'no regular files under {root}')
    ns.output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f'zairenkai-artifact-{ns.component}-{ns.source_commit}.tar.gz'
    archive_path = ns.output_dir / archive_name
    # Build a deterministic gzip/tar: stable ordering, no timestamps/owners, normalized modes.
    with archive_path.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tar:
                for entry in files:
                    p = root / entry['path']
                    info = tarfile.TarInfo(entry['path'])
                    info.size = p.stat().st_size
                    info.mode = 0o755 if entry['executable'] else 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = 0
                    with p.open('rb') as f: tar.addfile(info, f)
    manifest = {
        'schema_version': 1,
        'repository': ns.repository,
        'component': ns.component,
        'source_commit': ns.source_commit,
        'version': ns.version,
        'archive_format': 'tar.gz',
        'assets': [{'name': archive_name, 'size_bytes': archive_path.stat().st_size, 'sha256': sha256_file(archive_path)}],
        'files': files,
    }
    manifest_path = ns.output_dir / 'artifact-manifest.json'
    raw_manifest = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    manifest_path.write_bytes(raw_manifest)
    (ns.output_dir / 'artifact-manifest.sha256').write_text(f'{sha256_bytes(raw_manifest)}  artifact-manifest.json\n', encoding='utf-8')
    print(json.dumps({'repository':ns.repository,'component':ns.component,'source_commit':ns.source_commit,
                      'version':ns.version,'archive':archive_name,'size_bytes':archive_path.stat().st_size,
                      'sha256':sha256_file(archive_path),'manifest_sha256':sha256_bytes(raw_manifest),
                      'file_count':len(files)}, indent=2))
    return 0

if __name__ == '__main__': raise SystemExit(main())
