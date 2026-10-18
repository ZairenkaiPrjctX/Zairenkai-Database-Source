<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Prompt: Refactor

## Role and objective
You are a staff engineer on `Zairenkai-Database-Source`. Restructure `<target>` to achieve `<goal>` without
changing observable behaviour.

## Inputs
- `<target>`: code to restructure.
- `<goal>`: the concrete problem this solves (duplication, coupling, readability, …).
- `<constraints>`: interfaces that must not change.

## Context to read
`<target>`, all callers (search the repository), its tests, `AGENT/ARCHITECTURE.md`.

## Scope and constraints
- Behaviour-preserving only. No feature changes in the same diff.
- No total rewrites. Prefer a sequence of small, reviewable steps.
- Public interfaces in `<constraints>` stay byte-for-byte compatible.

## Discovery and planning
1. Confirm tests cover the behaviour you will preserve. If they do not, add
   characterisation tests first.
2. Plan the steps; each step should leave the code working.

## Procedure
Apply the steps, running the checks after each one.

## Validation
Same test results before and after (show both). No public interface diff unless approved.

## Security
Confirm no validation, permission check, or error path was dropped.

## Deliverables
Refactored code, characterisation tests (if added), updated `ARCHITECTURE.md` if structure
changed.

## Completion report
Steps taken; before/after check results; interfaces confirmed unchanged; remaining debt.
