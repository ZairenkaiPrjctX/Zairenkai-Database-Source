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
| `src/afid/providers/` | provider API, registry, brand providers, LineageOS wiki |
| `src/afid/updates/` | snapshot diff, staging, history |
| `src/afid/licensing/`, `audit.py` | distribution policy, repository audit |

## 3. Entry points
`afid` console script (`pyproject.toml`); workflows in `.github/workflows/`;
`scripts/open_data_pr.py` for workflow-created pull requests.

## 4. Data flow
Archive/image/directory → `.afid-cache/work/<sha>/` → `tree/<partition>/` → components and
edges → schema validation → `database/…` (see `docs/DATABASE_SCHEMA.md`).

## 5. External interfaces
HTTPS to provider `allowed_hosts` only (currently `github.com`, `raw.githubusercontent.com`
via git for `lineageos_wiki`); external tools `debugfs`, `fsck.erofs`, `lpunpack`,
`payload-dumper-go`, `lz4`, `git` (`src/afid/extraction/tools.py`).

## 6. Trust boundaries
Firmware content is untrusted and never executed; workflows run untrusted PR code with a
read-only token; write tokens exist only in PR-proposing jobs. Evidence: `docs/SECURITY.md`.

## 7. Generated artifacts
`database/index.json`, `database/statistics.json`, `database/dependencies/library_map.json`
(by `afid database index` / `afid dependencies build`); `requirements.lock` (by `uv pip
compile`); `tests/fixtures/elf/{arm,arm64}/*` (by `tests/fixtures/elf/build.sh`). Do not edit
these by hand.
