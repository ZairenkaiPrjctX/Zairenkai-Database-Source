---
paths:
  - "CLAUDE.md"
  - "AGENTS.md"
  - "AGENT/**"
  - ".claude/**"
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Rule: editing agent foundation files

- Files listed in `AGENT/.foundation-manifest.json` are managed centrally. Change them in
  `ZairenkaiPrjctX/.github/agent-foundation/templates/repo/` and re-sync; a local edit is
  reported as drift.
- `CLAUDE.md`, `AGENT/PROJECT_CONTEXT.md`, and `AGENT/ARCHITECTURE.md` belong to this
  repository. Every fact carries `Evidence:` or an Unverified/Unknown label.
- `.claude/settings.json` may only become *more* restrictive. Never add broad `allow` rules
  or `bypassPermissions`.
- After editing, run the foundation validator and fix all errors.
