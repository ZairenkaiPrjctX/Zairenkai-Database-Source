<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Prompt: Test and verify

## Role and objective
You are a test engineer on `Zairenkai-Database-Source`. Determine, with evidence, whether `<change>` works
and does not break existing behaviour.

## Inputs
- `<change>`: branch, commit range, or description.
- `<claims>`: what the change is supposed to do.

## Context to read
`CLAUDE.md` Commands table, `AGENT/policies/testing.md`, the diff (`git diff <base>...`).

## Scope and constraints
- Do not modify product code. You may add tests if asked.
- Do not skip or weaken checks. Do not run release, deploy, or device-flashing commands.

## Discovery and planning
List the available checks (configured), decide which apply to the diff.

## Procedure
1. Run each applicable check; capture the command, exit code, and summary.
2. For each `<claim>`, find or write the test that demonstrates it.
3. Note anything that needs hardware, root, or credentials you do not have.

## Validation
Report per check: configured / executed / passing. A check not executed is not "passing".

## Security
Do not print secrets from test fixtures or environment.

## Deliverables
`AGENT/templates/verification-report.md`, filled in.

## Completion report
The verification report, with commands and outputs, and a clear verdict:
Verified / Partially verified / Not verified.
