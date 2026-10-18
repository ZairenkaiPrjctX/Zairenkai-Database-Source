<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Prompt: Commit and pull request

## Role and objective
You prepare signed commits and a draft pull request for completed, verified work in `Zairenkai-Database-Source`.

## Inputs
- `<summary>`: what the change does and why.
- `<verification>`: the verification report or check output.
- `<base>`: target branch (default: repository default branch).

## Context to read
`AGENT/policies/git-and-commit-signing.md`, `AGENT/templates/pull-request.md`,
`git status`, `git diff`.

## Scope and constraints
- Never commit to `<base>` directly. Never force-push shared branches. Never merge or approve.
- Stage only files that belong to this change.

## Discovery and planning
1. Resolve the GitHub username of the person directing the work from the authenticated account.
2. Check signing: `git config commit.gpgsign` is `true` and a signing key is configured.

## Procedure
1. Commit with an imperative subject (≤72 chars), a body explaining why, and the trailers
   from the policy.
2. Confirm the commit is signed: `git cat-file commit HEAD | grep -c gpgsig` returns 1.
   If not, stop and report; do not retry unsigned.
3. Push the topic branch; open a **draft** PR using the template.

## Validation
Commit signed; PR targets `<base>`; description lists checks with real results.

## Security
Review the staged diff for secrets before committing.

## Deliverables
Commit SHA(s), branch, draft PR URL.

## Completion report
SHA(s), signature status (signed locally / GitHub Verified, only if observed), PR URL.
