---
name: test-and-verify
description: Run the repository's configured checks against a change and produce a verification report that separates configured, executed, and passing. Use before opening a PR or when asked whether a change works.
argument-hint: "[branch, commit range, or description of the change]"
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# /test-and-verify

**When:** before a PR, or to answer "does this work?".
**Input:** `$ARGUMENTS`: the change (default: working tree vs. default branch).

## Procedure
1. Read the Commands table in `CLAUDE.md`. Those are the only checks you may treat as the
   repository's own.
2. Follow `AGENT/prompts/test-and-verify.md`.
3. Run the foundation validator if any `CLAUDE.md`, `AGENTS.md`, `AGENT/`, or `.claude/`
   file changed.

## Restrictions
Do not edit product code. Do not skip or weaken checks. Do not run release, deploy, or
device-writing commands.

## Output
A filled `AGENT/templates/verification-report.md` with a verdict:
Verified / Partially verified / Not verified.

## Verification
Every "passing" entry has a command and output; nothing executed is reported as passing.
