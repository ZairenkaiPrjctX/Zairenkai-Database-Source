# Database schema

All records are JSON, validated by the JSON Schemas (draft 2020-12) in `schemas/`. Every record
carries `schema_version`; the validator rejects versions it does not know.

## Layout (codename-first)

```
database/
├── devices/<brand_id>/<codename_key>/device.json
├── firmware/<brand_id>/<codename_key>/<firmware_key>/firmware.json
├── components/<brand_id>/<codename_key>/<firmware_key>/<group>.json
├── dependencies/<brand_id>/<codename_key>/<firmware_key>.json
├── dependencies/library_map.json         (generated)
├── sources/<provider_id>.json            (discovery snapshots)
├── staging/unresolved/<provider_id>/<candidate_id>.json
├── updates/                              (update reports, when written)
├── index.json                            (generated)
└── statistics.json                       (generated)
```

`<group>` is one of `thermal_hal`, `thermal_config`, `power_hal`, `power_config`,
`vendor_libraries`, `init`, `vintf`, `metadata`, `unknown` (mapping from categories in
`src/afid/models.py`).

## Identifiers

| ID | Rule | Example |
|---|---|---|
| `codename` | verbatim from firmware evidence | `Mi439` |
| `codename_key` | `codename.lower()`; used for directory names | `mi439` |
| `device_id` | `<brand_id>_<codename_key>` | `redmi_mi439` |
| `firmware_key` | sanitized build id, plus `_<region>`/`_<channel>` when given | `V12.5.1.0.QCMMIXM_global` |
| `firmware_id` | `<device_id>__<firmware_key>` | `redmi_mi439__V12.5.1.0.QCMMIXM_global` |
| `component_id` | `c_` + SHA-256(firmware_id, partition, path)[:20] | `c_3fa9...` |
| `edge_id` | `d_` + SHA-256(firmware_id, type, from, to_name)[:20] | `d_91c0...` |

IDs are derived from identity fields, never from mutable paths alone, so re-ingesting the same
build reproduces the same IDs.

## Records

**device.json**: `codename_status` is always `verified` in `devices/`; `sources` must contain
at least one verifying evidence item (`firmware_build_prop`, `official_ota_metadata`,
`official_source`). Community evidence may be added as corroboration. Marketing names,
model numbers, regional variants and aliases are searchable metadata, never directory names.
Rebrands and shared codenames are expressed with `canonical_device_id` or `shared_identity`
(`relation`: `rebrand`, `regional_variant`, `shared_codename_distinct_device`) with evidence.

**firmware.json**: build id, variant (region/channel), Android release, API level, security
patch levels, fingerprint, source (provider, source type, archive name/SHA-256/size, official
checksum match), partition layout, ingestion status and tools, distribution status, component
groups and count, warnings/errors.

**<group>.json**: component records: category/subcategory, partition and partition-relative
path, file type, size, SHA-256, symlink target, classification (method, rule ids, confidence,
reasons, SoC tags), parser result, category-specific `details` (ELF, init, VINTF, config
summary, build props), license and distribution status, provenance, dependency refs,
`duplicate_of` (same SHA-256 within the build).

**dependencies/<build>.json**: edges with `type` (`dt_needed`, `init_service_binary`,
`vintf_declares_hal`, `config_reference`, `hal_config`), `status` (`resolved`, `inferred`,
`unresolved`) and `evidence`.

**staging candidate**: unverified identity (`unresolved` or `community_reported`), evidence,
and the reason it is not verified.

## Status vocabularies

- Ingestion: `discovered`, `download_pending`, `downloaded`, `extracted`, `validated`,
  `license_review_required`, `published`, `failed`, `unchanged`, `unavailable`.
- Distribution: `allowed`, `restricted`, `unknown` (default), `user_supplied`, `metadata_only`.
- Change report: `added`, `changed`, `removed_from_source`, `unavailable`, `checksum_changed`,
  `dependency_added`, `dependency_removed`, `license_changed`, `unverified`.

## Validation (`afid database validate`)

Schemas; brand and codename directory names match records; device ids follow the rule;
verified devices have verifying evidence; firmware references an existing device and sits in
its directory; components reference existing firmware and sit in the right group file;
`component_count`/`component_groups` match; `duplicate_of` points to same-content records;
dependency edges reference existing components; aliases are not used as another device's
codename without a recorded relation; shared codenames across brands without a relation are
warnings; `database/` holds JSON only; `--check-index` fails when generated files are stale.

## Determinism

JSON is written with sorted keys and LF newlines, only when content changes. Timestamps that
only reflect "checked again" (`last_checked_at`, `last_verified_at`, `ingested_at`,
`retrieved_at`) are ignored when deciding whether to rewrite. Generated files contain no
timestamps; `statistics.json` includes `database_digest`, a SHA-256 over all source records.

## Schema migration strategy

1. Additive, backward-compatible changes (new optional field) keep `schema_version` "1.0"
   only if every existing record still validates.
2. Anything else introduces a new version ("1.1", "2.0"): add it to `KNOWN_SCHEMA_VERSIONS`,
   ship a migration command that rewrites records deterministically, migrate in one pull
   request, and keep the old version readable until the migration has merged.
3. CI (`afid database validate`) fails on unknown versions, so a partial migration cannot merge.
