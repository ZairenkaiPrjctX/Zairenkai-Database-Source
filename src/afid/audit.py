"""Repository security audit: secrets, payloads, large files, workflow risks.

Scans files tracked by git (or all files when git is unavailable), excluding .git and cache.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

from afid.classification import glob_match

SECRET_PATTERNS = {
    "github_token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
}
PAYLOAD_MAGIC = {
    b"\x7fELF": "ELF binary",
    b"CrAU": "payload.bin",
    b"ANDROID!": "boot image",
    b"\x3a\xff\x26\xed": "sparse image",
}
ARCHIVE_EXT = (".zip", ".tgz", ".tar", ".tar.gz", ".tar.md5", ".img", ".bin", ".lz4", ".apk")
MAX_FILE_BYTES = 5 * 1024 * 1024
# Generated state must never be scanned as source. A ZIP export has no `.git` index, so the
# fallback crawler must reproduce Git's usual cache exclusions itself.
CACHE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".afid-cache",
    ".tox",
    ".nox",
    ".venv",
}
CACHE_SUFFIXES = {".pyc", ".pyo"}
# Small, self-built test fixtures may contain binaries (see tests/fixtures/README.md).
FIXTURE_GLOBS = ["tests/fixtures/**"]
SELF = {"src/afid/audit.py", "tests/security/test_audit.py"}


def _is_generated_cache(path: Path, root: Path) -> bool:
    """Whether a repository-relative path is generated Python/tool cache, not source."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in CACHE_DIRS for part in rel.parts) or path.suffix.lower() in CACHE_SUFFIXES


def tracked_files(root: Path) -> list[Path]:
    candidates: list[Path]
    if shutil.which("git") and (root / ".git").exists():
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            candidates = [root / p for p in proc.stdout.decode().split("\0") if p]
        else:
            candidates = list(root.rglob("*"))
    else:
        candidates = list(root.rglob("*"))
    return sorted(
        p for p in candidates
        if p.is_file()
        and not p.is_symlink()
        and ".git" not in p.parts
        and not _is_generated_cache(p, root)
    )


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(tracked_files(root)):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        fixture = glob_match(rel, FIXTURE_GLOBS)
        if size > MAX_FILE_BYTES:
            findings.append(
                f"{rel}: {size} bytes exceeds {MAX_FILE_BYTES} (use releases/LFS "
                "only for allowlisted payloads)"
            )
        head = path.read_bytes()[:8]
        for magic, what in PAYLOAD_MAGIC.items():
            if head.startswith(magic) and not fixture:
                findings.append(
                    f"{rel}: {what} outside tests/fixtures (payloads are not committed)"
                )
        if rel.lower().endswith(ARCHIVE_EXT) and not fixture:
            findings.append(f"{rel}: firmware/archive file type outside tests/fixtures")
        if rel in SELF or size > MAX_FILE_BYTES:
            continue
        text = path.read_bytes().decode("utf-8", "ignore")
        for name, rx in SECRET_PATTERNS.items():
            if rx.search(text):
                findings.append(f"{rel}: possible {name}")
    findings += workflow_risks(root)
    return findings


_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def workflow_risks(root: Path) -> list[str]:
    out: list[str] = []
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        rel = wf.relative_to(root).as_posix()
        try:
            doc = yaml.safe_load(wf.read_text())
        except yaml.YAMLError as exc:
            out.append(f"{rel}: invalid YAML ({exc})")
            continue
        if not isinstance(doc, dict):
            out.append(f"{rel}: not a mapping")
            continue
        triggers = doc.get("on", doc.get(True))  # YAML 1.1 parses bare `on` as True
        names = triggers if isinstance(triggers, (list, dict)) else [triggers]
        if "pull_request_target" in names:
            out.append(f"{rel}: uses pull_request_target")
        if "permissions" not in doc:
            out.append(f"{rel}: no top-level permissions block (defaults may be write)")
        elif doc["permissions"] in ("write-all",) or (
            isinstance(doc["permissions"], dict)
            and any(v == "write" for v in doc["permissions"].values())
        ):
            out.append(f"{rel}: write permissions at workflow level; grant per job instead")
        for job_name, job in (doc.get("jobs") or {}).items():
            if "uses" in job:  # reusable-workflow call: GitHub forbids timeout-minutes here
                if not str(job["uses"]).startswith("./.github/workflows/"):
                    out.append(f"{rel}: job '{job_name}' calls a non-local reusable workflow")
                continue
            if "timeout-minutes" not in job:
                out.append(f"{rel}: job '{job_name}' has no timeout-minutes")
            for step in job.get("steps") or []:
                uses = step.get("uses")
                if uses and not uses.startswith("./") and not _PINNED.match(uses):
                    out.append(
                        f"{rel}: job '{job_name}' action '{uses}' not pinned to a commit SHA"
                    )
                run = step.get("run") or ""
                if re.search(r"echo[^\n]*\$\{\{\s*secrets\.", run):
                    out.append(f"{rel}: job '{job_name}' echoes a secret")
    return out
