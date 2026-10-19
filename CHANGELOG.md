# Changelog

All notable changes to this project are documented here. Format: Keep a Changelog;
versioning: SemVer.

## [Unreleased]

### Added
- Community firmware dump providers `android_dumps_gitlab` (gitlab.com group
  `Android-Dumps`) and `tadiphone_dumps` (dumps.tadiphone.dev): read-only GitLab client with
  pagination and rate-limit handling, incremental discovery (one item per dump branch, keyed
  by commit SHA), `health_check()`, sanity floor for truncated listings.
- Remote-tree analysis (`afid firmware analyze`): commit-pinned selective file fetch within
  `MAX_FETCH_FILES`/`MAX_FETCH_BYTES`, system-as-root normalization, LFS pointer detection,
  transitive DT_NEEDED fetch, identity from the dump's build.prop (`dump_build_prop`).
- Delta stores and `afid catalog reconcile`: content-based placement, cross-host dedup into
  one firmware record with several `source_refs`, conflict quarantine, ingestion state
  (`database/state/`, `schemas/state.schema.json`).
- `afid matrix plan`: deterministic, bounded batches (<= 256) for GitHub Actions matrices.
- DumprX tool provider and guarded runner (`afid firmware dump`), pinned to
  `303f5bba1f58`; offline, credential-free worker image.
- Resource budgets (`resources` in `config/settings.yml`, `AFID_<NAME>` overrides,
  `afid resources`), `ResourceError` (exit code 13), download hardening (redirect host
  checks, HTML-page rejection, Content-Length and disk checks, truncation detection,
  `Retry-After`).
- Five container images under `.docker/` and workflows `container-images`,
  `discover-dumps`, `plan-firmware-matrix`, `download-dumps`, `analyze-components`,
  `reconcile-catalog`, `dump-and-analyze`; Hadolint/ShellCheck in `validate`, Trivy and SBOM
  in `security-audit`.
- 22 extended brands seen in dumps; MediaTek thermal/power classification rules;
  false-positive exclusions; YAML config summaries; CLI `providers health`, `discover --all`,
  `matrix plan`, `catalog reconcile|validate`, `firmware analyze|dump|download|verify|ingest`.
- Docs: SOURCE_INTEGRATION, DUMPRX_INTEGRATION, DOCKER_ARCHITECTURE, CONTAINER_IMAGES,
  MATRIX_PIPELINE, RESOURCE_BUDGETS.

### Changed
- Firmware keys include `ro.build.version.incremental` when it differs from the build id;
  firmware records gain `build_incremental` and `source_refs`.
- `brand_id` is validated against the registry instead of a fixed schema enum.
- `docs/LICENSING.md` -> `docs/LICENSE_AND_DISTRIBUTION.md`,
  `docs/COMPONENT_CLASSIFICATION.md` -> `docs/COMPONENT_ANALYSIS.md`.
- `afid discover` needs `--provider`, `--brand` or `--all`; `check-updates.yml` skips dump
  providers.
- Catalog JSON files are written with mode 0644.

### Fixed
- The update snapshot duplicated its `_index` marker on every run, so scheduled discovery
  opened PRs without upstream changes (regression test `test_index_marker_is_never_duplicated`).

### Earlier
- Initial AFID implementation (0.1.0): codename-centric catalog, JSON Schemas (device,
  firmware, component, dependency, source, candidate, report), rule-based classifier,
  ELF/init/VINTF/build.prop/config parsers, dependency graph, distribution policy, safe
  extraction pipeline (ZIP, TAR, Android sparse, ext4 via debugfs; EROFS, super.img,
  payload.bin and LZ4 via external tools), provider registry with 11 providers,
  LineageOS wiki metadata discovery, update detection and history reports, `afid` CLI,
  six GitHub Actions workflows, documentation.
- 353 unverified device candidates from the LineageOS Wiki (CC BY-SA 3.0, attributed) in
  `database/staging/unresolved/lineageos_wiki/`; not counted as verified devices.
- Per-source `data_license` metadata in the provider registry and in every staging record
  (source, revision, snapshot, license, verification requirements, `firmware_payload_ingested`).
- `afid policy check` rules for staging records; `staging_by_brand` / `staging_unverified`
  statistics.
