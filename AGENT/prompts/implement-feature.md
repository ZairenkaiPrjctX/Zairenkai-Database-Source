<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Prompt: Implement feature

## Role and objective
You are a senior engineer on `Zairenkai-Database-Source`. Implement `<feature>` so that it meets every
acceptance criterion, with the smallest change that fits the existing design.

## Inputs
- `<feature>`: what to build, in one or two sentences.
- `<expected_behaviour>`: observable behaviour after the change.
- `<acceptance_criteria>`: numbered, testable criteria.
- `<affected_areas>`: modules or paths, if known.
- `<out_of_scope>`: things explicitly not to change.

## Context to read
`AGENT/PROJECT_CONTEXT.md`, `AGENT/ARCHITECTURE.md`, the code in `<affected_areas>`, its
tests, and its callers.

## Scope and constraints
- Do not change public interfaces, file formats, or device behaviour beyond what the criteria
  require. Ask if a criterion forces such a change.
- No new dependencies without approval. No unrelated refactors.
- Preserve uncommitted changes you did not make.

## Discovery and planning
1. Locate where similar behaviour already exists and follow its pattern.
2. Write a plan with `AGENT/templates/implementation-plan.md`: files to change, tests to
   add, risks. For a large or risky change, share the plan before editing.

## Procedure
1. Add or update tests that encode the acceptance criteria (when a test framework exists).
2. Implement the change.
3. Update documentation and `AGENT/` facts the change affects.

## Validation
- Run the repository's checks from `CLAUDE.md`; show the commands and results.
- Map each acceptance criterion to the test or manual check that demonstrates it.
- If no checks exist, state "Not Configured" and describe what you verified manually.

## Security
Consider new inputs, privilege changes, and secret use. Root/kernel/licensing changes
need a human reviewer and a rollback path.

## Deliverables
The change, tests, updated docs, and a verification report
(`AGENT/templates/verification-report.md`).

## Completion report
Files changed; criteria → evidence table; checks executed and results; anything unverified
and why; follow-ups.
