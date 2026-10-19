# Providers

Each source is an independent provider registered in `config/provider_registry.yml` and
implemented under `src/afid/providers/`. `afid providers test` checks that declared
capabilities equal the implementation. Verification date for all entries: **2026-10-18**.

## Status

| Provider | Brands | Status | Discover | Download | Local import + verify | Tested with |
|---|---|---|---|---|---|---|
| `lineageos_wiki` | samsung, xiaomi, poco, redmi, oneplus, google_pixel, nothing | metadata_only | yes | no | no | fixtures + one real run (see below) |
| `local_firmware` | all registered | active | no | no | yes | fixtures (ZIP, TGZ, ext4, directories) |
| `android_dumps_gitlab` | all registered (from build.prop) | metadata_only | dump branches | selective file fetch only | no | fixtures + real runs ([SOURCE_INTEGRATION.md](SOURCE_INTEGRATION.md#live-results)) |
| `tadiphone_dumps` | all registered (from build.prop) | metadata_only | dump branches | selective file fetch only | no | fixtures + real runs |
| `dumprx` | all registered | manual_import_required | no | no | yes (through DumprX) | fake install + one real offline run ([DUMPRX_INTEGRATION.md](DUMPRX_INTEGRATION.md)) |
| `google_pixel` | google_pixel | manual_import_required | no | no | yes | fixtures |
| `samsung` | samsung | manual_import_required | no | no | yes | fixtures (generic path) |
| `xiaomi`, `poco`, `redmi` | one each | manual_import_required | no | no | yes | fixtures (generic path) |
| `oneplus` | oneplus | manual_import_required | no | no | yes | fixtures (generic path) |
| `infinix`, `tecno` | one each | manual_import_required | no | no | yes | fixtures (generic path) |
| `nothing` | nothing | manual_import_required | no | no | yes | fixtures (generic path) |

**No provider downloads firmware archives.** The dump providers fetch individual
extracted files from public dump repositories (metadata analysis, pinned to a commit); they
never clone, never download whole firmware and never write. For every brand, either no official documented and
automatable download API was verified, or (Pixel) access requires accepting terms in a
browser, which AFID does not bypass. Real firmware enters AFID only through `afid ingest
--local`, after the user obtained it under the source's terms.

"Tested with fixtures" means the code path was exercised with synthetic packages built by the
tests. No real vendor firmware was ingested while building this release.

## Common behaviour

- **Rate limits / timeouts** (all network providers): `HTTP_TIMEOUT` (60 s),
  `RETRY_LIMIT` (3) with exponential backoff from 2 s and `Retry-After` honoured, at least
  `max(network.min_interval_seconds, RATE_LIMIT_DELAY)` (1 s) between requests to one host,
  HTTPS only, hosts limited to `allowed_hosts` on every redirect hop
  ([RESOURCE_BUDGETS.md](RESOURCE_BUDGETS.md)).
- **Health**: `afid providers health [--provider <id>]` makes one cheap live request per
  remote provider (dump hosts: one project listing page and the rate-limit headers);
  `dumprx` reports its run guards.
- **Authentication**: none of the current providers needs credentials. A future provider that
  does names an environment variable in `auth.token_env`; the value comes from the environment
  or GitHub Secrets and is redacted from error messages.
- **Local import**: `afid ingest --local <path> --provider <id> [--sha256 <official>]`.
  Archives are verified by SHA-256 when an official checksum is supplied; the archive's own
  SHA-256 is always recorded.

## lineageos_wiki

- **Source**: https://github.com/LineageOS/lineage_wiki, `_data/devices/*.yml` (owned by the
  LineageOS project; community-maintained).
- **Discovery**: shallow, sparse `git clone` of `_data/devices/` into the AFID cache (or an
  existing checkout via `settings.checkout_dir` / `$AFID_LINEAGE_WIKI_DIR`). Each YAML file is
  parsed with `yaml.safe_load`. Revision marker per file: git blob SHA-1; index revision: HEAD.
- **Brand mapping**: `settings.brand_rules`; for example vendor `Xiaomi` with a name starting
  `Redmi` maps to `redmi`. The basis is stored as `brand_inference` and marked unverified.
- **Output**: staging candidates (`community_reported`), never verified devices. Shared
  codenames (e.g. `_variant1`/`_variant2` files) become separate candidates.
- **License**: CC BY-SA 3.0, `declared_by_source`. The repository has no license file for
  `_data/devices/` (`licenses/` covers the theme, MIT, and Navgoco, BSD), but its footer template
  `_includes/layout/footer.html` declares CC BY-SA 3.0 for every page generated from the data;
  confirmed on the live device pages. Records carry attribution and share-alike terms;
  `distribution_default: metadata_only`. See `docs/LICENSE_AND_DISTRIBUTION.md`.
- **Known limitations**: covers only devices with LineageOS ports; no Infinix or TECNO entries
  (vendor values checked 2026-10-18); release dates and SoC strings are as written by
  contributors.
- **Real run (2026-10-18)**: against upstream commit `2c365be2b66336e4da1f3ca3bdd71c17eb819005`:
  764 files, 353 in-scope candidates (samsung 118, redmi 66, xiaomi 59, oneplus 55,
  google_pixel 36, poco 17, nothing 2), 411 out of scope, 0 parse errors. Written to
  `database/staging/unresolved/lineageos_wiki/` (353 records, all `unverified`); a repeat run
  wrote nothing.
- **Tests**: `tests/providers/test_providers.py::test_lineage_discovery_from_fixture`,
  `tests/integration/test_updates_cli.py` (write, rerun-unchanged, failure keeps data,
  changed/removed detection), `tests/integration/test_ingest.py::test_staging_candidate_promoted_on_verified_ingest`.

## google_pixel

- **Source**: https://developers.google.com/android/images (factory images) and
  https://developers.google.com/android/ota (full OTAs), owned by Google.
- **Why no discovery/download**: on 2026-10-18 the served HTML contained no image tables; they
  appear only after accepting the terms in a browser. The page states the files "are for
  personal use on your Nexus or Pixel device and have usage restrictions based on licensing
  terms".
- **Ingestion**: download the factory ZIP or OTA ZIP yourself, then
  `afid ingest --local <file> --provider google_pixel --sha256 <SHA-256 shown on the page>`.
  Factory ZIPs contain a nested `image-*.zip` with partition images (handled as nested
  archives); full OTAs contain `payload.bin` (needs `payload-dumper-go`) and
  `META-INF/com/android/metadata` (parsed for `pre-device`, `post-build`).
- **Filename hints**: `<codename>-<build>-factory-<8 hex>.zip` and
  `<codename>-ota-<build>-<8 hex>.zip` are recognised as hints only; identity always comes from
  the firmware contents.
- **License**: proprietary; components are `user_supplied`, never published.
- **Tests**: end-to-end ingest of a synthetic factory-style ZIP with official-checksum match
  (`tests/integration/test_ingest.py`), filename hints (`test_pixel_filename_hints_are_hints`).

## samsung

- **Source**: none automated. Samsung's open-source portal (opensource.samsung.com) provides
  kernel/platform source, not firmware, and returned HTTP 403 to automated requests.
- **Ingestion**: packages you obtained yourself: TAR / `.tar.md5` (TAR is read natively; the MD5
  trailer is not verified), `.lz4` images need `lz4`, then ext4/EROFS/sparse/super handling.
- **Limitations**: Samsung package layout not tested with real firmware.

## xiaomi, poco, redmi

- **Source**: none automated. Separate providers keep POCO and Redmi identities distinct
  although packaging is shared.
- **Ingestion**: recovery ROM ZIP (`payload.bin` -> `payload-dumper-go`) or fastboot `.tgz`
  (TAR+gzip, native; images inside then extracted).
- **Limitations**: not tested with real firmware.

## oneplus, nothing

- **Source**: none automated. Full OTA ZIPs (`payload.bin` -> `payload-dumper-go`).
- **Limitations**: not tested with real firmware.

## infinix, tecno

- **Source**: no public official firmware distribution verified. Local import only.
  `Techno` is accepted as a search alias for TECNO (`config/brands.yml`).

## local_firmware

Generic import of an archive, a partition image, a directory of images, or an already extracted
tree (`<root>/<partition>/...`). Brand comes from `--brand` or build.prop
(`ro.product.vendor.brand` + model prefix rules in `config/brands.yml`).

## android_dumps_gitlab, tadiphone_dumps

Public GitLab groups of DumprX-style firmware dumps: one project per device, one branch per
firmware build. Verified layout, sizes, rate limits and live results:
[SOURCE_INTEGRATION.md](SOURCE_INTEGRATION.md). Settings in the registry: `api_base`,
numeric `group` id, `group_path`, `max_project_pages`, `min_projects` (sanity floor),
`max_branches_per_project`, `max_tree_pages`. Discovery is incremental by project
`last_activity_at`; analysis is `afid firmware analyze` ([MATRIX_PIPELINE.md](MATRIX_PIPELINE.md)).

## dumprx

A tool provider: `afid firmware dump --input <local file> --ingest` runs the pinned DumprX
offline and ingests the result ([DUMPRX_INTEGRATION.md](DUMPRX_INTEGRATION.md)).

## Adding a provider

1. Confirm the source's access method and terms; document them in an issue
   (`.github/ISSUE_TEMPLATE/add_source.yml`). Never automate around logins, CAPTCHAs,
   paywalls or click-through terms.
2. Subclass `FirmwareProvider` in `src/afid/providers/`, set `CAPABILITIES`, and implement
   only the operations the source really supports.
3. Add a registry entry with real `source_urls`, `allowed_hosts`, `limitations`,
   `distribution_default` and `last_verified`.
4. Add fixture-based tests (no network). `afid providers test` must pass.
5. Add a section to this file.
