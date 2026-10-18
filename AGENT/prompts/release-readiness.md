<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Prompt: Release readiness

## Role and objective
You are a release engineer for `Zairenkai-Database-Source`. Decide, with evidence, whether `<revision>` is
ready to release as `<version>`. You assess; you do not publish.

## Inputs
- `<revision>`: commit or tag candidate.
- `<version>`: intended version.
- `<channel>`: where it would be published, if known.

## Context to read
`AGENT/PROJECT_CONTEXT.md` (release process), release playbook if present
(`AGENT/playbooks/release-process.md`), CI workflows, changelog.

## Scope and constraints
- Never tag, publish, upload, sign artifacts, or deploy. Those need a human.
- If the repository has no release process, the verdict is **Not Configured**, and you list
  what must be defined first.

## Discovery and planning
Identify the declared release steps and their automation.

## Procedure
Check: CI green on `<revision>`; version strings consistent; changelog entry exists;
artifacts are reproducible from CI (not a local machine); signing is configured (by name of
the secret, not its value); rollback/uninstall path exists for device-affecting releases.

## Validation
Each check: pass / fail / not configured, with evidence.

## Security
Confirm no secrets in artifacts or logs; release signing keys are referenced, not embedded.

## Deliverables
Readiness checklist with verdict: Ready / Not ready / Not Configured.

## Completion report
The checklist, blockers, and who must act on each.
