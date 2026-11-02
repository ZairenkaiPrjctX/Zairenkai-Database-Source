# Architecture: Zairenkai-Database-Source

> Owned by this repository. Document only what inspected code supports, citing file paths.
> Full description: `docs/ARCHITECTURE.md`.

## 1. Overview
AFID ingests firmware locally, identifies devices from firmware evidence, classifies thermal
and power components, builds a dependency graph, and writes validated JSON metadata to
`database/`. Evidence: `src/afid/ingest.py`.

## 2. Components
| Path | Responsibility |
|---|---|
| `src/afid/cli.py` | `afid` command, exit codes |
| `src/afid/ingest.py` | end-to-end local ingestion |
| `src/afid/extraction/` | detection, safe ZIP/TAR, sparse, tool-backed filesystems |
| `src/afid/scanning/`, `classification/`, `parsers/` | inventory, rules, ELF/init/VINTF/config parsing |
| `src/afid/dependencies/` | dependency edges |
| `src/afid/catalog/` | storage, validation, index/statistics |
| `src/afid/providers/` | provider API, registry, brand providers, LineageOS wiki, GitLab client + dump providers, DumprX tool provider |
| `tools/mirror_lineageos_wiki.py`, `source-files/lineageos_wiki/` | bounded, commit-pinned mirror of original CC BY-SA LineageOS device YAML with per-file hashes |
| `src/afid/remote.py`, `matrix.py`, `reconcile.py` | remote dump analysis, matrix planning, delta merge + ingestion state |
| `src/afid/dumprx.py`, `resources.py` | guarded DumprX runner, resource budgets |
| `.docker/` | five container images (validation, discovery, catalog, firmware-worker, security) |
| `src/afid/updates/` | snapshot diff, staging, history |
| `src/afid/licensing/`, `audit.py` | distribution policy, repository audit |
| `src/afid/pipeline/`, `tools/`, `registry/` | CodeBuild metadata pipeline: source registry, URL policy, bounded discovery, records, run manifest, optional S3 upload (`docs/AWS_PIPELINE.md`) |
| `buildspec.yml`, `infra/cloudformation/codebuild.yml` | CodeBuild build and project/role/log group template (never deployed by this repository) |
| `.github/workflows/mirror-lineageos-source.yml` | scheduled/manual source-only mirror; proposed changes go through a scoped review PR |

## 3. Entry points
`afid` console script (`pyproject.toml`); workflows in `.github/workflows/`;
`scripts/open_data_pr.py` for workflow-created pull requests; `tools/ingest.py`,
`tools/validate.py`, `tools/publish_manifest.py` (run by `buildspec.yml` in CodeBuild).

## 4. Data flow
Archive/image/directory → `.afid-cache/work/<sha>/` → `tree/<partition>/` → components and
edges → schema validation → `database/…` (see `docs/DATABASE_SCHEMA.md`).

## 5. External interfaces
HTTPS to provider `allowed_hosts` only (`github.com`, `raw.githubusercontent.com` via git
for `lineageos_wiki`; `gitlab.com` and `dumps.tadiphone.dev` GitLab REST v4, read-only, for
the dump providers; `config/provider_registry.yml`); DumprX `303f5bba` runs offline in the
worker image (`src/afid/dumprx.py`); external tools `debugfs`, `fsck.erofs`, `lpunpack`,
`payload-dumper-go`, `lz4`, `git` (`src/afid/extraction/tools.py`). The metadata pipeline
contacts only `registry/sources.json` `allowed_hosts` in `discover` mode (none are enabled),
and, only with `ENABLE_S3_PUBLISH=true`, S3 via one `aws s3api put-object`
(`src/afid/pipeline/publish.py`).

## 6. Trust boundaries
Firmware content is untrusted and never executed; workflows run untrusted PR code with a
read-only token; write tokens exist only in PR-proposing jobs. Evidence: `docs/SECURITY.md`.

## 7. Generated artifacts
`database/index.json`, `database/statistics.json`, `database/dependencies/library_map.json`
(by `afid database index` / `afid dependencies build`); `requirements.lock` (by `uv pip
compile`); `tests/fixtures/elf/{arm,arm64}/*` (by `tests/fixtures/elf/build.sh`);
`build/pipeline/*.json` run manifests (by `tools/ingest.py`; gitignored, never committed). Do
not edit these by hand.
