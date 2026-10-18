---
name: repo-audit
description: Audit what this repository actually contains and update AGENT/PROJECT_CONTEXT.md and AGENT/ARCHITECTURE.md with evidence. Use when starting work in an unfamiliar area, after significant code lands, or when the context files look stale.
argument-hint: "[focus area] [quick|full]"
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# /repo-audit

**When:** context files are missing, stale, or you are about to work in an unfamiliar area.
**Input:** `$ARGUMENTS`: optional focus path and depth (`quick` default, or `full`).

## Procedure
1. Follow `AGENT/prompts/audit-repository.md` with `<focus>` and `<depth>` from the arguments.
2. Compare what you find with the current `AGENT/PROJECT_CONTEXT.md`; list every statement
   that is now wrong, missing, or unsupported.
3. Apply the updates; keep each fact labelled Verified (with `Evidence:`), Unverified, or Unknown.

## Restrictions
Read-only outside the two context files and the `CLAUDE.md` Commands table. Never run builds,
installs, or release scripts to discover behaviour. Never open secret files.

## Output
A diff of the context files plus a short list: facts added, facts corrected, still unknown.

## Verification
Run the foundation validator on the repository and include its exit code.
