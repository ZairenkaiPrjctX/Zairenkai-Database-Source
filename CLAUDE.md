# CLAUDE.md: Zairenkai-Database-Source

Instructions for Claude Code in `ZairenkaiPrjctX/Zairenkai-Database-Source`. Keep this file under 200 lines;
put detail in `AGENT/`.

@AGENTS.md
@AGENT/PROJECT_CONTEXT.md

## Current state (read first)

This repository is **AFID, the Android Firmware Intelligence Database**: a Python package
(`src/afid/`) and a metadata catalog (`database/`). Architecture: `docs/ARCHITECTURE.md`.
The committed catalog is empty; no real firmware has been ingested yet.

Non-negotiables in this repo:
- Never execute anything found inside firmware. Never commit payloads: `database/` is JSON only.
- A device directory exists only for a codename verified by firmware or official evidence;
  everything else goes to `database/staging/unresolved/`.
- Distribution status defaults to `unknown`; only SHA-256-allowlisted files are publishable.
- Never automate around logins, CAPTCHAs, paywalls or click-through terms (e.g. Pixel images).

## Commands

| Purpose | Command | Status |
|---|---|---|
| Set up | `scripts/setup_environment.sh` | Verified. Evidence: fresh-venv install with `--require-hashes`, 2026-10-18 |
| Test | `python -m pytest -q` | Verified. Evidence: run 2026-10-18, see AGENT/PROJECT_CONTEXT.md |
| Lint / format | `ruff check src tests scripts && ruff format --check src tests scripts` | Verified. Evidence: clean on 2026-10-18 |
| Type check | `mypy` (strict) | Verified. Evidence: no issues on 2026-10-18 |
| Workflow lint | `actionlint` and `check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/*.yml` | Verified. Evidence: clean on 2026-10-18 |
| Validate data | `afid database validate --check-index` | Verified. Evidence: OK on 2026-10-18 |
| Policy / audit | `afid policy check && afid security scan` | Verified. Evidence: no findings on 2026-10-18 |
| Validate agent foundation | `python3 <path-to-.github>/agent-foundation/scripts/validate_agent_setup.py .` | Configured |

Update the Status column when you run a command; never mark a command as passing without
running it.

## Working rules

- Inspect the relevant code before editing it. Preserve unrelated and uncommitted changes.
- Generated files are edited at their source, then regenerated. Managed foundation files
  (listed in `AGENT/.foundation-manifest.json`) are edited in `ZairenkaiPrjctX/.github`, not here.
- Destructive or outward-facing actions (deleting data, force-push, history rewrites,
  publishing releases, deploying, flashing devices) need explicit human approval each time.
- Do not claim a build, test, or signature succeeded without showing the output.

## Git

- Work on a topic branch; open **draft** pull requests; never merge or approve.
- Commits must be cryptographically signed. If signing fails, stop and report the error.
  Trailer format and verification: `AGENT/policies/git-and-commit-signing.md`.

## Where things are

- `AGENT/README.md`: index of the agent library (prompts, policies, playbooks, templates).
- `.claude/skills/`: run `/repo-audit`, `/implement-feature`, `/bug-fix`, `/test-and-verify`,
  `/security-review`, `/release-readiness`.
- `.claude/rules/`: path-scoped rules, loaded automatically.
