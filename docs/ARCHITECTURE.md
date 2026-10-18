# Architecture

AFID is a Python package (`src/afid/`) plus a Git-tracked metadata catalog (`database/`).
Firmware is processed locally; only metadata that passes validation and policy enters Git.

## Pipeline

```
Source discovery (providers)          afid discover / afid updates check
      |  metadata only; snapshots in database/sources/, candidates in database/staging/
Source validation / local import      afid ingest --local
      |  provider capability check, SHA-256 vs. supplied official checksum
Archive integrity + type detection    extraction/detect.py (magic bytes, never extensions)
      |
Read-only extraction                  extraction/archives.py, sparse.py, pipeline.py
      |  ZIP/TAR (safe), nested archives, sparse->raw, super/payload/ext4/EROFS via tools
Partition discovery + inspection      extraction/pipeline.py -> tree/<partition>/
      |
Component scanning                    scanning/  (inventory, SHA-256, safe parsers)
      |
Classification + dependencies         classification/ (rules), dependencies/ (graph)
      |
Policy / license check                licensing/  (default unknown; allowlist by SHA-256)
      |
Schema validation                     catalog/validate.py (before every write, and in CI)
      |
Catalog write + index                 catalog/__init__.py, catalog/index.py
      |
Update report                         updates/  (snapshot diff, build-to-build history)
```

Device identity is decided between extraction and scanning (`ingest.py`): the codename must
come from firmware evidence (build.prop, OTA metadata) or an official source. Otherwise the
result goes to `database/staging/unresolved/` and no permanent device directory is created.

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Locate the repository root and load `config/*.yml` |
| `models.py` | Stable ID rules, categories, record builders |
| `parsers/` | ELF (pure Python), init `.rc`, VINTF XML, build.prop, thermal/power config summaries |
| `classification/` | Glob rules from `config/component_rules.yml`, confidence and reasons |
| `scanning/` | Recursive inventory, symlink handling, duplicate detection, component records |
| `dependencies/` | DT_NEEDED (transitive), init->binary, VINTF->HAL, config references, HAL->config |
| `extraction/` | Format detection, safe archives, sparse images, tool-backed filesystem extraction |
| `download/` | HTTPS client: host allowlist, retries with backoff, rate limit, resume, checksum |
| `providers/` | Provider API, registry, brand providers, LineageOS wiki metadata provider |
| `licensing/` | Distribution statuses, allowlist, publish-directory check |
| `catalog/` | Codename-centric storage, validation, deterministic index/statistics/library map |
| `updates/` | Discovery snapshots, change detection, staging writes, firmware history diff |
| `reporting/` | JSON/Markdown catalog report |
| `audit.py` | Secrets, payloads, large files, workflow risk scan |
| `cli.py` | The `afid` command |

## Design decisions and deviations from the initial structure

| Requested | Implemented | Why |
|---|---|---|
| Top-level `providers/` | `src/afid/providers/` | Importable package, testable, no `sys.path` tricks |
| `database/components/.../<group>/` directories | `.../<build>/<group>.json` files | One file per group keeps diffs reviewable and avoids thousands of tiny files |
| `database/brands/` | Brand registry in `config/brands.yml`, brand counts in `statistics.json` | Avoids a second copy of brand data that could disagree |
| `database/staging/unresolved/` | `database/staging/unresolved/<provider>/<candidate>.json` | Candidates from different sources never overwrite each other |
| `.github/FUNDING.yml` | Not created | No real funding accounts exist; a placeholder would be fabricated |
| Separate `discovery/`, `hashing/` subpackages | `providers/` + `updates/` do discovery; `hashing/` exists | Discovery is a provider capability, not a separate layer |
| Additional | `schemas/candidate.schema.json`, `afid policy check`, `afid security scan`, `afid updates report` | Needed to enforce staging, publishing policy and history comparison |

## Trust boundaries

- **Firmware content** is untrusted data. It is parsed with bounded, read-only parsers and is
  never executed. External tools get argument lists (no shell) and fixed timeouts.
- **Providers** may only contact the hosts listed in their registry entry, over HTTPS.
- **Git** receives metadata only. `database/` may contain only JSON; the validator and the
  security scan fail on binaries, archives or images outside `tests/fixtures/`.
- **CI** runs untrusted pull-request code with a read-only token. Jobs with write access run
  only on schedule/dispatch, on the default branch's code, and only open pull requests.
