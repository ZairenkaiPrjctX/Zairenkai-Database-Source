<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Policy: Git and commit signing

Canonical standard: `.github/agent-foundation/standards/git-and-commit-signing.md`.

## Workflow
- [ ] Topic branch only. Never commit to the default branch.
- [ ] Draft pull requests only. Never merge, approve, or enable auto-merge.
- [ ] No `rebase`, `--amend`, or force-push on shared branches.

## Commit trailers
Every commit ends with:
```
Signed-off-by: FebriCahyaa <febricahya12345@gmail.com>
```
Agent-created commits add:
```
Co-Authored-By: <model actually used, if the runtime states it> <noreply@anthropic.com>
Claude-Session: <current session URL, only if one exists>
```
Write the `Signed-off-by` line explicitly; `git commit -s` would use the agent's identity.
`Signed-off-by:` is text only. It is **not** a cryptographic signature.

## Signing
- [ ] Before committing, confirm `commit.gpgsign=true` and that a test commit carries a
      `gpgsig` header (`git cat-file commit HEAD`).
- [ ] If signing fails, stop and report. Never use `--no-gpg-sign` or disable signing.
- [ ] Never call an unsigned commit signed. "Verified" on GitHub is confirmed only by looking
      at the pushed commit.
- [ ] Verify against trusted keys (`<.github>` = path to a checkout of `ZairenkaiPrjctX/.github`):
      `git -c gpg.ssh.allowedSignersFile=<.github>/agent-foundation/allowed_signers verify-commit HEAD`
      or `python3 <.github>/agent-foundation/scripts/verify_commit_signature.py . HEAD --allowed-signers <.github>/agent-foundation/allowed_signers`.
