<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Prompt: Bug fix

## Role and objective
You are a debugging engineer on `Zairenkai-Database-Source`. Find the root cause of `<bug>` and fix it with
a minimal change, proving the fix with a reproduction.

## Inputs
- `<bug>`: observed behaviour.
- `<expected>`: correct behaviour.
- `<reproduction>`: steps, logs, device/OS/version details if known.
- `<suspected_area>`: optional.

## Context to read
`AGENT/playbooks/debugging.md`, the code on the failing path, recent commits touching it
(`git log -p -- <path>`).

## Scope and constraints
- Fix the cause, not the symptom. Do not paper over it with retries, broad catches, or by
  disabling a check.
- Keep the diff to what the fix needs.

## Discovery and planning
1. Reproduce the bug. If you cannot, report what you tried before changing code.
2. Trace from the symptom to the cause; state the cause in one sentence with the path:line.

## Procedure
1. Write a failing test (or a scripted reproduction) that captures the bug.
2. Fix the cause.
3. Check for the same defect pattern in sibling code; report, but only fix in scope.

## Validation
- The reproduction fails before and passes after; show both.
- Run the repository's other checks; show results.

## Security
If the bug is exploitable (input validation, privilege, auth, licensing), say so and treat
the report as private.

## Deliverables
Fix, regression test, root-cause statement.

## Completion report
Root cause (path:line); reproduction before/after output; checks run; residual risk.
