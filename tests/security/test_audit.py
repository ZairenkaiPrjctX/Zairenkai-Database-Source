import shutil

from afid import audit
from tests.conftest import ELF64, REPO, write


def test_repository_itself_has_no_findings():
    assert audit.scan(REPO) == []


def test_planted_problems_are_found(tmp_path):
    write(tmp_path / "src/x.py", "TOKEN = 'ghp_" + "a" * 36 + "'\n")
    write(tmp_path / "notes.txt", "-----BEGIN OPENSSH " + "PRIVATE KEY-----\n")
    shutil.copyfile(ELF64 / "libfixture_dep.so", tmp_path / "vendor_blob.so")
    write(tmp_path / "firmware.zip", "PK")
    (tmp_path / "big.json").write_bytes(b"0" * (audit.MAX_FILE_BYTES + 1))
    write(tmp_path / "tests/fixtures/ok.so", "\x7fELF")  # fixtures are allowed
    write(
        tmp_path / ".github/workflows/bad.yml",
        """
on: pull_request_target
permissions: write-all
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo ${{ secrets.TOKEN }}
""",
    )
    found = "\n".join(audit.scan(tmp_path))
    for needle in (
        "possible github_token",
        "possible private_key",
        "ELF binary outside",
        "firmware/archive",
        "exceeds",
        "pull_request_target",
        "write permissions",
        "not pinned",
        "echoes a secret",
        "no timeout-minutes",
    ):
        assert needle in found, needle
    assert "tests/fixtures/ok.so" not in found


def test_generated_python_cache_is_ignored_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(audit.shutil, "which", lambda _name: None)
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'safe'\n")
    bytecode = tmp_path / "tests" / "security" / "__pycache__" / "test_audit.cpython-313.pyc"
    bytecode.parent.mkdir(parents=True)
    bytecode.write_bytes(b"fixture ghp_" + b"a" * 36)
    pytest_cache = tmp_path / ".pytest_cache" / "v" / "cache" / "nodeids"
    pytest_cache.parent.mkdir(parents=True)
    pytest_cache.write_text("generated test cache")

    files = audit.tracked_files(tmp_path)
    assert source in files
    assert bytecode not in files
    assert pytest_cache not in files
    assert audit.scan(tmp_path) == []
