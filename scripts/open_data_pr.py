#!/usr/bin/env python3
"""Propose database changes as a pull request from one fixed branch per workflow.

Every workflow owns one long-lived branch (e.g. afid/updates) and reuses it on each run
instead of creating a new timestamped branch:
- the branch does not exist yet: it is created at the base commit;
- its previous pull request was merged (the branch is an ancestor of the base): it is
  fast-forwarded to the base;
- its pull request is still open: the earlier unmerged commits are kept, and the base is
  merged into the branch first if they diverged (a conflict stops the run and asks a
  maintainer to merge or close that pull request);
- it has commits but no open pull request (closed without merging, or squash-merged): the
  branch is recreated at the base, so rejected changes never come back.

The run then commits only the database/ files whose content differs from the branch, so the
pull request lists just the data files the workflow changed. One pull request per branch is
reused (title and body updated) or opened.

- Only files under database/ may be proposed; anything else aborts.
- Runs `afid database validate --check-index` and `afid policy check` first.
- Creates the commit with the GraphQL createCommitOnBranch mutation, so GitHub signs it.
- Never pushes to the base branch, never force-pushes; skips when there is no diff.
- Dispatches validate.yml on the branch (PRs opened with GITHUB_TOKEN do not trigger
  workflows by themselves; workflow_dispatch is the documented exception).

Environment: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_SHA (set by Actions), AFID_COMMIT_TRAILER.
Usage: open_data_pr.py --branch afid/updates --title "..." [--body-file report.md]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ALLOWED_PREFIX = "database/"
BRANCH = re.compile(r"^afid/[a-z0-9][a-z0-9-]{0,62}$")


class Conflict(Exception):
    """The base branch cannot be merged into the data branch automatically."""


def run(*args: str, check: bool = True) -> str:
    proc = subprocess.run(list(args), capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        sys.exit(f"command failed: {' '.join(args[:3])}...: {proc.stderr.strip()[:500]}")
    return proc.stdout


def changed_files() -> tuple[list[str], list[str]]:
    out = run("git", "status", "--porcelain", "-z", "--untracked-files=all")
    added, deleted = [], []
    for entry in filter(None, out.split("\0")):
        status, path = entry[:2], entry[3:]
        if not path.startswith(ALLOWED_PREFIX):
            sys.exit(f"refusing to propose a change outside {ALLOWED_PREFIX}: {path}")
        (deleted if "D" in status else added).append(path)
    return sorted(added), sorted(deleted)


def blob_sha(path: str) -> str:
    """Git blob id of a working-tree file, comparable with the branch's tree entries."""
    return run("git", "hash-object", "--", path).strip()


