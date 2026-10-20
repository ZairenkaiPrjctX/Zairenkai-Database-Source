"""scripts/open_data_pr.py: one fixed branch per workflow, reused on every run, whose pull
request carries only the data files a run changed. GitHub is faked; nothing leaves the host."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.conftest import REPO

spec = importlib.util.spec_from_file_location("open_data_pr", REPO / "scripts" / "open_data_pr.py")
assert spec and spec.loader
odp = importlib.util.module_from_spec(spec)
sys.modules["open_data_pr"] = odp  # dataclasses resolve annotations via sys.modules
spec.loader.exec_module(odp)

BASE = "b" * 40
OLD = "a" * 40


class FakeGitHub(odp.GitHub):
    """Records calls; refs and compare results are set per test."""

    def __init__(self, refs=None, status="identical", conflict=False):
        super().__init__("ZairenkaiPrjctX/Zairenkai-Database-Source")
        self.refs = dict(refs or {})
        self.status = status
        self.conflict = conflict
        self.calls: list[tuple] = []

    def ref_sha(self, branch):
        return self.refs.get(branch)

    def compare(self, base, head):
        return self.status

    def create_ref(self, branch, sha):
        self.calls.append(("create", branch, sha))
        self.refs[branch] = sha

    def delete_ref(self, branch):
        self.calls.append(("delete", branch))
        del self.refs[branch]

    def fast_forward(self, branch, sha):
        self.calls.append(("fast_forward", branch, sha))
        self.refs[branch] = sha

    def merge_into(self, branch, sha, message):
        if self.conflict:
            raise odp.Conflict("Merge conflict (HTTP 409)")
        self.calls.append(("merge", branch, sha))
        self.refs[branch] = "m" * 40


def test_new_branch_is_created_at_the_base():
    gh = FakeGitHub()
    assert odp.prepare_branch(gh, "afid/updates", BASE, pr=None) == BASE
    assert gh.calls == [("create", "afid/updates", BASE)]


def test_merged_branch_is_fast_forwarded_not_recreated():
    gh = FakeGitHub({"afid/updates": OLD}, status="behind")
    assert odp.prepare_branch(gh, "afid/updates", BASE, pr=None) == BASE
    assert gh.calls == [("fast_forward", "afid/updates", BASE)]


def test_open_pull_request_keeps_its_commits():
    gh = FakeGitHub({"afid/dumps": OLD}, status="ahead")
    assert odp.prepare_branch(gh, "afid/dumps", BASE, pr=12) == OLD
    assert gh.calls == []  # new commit goes on top of the unmerged ones
    gh = FakeGitHub({"afid/dumps": OLD}, status="diverged")
    assert odp.prepare_branch(gh, "afid/dumps", BASE, pr=12) == "m" * 40
    assert gh.calls == [("merge", "afid/dumps", BASE)]


def test_conflict_with_an_open_pull_request_stops_the_run():
    gh = FakeGitHub({"afid/dumps": OLD}, status="diverged", conflict=True)
    with pytest.raises(SystemExit, match="Merge or close #12"):
        odp.prepare_branch(gh, "afid/dumps", BASE, pr=12)
    assert ("delete", "afid/dumps") not in gh.calls  # never thrown away while a PR is open


def test_rejected_changes_do_not_come_back():
    # Commits on the branch but no open pull request: closed unmerged (or squash-merged).
    for status in ("ahead", "diverged"):
        gh = FakeGitHub({"afid/discovery": OLD}, status=status)
        assert odp.prepare_branch(gh, "afid/discovery", BASE, pr=None) == BASE
        assert gh.calls == [("delete", "afid/discovery"), ("create", "afid/discovery", BASE)]


def test_only_files_that_differ_from_the_branch_are_committed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "database").mkdir()
    same = tmp_path / "database" / "same.json"
    changed = tmp_path / "database" / "changed.json"
    same.write_text('{"a": 1}\n')
    changed.write_text('{"a": 2}\n')
    tree = {
        "database/same.json": odp.blob_sha("database/same.json"),
        "database/changed.json": "0" * 40,
        "database/gone.json": "1" * 40,
        "README.md": "2" * 40,  # unrelated files on the branch are never touched
    }
    added = ["database/changed.json", "database/same.json"]
    deleted = ["database/gone.json", "database/never-existed.json"]
    assert odp.pending_changes(tree, added, deleted) == (
        ["database/changed.json"],
        ["database/gone.json"],
    )
    assert odp.pending_changes(None, added, deleted) == (added, deleted)  # truncated tree


def test_branch_names_are_fixed_and_safe():
    for ok in ("afid/updates", "afid/dumps", "afid/dump-analysis"):
        assert odp.BRANCH.match(ok)
    for bad in ("dev", "main", "afid/", "afid/Up", "afid/a/b", "afid/-x", "refs/heads/afid/x"):
        assert not odp.BRANCH.match(bad), bad


def test_every_workflow_uses_its_own_fixed_data_branch():
    branches: dict[str, str] = {}
    for path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        text = path.read_text()
        assert "--branch-prefix" not in text, path.name
        for branch in re.findall(r"open_data_pr\.py --branch (\S+)", text):
            assert odp.BRANCH.match(branch), (path.name, branch)
            assert branch not in branches, (
                f"{branch} used by {branches.get(branch)} and {path.name}"
            )
            branches[branch] = path.name
            assert yaml.safe_load(text)["concurrency"]["group"]  # one run at a time per branch
    assert {
        "afid/updates": "check-updates.yml",
        "afid/dumps": "discover-dumps.yml",
        "afid/discovery": "source-discovery.yml",
    }.items() <= branches.items()


def test_never_force_pushes():
    source = Path(REPO / "scripts" / "open_data_pr.py").read_text()
    assert "force=true" not in source.lower()
    assert '"force=false"' in source
    assert "--force" not in source


class FakeRunGitHub(FakeGitHub):
    """Adds the PR and commit calls main() makes."""

    def __init__(self, tree, pr=None, **kw):
        super().__init__(**kw)
        self.branch_tree, self.pr = tree, pr

    def default_branch(self):
        return "dev"

    def open_pr(self, branch, base):
        return self.pr

    def tree(self, sha):
        return self.branch_tree

    def commit(self, branch, head, headline, body, additions, deletions):
        self.calls.append(("commit", branch, head, tuple(additions), tuple(deletions)))
        return "c" * 40

    def create_pr(self, branch, base, title, body):
        self.calls.append(("create_pr", branch, base))
        return "https://github.com/x/y/pull/99"

    def edit_pr(self, number, title, body):
        self.calls.append(("edit_pr", number))

    def dispatch_validate(self, branch):
        self.calls.append(("dispatch", branch))


def run_main(monkeypatch, gh, added, deleted=()):
    monkeypatch.setattr(odp, "GitHub", lambda repo: gh)
    monkeypatch.setattr(odp, "changed_files", lambda: (list(added), list(deleted)))
    monkeypatch.setattr(odp, "run", lambda *a, **k: "")  # afid validate / policy check
    monkeypatch.setattr(odp, "blob_sha", lambda p: "new" if "changed" in p else "same")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ZairenkaiPrjctX/Zairenkai-Database-Source")
    monkeypatch.setenv("GITHUB_SHA", BASE)
    monkeypatch.setattr(
        "sys.argv",
        ["open_data_pr.py", "--branch", "afid/updates", "--title", "AFID: metadata updates"],
    )
    assert odp.main() == 0


def test_second_run_reuses_the_branch_and_its_pull_request(monkeypatch):
    tree = {"database/a-changed.json": "old", "database/b.json": "same"}
    # First run: no branch yet -> created, one commit, one new pull request.
    gh = FakeRunGitHub(tree)
    run_main(monkeypatch, gh, ["database/a-changed.json", "database/b.json"])
    assert gh.calls[0] == ("create", "afid/updates", BASE)
    assert ("commit", "afid/updates", BASE, ("database/a-changed.json",), ()) in gh.calls
    assert ("create_pr", "afid/updates", "dev") in gh.calls
    # Second run while that PR (#99) is open: same branch, PR updated, no new PR or branch.
    gh = FakeRunGitHub(tree, pr=99, refs={"afid/updates": OLD}, status="ahead")
    run_main(monkeypatch, gh, ["database/a-changed.json", "database/b.json"])
    assert [c[0] for c in gh.calls] == ["commit", "edit_pr", "dispatch"]
    assert gh.calls[0] == ("commit", "afid/updates", OLD, ("database/a-changed.json",), ())


def test_nothing_new_means_no_commit_but_the_pull_request_stays(monkeypatch):
    gh = FakeRunGitHub(
        {"database/b.json": "same"}, pr=99, refs={"afid/updates": OLD}, status="ahead"
    )
    run_main(monkeypatch, gh, ["database/b.json"])
    assert [c[0] for c in gh.calls] == ["edit_pr", "dispatch"]


def test_changes_outside_database_are_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "pr-body.md").write_text("x")
    with pytest.raises(SystemExit, match="outside database/"):
        odp.changed_files()
