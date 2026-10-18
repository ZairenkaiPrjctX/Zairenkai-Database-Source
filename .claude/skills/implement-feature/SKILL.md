---
name: implement-feature
description: Implement a new feature against explicit acceptance criteria with tests, docs, and a verification report. Use when asked to add or extend behaviour (not for bug fixes or pure refactors).
argument-hint: "<feature description and acceptance criteria>"
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# /implement-feature

**When:** adding or extending behaviour.
**Input:** `$ARGUMENTS`: the feature and its acceptance criteria. If criteria are missing or
untestable, ask for them before writing code.

## Procedure
1. Fill `AGENT/templates/task-brief.md` from the arguments (in your response, not a file).
2. Follow `AGENT/prompts/implement-feature.md` end to end.
3. For changes to public interfaces, root/kernel code, or licensing, present the
   implementation plan and wait for approval before editing.

## Restrictions
No new dependencies, interface changes, or unrelated refactors without approval. Preserve
uncommitted work you did not create.

## Output
The change, plus a filled `AGENT/templates/verification-report.md` mapping each criterion
to evidence.

## Verification
Repository checks from `CLAUDE.md` executed with results shown, or "Not Configured" stated.