@dataclass
class GitHub:
    """The few GitHub API calls this script needs, through the gh CLI."""

    repo: str

    def _gh(self, args: Sequence[str], stdin: str | None = None, ok: Sequence[int] = ()) -> str:
        proc = subprocess.run(
            ["gh", *args], input=stdin, capture_output=True, text=True, check=False
        )
        if proc.returncode == 0:
            return proc.stdout
        if any(f"(HTTP {code})" in proc.stderr for code in ok):
            return ""
        if "(HTTP 409)" in proc.stderr:
            raise Conflict(proc.stderr.strip()[:500])
        sys.exit(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()[:500]}")

    def default_branch(self) -> str:
        return str(json.loads(self._gh(["api", f"repos/{self.repo}"]))["default_branch"])

    def ref_sha(self, branch: str) -> str | None:
        out = self._gh(["api", f"repos/{self.repo}/git/ref/heads/{branch}"], ok=(404,))
        return str(json.loads(out)["object"]["sha"]) if out else None

    def compare(self, base: str, head: str) -> str:
        """identical | ahead | behind | diverged (head relative to base)."""
        out = self._gh(["api", f"repos/{self.repo}/compare/{base}...{head}", "--jq", ".status"])
        return out.strip()

    def create_ref(self, branch: str, sha: str) -> None:
        self._gh(
            [
                "api",
                f"repos/{self.repo}/git/refs",
                "-f",
                f"ref=refs/heads/{branch}",
                "-f",
                f"sha={sha}",
            ]
        )

    def delete_ref(self, branch: str) -> None:
        self._gh(["api", "-X", "DELETE", f"repos/{self.repo}/git/refs/heads/{branch}"])

    def fast_forward(self, branch: str, sha: str) -> None:
        # force=false: GitHub refuses anything that is not a fast-forward.
        self._gh(
            [
                "api",
                "-X",
                "PATCH",
                f"repos/{self.repo}/git/refs/heads/{branch}",
                "-f",
                f"sha={sha}",
                "-F",
                "force=false",
            ]
        )

    def merge_into(self, branch: str, sha: str, message: str) -> None:
        """Merge commit `sha` into `branch`; GitHub creates the merge commit (no force-push)."""
        self._gh(
            [
                "api",
                f"repos/{self.repo}/merges",
                "-f",
                f"base={branch}",
                "-f",
                f"head={sha}",
                "-f",
                f"commit_message={message}",
            ]
        )

    def tree(self, sha: str) -> dict[str, str] | None:
        """path -> blob sha of a commit's tree; None when GitHub truncated the listing."""
        out = json.loads(self._gh(["api", f"repos/{self.repo}/git/trees/{sha}?recursive=1"]))
        if out.get("truncated"):
            return None
        return {e["path"]: e["sha"] for e in out["tree"] if e["type"] == "blob"}

    def commit(
        self,
        branch: str,
        head: str,
        headline: str,
        body: str,
        additions: list[str],
        deletions: list[str],
    ) -> str:
        mutation = """mutation($input: CreateCommitOnBranchInput!) {
          createCommitOnBranch(input: $input) { commit { oid url } } }"""
        variables = {
            "input": {
                "branch": {"repositoryNameWithOwner": self.repo, "branchName": branch},
                "expectedHeadOid": head,
                "message": {"headline": headline, "body": body},
                "fileChanges": {
                    "additions": [
                        {"path": p, "contents": base64.b64encode(Path(p).read_bytes()).decode()}
                        for p in additions
                    ],
                    "deletions": [{"path": p} for p in deletions],
                },
            }
        }
        out = self._gh(
            ["api", "graphql", "--input", "-"],
            stdin=json.dumps({"query": mutation, "variables": variables}),
        )
        return str(json.loads(out)["data"]["createCommitOnBranch"]["commit"]["oid"])

    def open_pr(self, branch: str, base: str) -> int | None:
        out = self._gh(
            [
                "pr",
                "list",
                "--repo",
                self.repo,
                "--head",
                branch,
                "--base",
                base,
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number // empty",
            ]
        ).strip()
        return int(out) if out else None

    def create_pr(self, branch: str, base: str, title: str, body: str) -> str:
        return self._gh(
            [
                "pr",
                "create",
                "--repo",
                self.repo,
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
        ).strip()

    def edit_pr(self, number: int, title: str, body: str) -> None:
        self._gh(["pr", "edit", str(number), "--repo", self.repo, "--title", title, "--body", body])

    def dispatch_validate(self, branch: str) -> None:
        subprocess.run(
            ["gh", "workflow", "run", "validate.yml", "--repo", self.repo, "--ref", branch],
            capture_output=True,
            check=False,
        )


def prepare_branch(gh: GitHub, branch: str, base_sha: str, pr: int | None) -> str:
    """Bring the data branch to a state the new commit can go on; return its head."""
    head = gh.ref_sha(branch)
    if head is None:
        gh.create_ref(branch, base_sha)
        print(f"created {branch} at {base_sha[:12]}")
        return base_sha
    status = gh.compare(base_sha, head)
    if status in ("identical", "behind"):
        if status == "behind":
            gh.fast_forward(branch, base_sha)
            print(f"fast-forwarded {branch} to {base_sha[:12]} (previous changes are merged)")
        return base_sha
    if pr is None:
        # Commits that never reached the base through an open PR: rejected or squash-merged.
        gh.delete_ref(branch)
        gh.create_ref(branch, base_sha)
        print(f"recreated {branch} at {base_sha[:12]} (it had commits but no open pull request)")
        return base_sha
    if status == "diverged":
        try:
            gh.merge_into(branch, base_sha, f"Merge {base_sha[:12]} into {branch}")
        except Conflict:
            sys.exit(
                f"{branch}: the base cannot be merged into the open pull request #{pr} "
                f"automatically. Merge or close #{pr}, then rerun this workflow."
            )
        head = gh.ref_sha(branch) or head
        print(f"merged {base_sha[:12]} into {branch} (pull request #{pr} is still open)")
    return head


def pending_changes(
    tree: dict[str, str] | None, added: list[str], deleted: list[str]
) -> tuple[list[str], list[str]]:
    """Keep only the files that differ from the branch. A truncated tree keeps everything."""
    if tree is None:
        return added, deleted
    return (
        [p for p in added if tree.get(p) != blob_sha(p)],
        [p for p in deleted if p in tree],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", required=True, help="fixed data branch, e.g. afid/updates")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file")
    ap.add_argument("--base", default=os.environ.get("AFID_BASE_BRANCH", ""))
    args = ap.parse_args()
    if not BRANCH.match(args.branch):
        sys.exit(f"--branch must look like afid/<name>, not {args.branch!r}")

    added, deleted = changed_files()
    if not added and not deleted:
        print("no database changes; no pull request created")
        return 0
    run("afid", "database", "validate", "--check-index")
    run("afid", "policy", "check")

    gh = GitHub(os.environ["GITHUB_REPOSITORY"])
    base_sha = os.environ["GITHUB_SHA"]  # the commit the changes were generated from
    base = args.base or gh.default_branch()
    if args.branch == base:
        sys.exit("the data branch must not be the base branch")
    pr = gh.open_pr(args.branch, base)
    head = prepare_branch(gh, args.branch, base_sha, pr)
    additions, deletions = pending_changes(gh.tree(head), added, deleted)

    trailer = os.environ.get("AFID_COMMIT_TRAILER", "").strip()
    body = "Generated by an AFID workflow from verified provider metadata."
    if trailer:
        body += f"\n\n{trailer}"
    if additions or deletions:
        oid = gh.commit(args.branch, head, args.title, body, additions, deletions)
        print(f"commit {oid} on {args.branch}: {len(additions)} changed, {len(deletions)} deleted")
    else:
        print(f"{args.branch} already contains these changes; nothing to commit")

    pr_body = Path(args.body_file).read_text() if args.body_file else body
    pr_body += f"\n\nFiles in this run: {len(additions)} added/changed, {len(deletions)} deleted."
    if pr is None:
        print(f"opened {gh.create_pr(args.branch, base, args.title, pr_body)}")
    else:
        gh.edit_pr(pr, args.title, pr_body)
        print(f"updated pull request #{pr}")
    gh.dispatch_validate(args.branch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
