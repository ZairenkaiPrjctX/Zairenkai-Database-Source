# AFID — Android Firmware Intelligence Database

AFID builds a structured, verifiable metadata database of Android firmware components that
matter for thermal and power work: Thermal HAL services and libraries, thermal-engine and
thermal configuration, Power HAL, PowerHint/power JSON and power profiles, vendor
performance libraries, init service definitions, VINTF declarations, and the dependency
graph that ties them together. It is the data source for future Zairenkai projects (Thermal
HAL / Thermal Engine integration, PowerHAL tuning, cross-device compatibility work).

The repository stores **metadata** (identities, versions, paths, SHA-256 checksums,
classifications, dependencies, provenance). Proprietary firmware is processed locally and is
**not** stored or published unless an explicit, evidence-backed allowlist entry permits it.

> Status: unreleased development on `dev` (package version 0.1.0). Engine, schemas, CLI, workflows and container images are
> implemented and tested offline with fixtures. Community firmware dumps (Android-Dumps on
> gitlab.com, dumps.tadiphone.dev) can now be discovered and analyzed without downloading
> firmware, and pinned DumprX can unpack local firmware offline; both were exercised against
> real sources into scratch databases ([docs/SOURCE_INTEGRATION.md](docs/SOURCE_INTEGRATION.md#live-results)).
> The committed catalog still has **no verified devices** (353 unverified LineageOS Wiki
> candidates wait in staging) until the dump workflows run and their PRs are reviewed. No CI
> badges are shown until the workflows have run on GitHub.

## Contents

1. [Scope](#scope) · 2. [Brands](#brands) · 3. [Features](#features) ·
4. [Architecture](#architecture) · 5. [Repository layout](#repository-layout) ·
6. [Data stored](#data-stored) · 7. [Database schema](#database-schema) ·
8. [Provider status](#provider-status) · 9. [Installation](#installation) ·
10. [CLI usage](#cli-usage) · 11. [Local firmware import](#local-firmware-import) ·
12. [Scanning and validation](#scanning-and-validation) · 13. [Updates](#update-workflow) ·
14. [Extending AFID](#extending-afid) · 15. [Licensing policy](#licensing-and-redistribution) ·
16. [Security](#security-and-firmware-use) · 17. [Troubleshooting](#troubleshooting) ·
18. [Testing](#testing-and-quality-checks) · 19. [Roadmap](#roadmap) ·
20. [Contributing](#contributing) · 21. [License](#license-and-attribution)

## Scope

Components AFID finds, classifies and indexes:

| Category | Examples of what is recognised |
|---|---|
| `thermal_hal` | `*/bin/hw/android.hardware.thermal-service*`, `thermal.*.so` HAL modules, Thermal HAL interface libraries |
| `thermal_engine`, `thermal_config` | `thermal-engine*` daemon and `.conf`, `thermal_info_config*.json`, `thermal*.{conf,json,xml}`, files under `*/etc/thermal*/` |
| `power_hal` | `android.hardware.power-service*`, `power.*.so`, vendor perf HAL services |
| `power_json`, `power_config`, `power_profile`, `performance_config` | `powerhint*.json`, `power.json`, `powerhint*.xml`, `power_profile*.xml`, `*/etc/perf/*` |
| `vendor_library` | `libqti-perf*`, `libperfmgr*`, thermal/power-named libraries (low confidence), and every vendor library reached through DT_NEEDED |
| `init_service`, `init_script` | `.rc` files defining thermal/power/perf services, `ueventd*.rc` |
| `vintf_manifest` | VINTF manifests and compatibility matrices |
| `supporting_metadata` | `build.prop` (allowlisted keys only) |
| `unknown` | unmatched files in HAL and config directories, kept for future rules |

Names and paths are patterns, not guarantees; classification records its rule, reason and
confidence, and a name alone never proves a role. Missing components (for example no
PowerHint JSON on a device) are simply absent, never invented.

## Brands

The nine **core** brands below are covered by every provider and report. 22 **extended**
brands seen in community dumps (Motorola, Nokia, Lenovo, realme, OPPO, vivo, iQOO, ASUS,
Sony, Meizu, LG, Amazon, nubia, ZTE, HONOR, Huawei, itel, TCL, HTC, Fairphone, UMIDIGI,
Black Shark) are cataloged with the same evidence rules; anything else stays in staging
(`config/brands.yml`).

| Brand | `brand_id` | Notes |
|---|---|---|
| Samsung | `samsung` | |
| Xiaomi | `xiaomi` | |
| POCO | `poco` | own identity, Xiaomi ecosystem |
| Redmi | `redmi` | own identity, Xiaomi ecosystem |
| Infinix | `infinix` | |
| OnePlus | `oneplus` | |
| TECNO | `tecno` | "Techno" accepted as a search alias |
| Google Pixel | `google_pixel` | |
| Nothing Phone | `nothing` | |

## Features

- Codename-first catalog: every device directory is a **verified** codename; unverified data
  waits in `database/staging/unresolved/`.
- Provider-based ingestion with a registry, capability checks and documented limitations.
- Safe, read-only extraction: ZIP/TAR, nested archives, Android sparse images, ext4
  (`debugfs`), and EROFS / `super.img` / `payload.bin` / LZ4 through external tools.
- Pure-Python ELF analysis (SONAME, DT_NEEDED, machine, interpreter) without executing anything.
- init `.rc`, VINTF and thermal/power config parsing; dependency graph with
  `resolved` / `inferred` / `unresolved` edges.
- Default-deny distribution policy with a SHA-256 allowlist.
- Deterministic JSON output: unchanged data never produces a Git diff.
- Update detection by revision markers, history diffs between firmware builds, and pull
  requests for every data change.
- Community dump providers: incremental GitLab discovery (one item per dump branch, keyed by
  commit SHA), commit-pinned selective file fetch, identity from the dump's build.prop,
  cross-host dedup into one firmware record with several source refs, conflict quarantine.
- Pinned DumprX in an offline, non-root worker container that refuses to publish.
- Bounded GitHub Actions matrices (<= 256 jobs, `MAX_ITEMS_PER_RUN`), per-item failure
  isolation, delta stores merged by a single reconcile job, resource budgets for every step.
- Five digest-pinned container images with smoke tests, Trivy scans and SBOMs.

## Architecture

```
providers -> verify -> detect -> extract -> partitions -> scan -> classify -> dependencies
          -> policy -> schema validation -> catalog -> index/statistics -> update report
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```
.github/workflows/      validate, source-discovery, ingest-firmware, check-updates,
                        refresh-catalog, security-audit, container-images, discover-dumps,
                        plan-firmware-matrix, download-dumps, analyze-components,
                        reconcile-catalog, dump-and-analyze
.docker/                five Dockerfiles + build helpers (see .docker/README.md)
.github/actions/        setup-afid (Python + hash-pinned dependencies)
config/                 settings, brands, provider registry, classification rules,
                        source policy, redistributable allowlist
schemas/                JSON Schemas for every record type
database/               the catalog (JSON metadata only)
src/afid/               the AFID package (CLI, engine, providers)
scripts/                setup, validation, refresh, report, PR helper
tests/                  unit, integration, providers, extraction, schemas, security, fixtures
docs/                   architecture, schema, providers, ingestion, classification,
                        updates, licensing, security, contributing, troubleshooting
redistributable/        allowlisted payloads only (empty)
```

Agent-related files (`CLAUDE.md`, `AGENTS.md`, `AGENT/`, `.claude/`) come from the
ZairenkaiPrjctX agent foundation.

## Data stored

Per device: brand, codename (verbatim) and directory key, product names, model numbers,
regional variants, SoC, aliases, rebrand/shared-identity relations, Android versions, and the
evidence that verifies the codename. Per firmware build: build id, region/channel, Android
release, API level, security patch levels, fingerprint, source and archive checksum, official
checksum match, partition layout, extraction tools and versions, ingestion and validation
status. Per component: everything in [Scope](#scope) plus path, partition, size, SHA-256,
symlink target, classification evidence, parser output, license/distribution status,
provenance and dependency references. Personal data (serial numbers, IMEIs, accounts) is never
stored.

## Database schema

```
database/devices/<brand>/<codename_key>/device.json
database/firmware/<brand>/<codename_key>/<build>/firmware.json
database/components/<brand>/<codename_key>/<build>/<group>.json
database/dependencies/<brand>/<codename_key>/<build>.json
database/staging/unresolved/<provider>/<candidate>.json
```

Full description, ID rules, validation and migration strategy:
[docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md).

## Provider status

| Provider | Status | What works today |
|---|---|---|
| `lineageos_wiki` | metadata_only | device candidates from the LineageOS Wiki; 353 unverified candidates staged from upstream commit `2c365be2` (2026-10-18), 0 parse errors |
| `local_firmware` | active | local import of archives, images, extracted trees (fixture-tested) |
| `android_dumps_gitlab` | metadata_only | discovery of 592 dump branches (429 projects) and per-item analysis verified live on 2026-10-19 |
| `tadiphone_dumps` | metadata_only | per-item analysis and incremental discovery verified live on a subgroup (12 projects, 110 items); a full 2877-project listing has not completed yet |
| `dumprx` | manual_import_required | pinned DumprX, offline worker; verified on a synthetic ext4 firmware ZIP |
| `google_pixel` | manual_import_required | local import with official SHA-256 check; downloads need terms acceptance in a browser |
| `samsung`, `xiaomi`, `poco`, `redmi`, `oneplus`, `infinix`, `tecno`, `nothing` | manual_import_required | local import; no official automatable source verified |

No provider downloads firmware archives; dump providers fetch individual files at a pinned
commit. No real vendor firmware archive has been run through DumprX in this repository yet.
Not every model has an automatically accessible source, and proprietary firmware may be
restricted by its license. Per-provider details: [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Installation

Linux (tested on Ubuntu 24.04), Python 3.11+.

```bash
git clone https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source
cd Zairenkai-Database-Source
scripts/setup_environment.sh          # creates .venv from requirements.lock (hash-pinned)
source .venv/bin/activate
afid doctor
```

Optional tools for image formats (ext4, EROFS, LZ4): `sudo scripts/install_dependencies.sh`.
`lpunpack` and `payload-dumper-go` must be installed manually; `afid doctor` shows what each
missing tool blocks.

## CLI usage

```bash
afid --help
afid version
afid doctor
afid providers list
afid providers test
afid providers health [--provider <id>]         # live reachability / DumprX guards
afid discover --all --skip-dumps                # dry run of the fast discovery providers
afid discover --brand xiaomi --write            # store snapshot + staging candidates
afid discover --provider android_dumps_gitlab --write   # list dump branches (incremental)
afid matrix plan --mode eligible-batch [--provider <id>] [--batch-size <n>] [--batch-index <n>]
afid firmware analyze --provider <id> --item <item-id> [--out <delta-dir>]
afid firmware dump --input <local-file> --ingest   # pinned DumprX, inside afid-firmware-worker
afid firmware download --url <https-url> --sha256 <hex> --out <file>
afid firmware verify --input <file> [--sha256 <hex>]
afid firmware ingest --local <firmware-path>
afid catalog reconcile --deltas <dir> [--report-out reconcile.json]
afid catalog validate
afid resources
afid devices list
afid devices show google_pixel_<codename>
afid firmware list --device <device-id>
afid firmware inspect <firmware-id> --components
afid ingest --local <firmware-path> [--provider <id>] [--brand <id>] [--sha256 <hex>]
afid ingest --source <provider:item>            # explains why no provider can download yet
afid scan --input <extracted-directory> [--inventory] [--output scan.json]
afid classify --input <extracted-directory>
afid dependencies build
afid database validate [--check-index] [--strict]
afid database index [--check]
afid database stats
afid updates check [--provider <id>] [--write] [--report-out report.json]
afid updates report [--device <device-id>]
afid report --format json|markdown [--output file]
afid cache clean [--all]
afid policy check
afid security scan
```

Every command accepts `--json` (before the command name) for machine-readable output and
returns meaningful exit codes ([docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)).

## Local firmware import

```bash
# Pixel factory image downloaded after accepting Google's terms
afid ingest --local ~/Downloads/<codename>-<build>-factory-<hash>.zip \
    --provider google_pixel --sha256 <sha256 from the download page>

# Already-extracted tree with vendor/, odm/, system/ ...
afid ingest --local ./extracted --brand redmi --region global
```

The codename comes from the firmware (`ro.product.vendor.device`, OTA `pre-device`), never
from the file name or marketing name. Without usable identity the result is staged and the
command exits 12. See [docs/FIRMWARE_INGESTION.md](docs/FIRMWARE_INGESTION.md).

## Scanning and validation

```bash
afid classify --input ./extracted               # what would be cataloged, with confidence
afid scan --input ./extracted --output scan.json --inventory
afid database validate --check-index            # schemas, references, codenames, index
afid policy check                               # nothing unpublishable staged for publishing
```

## Community dumps in four commands

```bash
afid discover --provider android_dumps_gitlab --write          # 1. list dump branches
afid matrix plan --mode selected-item --provider android_dumps_gitlab --item '<item-id>'
afid firmware analyze --provider android_dumps_gitlab --item '<item-id>'   # 2-3. fetch + catalog
afid catalog validate                                          # 4. check the result
```

On GitHub the same runs as `discover-dumps.yml` and `download-dumps.yml`; see
[docs/MATRIX_PIPELINE.md](docs/MATRIX_PIPELINE.md), [docs/RESOURCE_BUDGETS.md](docs/RESOURCE_BUDGETS.md),
[docs/DOCKER_ARCHITECTURE.md](docs/DOCKER_ARCHITECTURE.md), [docs/CONTAINER_IMAGES.md](docs/CONTAINER_IMAGES.md)
and [docs/DUMPRX_INTEGRATION.md](docs/DUMPRX_INTEGRATION.md).

## Update workflow

`check-updates.yml` runs daily, compares sources by revision markers, and opens a pull request
only when metadata changed; a failing provider never deletes data. Identity questions
(possible rebrands, codename collisions) are flagged for review, never merged automatically.
Enabling it requires one repository setting. See [docs/UPDATE_SYSTEM.md](docs/UPDATE_SYSTEM.md).

## Extending AFID

- **Provider**: subclass `FirmwareProvider`, register it, add fixture tests
  ([docs/PROVIDERS.md](docs/PROVIDERS.md#adding-a-provider)).
- **Device**: ingest firmware that contains its identity; community data stays in staging
  ([CONTRIBUTING](docs/CONTRIBUTING.md#adding-a-device)).
- **Classifier**: add a rule to `config/component_rules.yml` with an honest confidence and
  reason ([docs/COMPONENT_ANALYSIS.md](docs/COMPONENT_ANALYSIS.md#adding-a-classifier)).

## Licensing and redistribution

Default status is `unknown`, which is never publishable; only files allowlisted by SHA-256
with license evidence are. XML/JSON/`.conf`/`.rc` files are not assumed free. Payloads never
enter Git, releases or workflow artifacts by default.
See [docs/LICENSE_AND_DISTRIBUTION.md](docs/LICENSE_AND_DISTRIBUTION.md).

## Security and firmware use

Firmware is untrusted input and is never executed. Extraction rejects traversal, escaping
links and bombs; XML entities are refused; tokens come only from the environment. AFID never
flashes, unlocks or modifies devices and never bypasses authentication, CAPTCHAs, paywalls or
click-through terms. See [SECURITY.md](SECURITY.md) and [docs/SECURITY.md](docs/SECURITY.md).

## Troubleshooting

Exit codes and common problems: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Testing and quality checks

```bash
python -m pytest -q
ruff check src tests scripts && ruff format --check src tests scripts
mypy
afid database validate --check-index && afid providers test && afid policy check && afid security scan
actionlint
docker run --rm -i hadolint/hadolint:v2.14.0 hadolint - < .docker/afid-catalog.Dockerfile
shellcheck .docker/scripts/*.sh scripts/*.sh
```

Tests run offline. ELF fixtures are real AArch64/ARM binaries built from
`tests/fixtures/elf/src/` (`tests/fixtures/elf/build.sh`); firmware trees and archives are
generated per test.

## Roadmap

- Exercise each brand's local import with real firmware and record results in
  `docs/PROVIDERS.md`.
- Boot-image parsing for kernel version; `vendor_boot` and `init_boot` layouts.
- Exynos and Tensor classification rules; MediaTek rules checked on more devices.
- Licence review of DumprX's bundled binaries, then a publishable worker image.
- Official-source providers wherever a documented, permitted, automatable API exists.
- Normalized (derived) thermal/power config representations stored separately from originals.

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). Commits must be signed; data changes go
through pull requests.

## License and attribution

AFID code, configuration, schemas, documentation and test fixtures: Apache License 2.0
([LICENSE](LICENSE), [NOTICE](NOTICE)). Third-party data keeps its own license: the LineageOS
Wiki candidates in `database/staging/unresolved/lineageos_wiki/` are CC BY-SA 3.0, (c) The
LineageOS Project. Apache-2.0 does not cover firmware, vendor libraries or vendor
configuration referenced by the catalog; those belong to their owners and are never
redistributed by default. Details: [docs/LICENSE_AND_DISTRIBUTION.md](docs/LICENSE_AND_DISTRIBUTION.md).
