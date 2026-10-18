<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Policy: Git and commit signing

Canonical standard: `.github/agent-foundation/standards/git-and-commit-signing.md`.

## Workflow
- [ ] Topic branch only. Never commit to the default branch.
- [ ] Draft pull requests only. Never merge, approve, or enable auto-merge.
- [ ] No `rebase`, `--amend`, or force-push on shared branches.

## Commit trailers (agent-created commits)
```
Signed-By: <GitHub username resolved from the authenticated account>
Co-Authored-By: <model actually used, if the runtime states it> <noreply@anthropic.com>
Claude-Session: <current session URL, only if one exists>
```
`Signed-By:` is text only. It is **not** a cryptographic signature.

## Signing
- [ ] Before committing, confirm `commit.gpgsign=true` and that a test commit carries a
      `gpgsig` header (`git cat-file commit HEAD`).
- [ ] If signing fails, stop and report. Never use `--no-gpg-sign` or disable signing.
- [ ] Never call an unsigned commit signed. "Verified" on GitHub is confirmed only by looking
      at the pushed commit.
- [ ] Verify independently: `python3 <.github>/agent-foundation/scripts/verify_commit_signature.py . HEAD`.
