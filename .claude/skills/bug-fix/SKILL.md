---
name: bug-fix
description: Reproduce a reported defect, identify its root cause, and fix it with a regression test. Use when something behaves incorrectly and the expected behaviour is known.
argument-hint: "<observed behaviour> / <expected behaviour> / <repro steps>"
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# /bug-fix

**When:** a defect with known expected behaviour.
**Input:** `$ARGUMENTS`: observed vs expected behaviour, reproduction details.

## Procedure
1. Follow `AGENT/playbooks/debugging.md` to reproduce and narrow the bug.
2. Follow `AGENT/prompts/bug-fix.md` to fix it.
3. If you cannot reproduce it, stop and report what you tried; do not guess-fix.

## Restrictions
Fix the cause, not the symptom. No disabling checks, blanket exception handling, or retries
to hide the failure.

## Output
Root cause (`path:line`, one sentence), the fix, the regression test.

## Verification
Show the reproduction failing before and passing after, plus other checks' results.
