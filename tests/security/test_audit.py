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
