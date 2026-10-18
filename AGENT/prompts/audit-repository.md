<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Prompt: Audit repository

## Role and objective
You are a staff engineer auditing `Zairenkai-Database-Source`. Produce an evidence-backed picture of what the
repository actually contains and update `AGENT/PROJECT_CONTEXT.md` and `AGENT/ARCHITECTURE.md`.

## Inputs
- `<focus>`: whole repository, or a named area (default: whole repository).
- `<depth>`: `quick` (layout and manifests) or `full` (also entry points and data flow).

## Context to read
`CLAUDE.md`, `AGENT/PROJECT_CONTEXT.md`, `AGENT/ARCHITECTURE.md`, `README*`, manifests
(`package.json`, `build.gradle*`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `Makefile`,
`Android.bp`, `CMakeLists.txt`, `module.prop`, …), `.github/workflows/`, test directories.

## Scope and constraints
- Read-only, except `AGENT/PROJECT_CONTEXT.md`, `AGENT/ARCHITECTURE.md`, and the Commands
  table in `CLAUDE.md`.
- Do not run builds, installs, migrations, deployments, or release scripts to "see what
  happens". Read them instead.
- Do not open files that look like secrets (`.env`, keys, keystores). Note their *paths* only.

## Discovery and planning
1. `git status`; `git ls-files | head -200`; count files per top-level directory.
2. Identify languages from manifests and extensions, not from the repository name.
3. List entry points, build/test/lint commands as *declared* in manifests and CI.

## Procedure
1. For each fact, record the evidence path. Mark anything inferred as **Unverified**.
2. Update the Identity, Contents, Key components, and Build/test sections of
   `PROJECT_CONTEXT.md`, and fill `ARCHITECTURE.md` sections 1–7 as far as evidence allows.
3. Update `CLAUDE.md` Commands: a command is listed only if a manifest or CI file declares it;
   its status is `Declared` until it has been run, `Verified` after it has run successfully.
4. List generated files and their generators.

## Validation
- Every new statement has `Evidence:` or an Unverified/Unknown label.
- Run the foundation validator; fix errors.

## Security
List security-sensitive areas (root/kernel code, auth, licensing, CI secrets usage, network
endpoints) with paths. Do not reproduce secret values.

## Deliverables
Updated context files; a findings list of risks and unknowns.

## Completion report
What was inspected (paths), facts added, facts still unknown, commands run and their
output, validator result.
