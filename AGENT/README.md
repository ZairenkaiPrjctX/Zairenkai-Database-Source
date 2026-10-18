<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# AGENT/: agent library for Zairenkai-Database-Source

| Path | What it is | Owner |
|---|---|---|
| `PROJECT_CONTEXT.md` | Verified facts about this repository | This repo |
| `ARCHITECTURE.md` | Architecture supported by inspected code | This repo |
| `prompts/` | Ready-to-use task prompts ([index](prompts/README.md)) | Central |
| `policies/` | Operational rules derived from org standards | Central |
| `playbooks/` | Step-by-step procedures for recurring work | Central |
| `templates/` | Fill-in templates for briefs, plans, reports, PRs | Central |
| `.foundation-manifest.json` | List and hashes of centrally managed files | Generated |

"Central" files are generated from `ZairenkaiPrjctX/.github/agent-foundation/templates/repo/`.
To change one, edit the template there and re-run the sync script; local edits show up as
drift in the validator.

## Policies
- [Engineering](policies/engineering.md)
- [Testing](policies/testing.md)
- [Security and secrets](policies/security-and-secrets.md)
- [Git and commit signing](policies/git-and-commit-signing.md)
- [Documentation](policies/documentation.md)

## Playbooks
- [Feature delivery](playbooks/feature-delivery.md)
- [Debugging](playbooks/debugging.md)

## Templates
- [Task brief](templates/task-brief.md)
- [Implementation plan](templates/implementation-plan.md)
- [Verification report](templates/verification-report.md)
- [Pull request](templates/pull-request.md)

## Using a prompt
Copy the prompt file's content into a Claude Code session (or reference it:
"Follow `AGENT/prompts/bug-fix.md` for: <issue>"), filling in the `<parameters>`.
The matching skill (`/bug-fix`, etc.) does this for you.
