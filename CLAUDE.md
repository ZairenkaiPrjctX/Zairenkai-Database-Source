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
- Dump hosts (Android-Dumps, tadiphone) are read-only sources: never clone, push or download
  archives; dump-derived records keep distribution `unknown`.
- DumprX runs only offline in `afid-firmware-worker`; never create its credential files
  (`.github_token`, `.gitlab_token`, `.tg_token`, ...) or pass it URLs or tokens.
- The CodeBuild metadata pipeline (`src/afid/pipeline/`, `tools/`, `registry/`,
  `buildspec.yml`, `infra/`) never downloads firmware, keeps every source disabled until an
  approved review is recorded in `registry/sources.json`, and publishes to S3 only with
  `ENABLE_S3_PUBLISH=true`. Never deploy the stack, start builds or change AWS resources
  without explicit human approval (`docs/AWS_SETUP.md`).

## Commands

| Purpose | Command | Status |
|---|---|---|
| Set up | `scripts/setup_environment.sh` | Verified. Evidence: fresh-venv install with `--require-hashes`, 2026-10-18 |
| Test | `python -m pytest -q` | Verified. Evidence: 325 passed on host, 2026-10-20 |
| Test (pipeline only, no test dependencies) | `PYTHONPATH=src python -m unittest discover -s tests/pipeline -t .` | Verified. Evidence: 58 passed, 2026-10-20 |
| Lint / format | `ruff check src tests scripts tools && ruff format --check src tests scripts tools` | Verified. Evidence: clean on 2026-10-20 |
| Type check | `mypy` (strict) | Verified. Evidence: no issues in 56 files on 2026-10-20 |
| Workflow lint | `actionlint` and `check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/*.yml` | Verified. Evidence: clean (actionlint with shellcheck, in `afid-validation`) on 2026-10-19 |
| Shell / Dockerfile lint | `shellcheck .docker/scripts/*.sh scripts/*.sh`; `hadolint` on `.docker/*.Dockerfile` | Verified. Evidence: clean on 2026-10-19 |
| Container images | `docker build -f .docker/<image>.Dockerfile .` (see `.docker/README.md`) | Verified. Evidence: all five built and smoke-tested locally, 2026-10-19 |
| Validate data | `afid database validate --check-index` | Verified. Evidence: OK on 2026-10-19 |
| Policy / audit | `afid policy check && afid security scan` | Verified. Evidence: no findings on 2026-10-19 |
| Pipeline dry-run (offline) | `python3 tools/ingest.py --mode dry-run && python3 tools/validate.py manifest build/pipeline/manifest.json` | Verified. Evidence: exit 0, 3 validated, 1 duplicate, 2026-10-20 |
| Pipeline config | `python3 tools/validate.py all` | Verified. Evidence: OK, 2026-10-20 |
| CloudFormation lint | `cfn-lint --regions ap-southeast-3 -- infra/cloudformation/codebuild.yml` (not a repository dependency) | Verified. Evidence: cfn-lint 1.57.2 clean, 2026-10-20 |
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
