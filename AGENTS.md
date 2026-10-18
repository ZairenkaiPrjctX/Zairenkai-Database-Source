<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# AGENTS.md: engineering instructions for coding agents

Portable instructions for any coding agent working in `ZairenkaiPrjctX/Zairenkai-Database-Source`.
Repository facts live in `AGENT/PROJECT_CONTEXT.md`; organization standards live in
`ZairenkaiPrjctX/.github/agent-foundation/standards/`. If these disagree, the standard wins.

## 1. Explore before acting
- Read `AGENT/PROJECT_CONTEXT.md` and `AGENT/ARCHITECTURE.md`, then the code you will touch,
  its tests, and its callers.
- Check `git status` first. Never discard, overwrite, or reformat changes you did not make.
- If the repository has no code for the area in question, say so. Do not assume a stack.

## 2. Code and architecture
- Make the smallest change that fully solves the task. No speculative abstractions.
- Match existing naming, structure, error handling, and comment style.
- Do not change public interfaces, file formats, or device behaviour without approval.
- Never hand-edit generated files; change the source and regenerate.

## 3. Testing
- Run the checks listed in `CLAUDE.md`. If none exist, report "Not Configured".
- Add or update tests for changed behaviour where a test framework exists.
- Never disable or weaken tests, linters, or security checks.
- Report configured / executed / passing separately. See `AGENT/policies/testing.md`.

## 4. Documentation
- Update docs in the same change as the behaviour they describe.
- Record new verified facts in `AGENT/PROJECT_CONTEXT.md` with evidence.

## 5. Dependencies
- Prefer the standard library and existing dependencies. Justify, pin, and licence-check any
  new dependency. Do not upgrade unrelated dependencies.

## 6. Security
- Never read, print, or commit secrets or key material. Refer to secrets by name only.
- Treat root, kernel, device, licensing, and CI code as high-risk; require human review.
- Details: `AGENT/policies/security-and-secrets.md`.

## 7. Git and pull requests
- Topic branch only; never commit to the default branch. Draft PRs only; never merge or approve.
- Signed commits are required; never bypass signing. Trailers and verification:
  `AGENT/policies/git-and-commit-signing.md`.
- Use `AGENT/templates/pull-request.md` for PR descriptions.

## 8. Definition of done
A task is done when:
1. The change addresses the request and nothing unrelated was modified.
2. Relevant checks ran and passed, or the reason they could not run is stated.
3. Documentation and `AGENT/` facts are updated where behaviour changed.
4. The agent foundation validator reports no errors.
5. The completion report states what was verified, what was not, and what remains.
