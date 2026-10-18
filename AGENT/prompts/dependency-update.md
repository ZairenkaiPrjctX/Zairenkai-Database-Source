<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Prompt: Dependency update

## Role and objective
You are a maintainer of `Zairenkai-Database-Source`. `<action>` the dependency `<package>` safely.

## Inputs
- `<action>`: add / upgrade / remove.
- `<package>` and `<target_version>`.
- `<reason>`: why this is needed.

## Context to read
Manifest and lockfile, the code that uses `<package>`, upstream changelog/release notes
between versions.

## Scope and constraints
- One dependency per change unless they must move together.
- Use the repository's package manager to update lockfiles; never hand-edit them.
- Do not upgrade unrelated packages.

## Discovery and planning
Read breaking changes between current and target version; list affected call sites.
Check the licence is compatible.

## Procedure
Update the manifest, regenerate the lockfile, adapt call sites, update docs.

## Validation
Run build and tests; show results. Confirm the resolved version in the lockfile.

## Security
Check for known advisories on the target version; prefer pinned versions; verify the
package name (typosquatting).

## Deliverables
Manifest/lockfile change, adapted code, note of breaking changes handled.

## Completion report
Old → new version, licence, advisories checked, checks run and results.
