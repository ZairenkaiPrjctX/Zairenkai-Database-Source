---
name: release-readiness
description: Assess whether a revision is ready to release and return a pass/fail/not-configured checklist. Use before a human tags or publishes. Never tags, publishes, or signs anything itself.
argument-hint: "<revision> <version> [channel]"
disable-model-invocation: true
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# /release-readiness

**When:** a human is considering a release.
**Input:** `$ARGUMENTS`: candidate revision, intended version, optional channel.

## Procedure
1. Look for the release process in `AGENT/PROJECT_CONTEXT.md` and
   `AGENT/playbooks/release-process.md`. If none is defined, the verdict is
   **Not Configured**; list what must be decided and stop.
2. Otherwise follow `AGENT/prompts/release-readiness.md`.

## Restrictions
Never tag, push tags, publish, upload, sign artifacts, or deploy.

## Output
Checklist (CI, versions, changelog, artifact provenance, signing configuration, rollback)
with pass / fail / not configured and a verdict: Ready / Not ready / Not Configured.

## Verification
Every "pass" cites evidence (CI run, file, command output).
